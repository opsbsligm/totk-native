"""Measure one Deck pool-backing arm on an installed release: import (the default) or host-visible copies.

Runs on the Steam Deck. The game starts inside bwrap with its own data, cache and config, so a
measurement never touches the player's save: the save is copied in, and the run is accepted only when
the fixture still matches the inventory taken before the run. Foreground ownership is verified against
Gamescope's focused-app property before every screenshot and on every sample, and the root-window
properties the harness sets are restored at the end.

Frame data comes from the game's own per-frame TSV (DM_NVN_TSV with the call-count rows off), so the
same numbers are readable over SSH on any device. The queue timings are host submission intervals, not
GPU execution measurements, and the game's present cadence is not the panel's scanout.

usage: python3 tools/deck_pool_ab.py run --dir <case-dir> --release <release-dir> \
           --pool-mode import|copy --commit <source-commit> [--sample-seconds 50]
           (copy only) --pool-mem cached|uncached|device selects the memory the copies live in
           --gpu-passprof-after <seconds> times every render pass of a window of presents that opens that far
           into the run (the game aggregates it by pass kind and logs the breakdown; diagnostic)
       python3 tools/deck_pool_ab.py summarize --dir <case-dir>   # one completed case
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import stat
import statistics
import subprocess
import time

APPID = 4131851805          # this game's Deck library entry (the signed value in shortcuts.vdf aside)
MAX_LOG_BYTES = 20 * 2**20  # a runaway log aborts the sample rather than filling the volume
MAX_TSV_BYTES = 32 * 2**20
MIN_FREE_BYTES = 2 * 2**30
MENU_SETTLE_FRAMES = 100
WORLD_MIN_DRAWS = 2001
# The Deck's panel size, which is also the size the game is played at. The presenting window is a measured
# variable (run --window-size), but it is NOT the scene size: with the game's dynamic resolution patched off
# (tools/lifter/patches.py drs_off) the scene targets stay at the mode's fixed size, so a smaller window only
# shrinks the swapchain and the upscale. The knob that actually moves scene pixels is TOTK_OPERATION_MODE
# (handheld 1280x720 against docked 1600x900), passed with --env.
WINDOW_W, WINDOW_H = 1280, 800
REQUIRED_METRICS = ['@frame_ms', '@nvn_ms', '@sub_wall_ms', '@sub_cpu_ms',
                    '@queue_lock_ms', '@queue_api_ms', '@present_effective_ticks']
# Variables the harness owns: the pool backing (which of the two is set defines the arm), the isolated save/cache
# paths, the TSV output, the input fifo, and the profiling switches. They are cleared from the inherited environment
# so a case measures the arm and nothing else, and an --env arm may not set them either.
RESERVED_ENV = ('TOTK_POOL_COPY', 'TOTK_POOL_IMPORT', 'TOTK_WRITE_WATCH', 'TOTK_POOL_MEM',
                'TOTK_INPUT_SCRIPT', 'TOTK_INPUT_FIFO', 'LD_PRELOAD', 'TOTK_HEADLESS', 'TOTK_SHOT',
                'TOTK_GPU_PASSPROF')


def inventory(root):
    """Size and content of every regular file under root, with no symlink allowed anywhere."""
    rows = {}
    for path in sorted(root.rglob('*')):
        if path.is_file():
            assert not path.is_symlink(), path
            with path.open('rb') as stream:
                rows[str(path)] = dict(size=path.stat().st_size,
                                       sha256=hashlib.file_digest(stream, 'sha256').hexdigest())
    return rows


def rel_inventory(root):
    return {Path(key).relative_to(root).as_posix(): value for key, value in inventory(root).items()}


class Deck:
    """The X11/Gamescope side of a run: ownership handshake, captures, read-only device sampling."""

    def __init__(self, case, env):
        self.case = case
        self.env = dict(env, DISPLAY=':0')
        self.window = None
        self.original = {}
        self.report = dict(appid=APPID, samples=0, valid_foreground_sample=False, captures=[])

    def output(self, args):
        return subprocess.check_output(args, env=self.env, text=True, timeout=6).strip()

    def call(self, args):
        return subprocess.run(args, env=self.env, check=True, capture_output=True, text=True,
                              timeout=8).stdout

    def set_property(self, key, value):
        self.call(['xprop', '-root', '-f', key, '32c', '-set', key, str(value)])

    def bind_game(self, pid, size=(WINDOW_W, WINDOW_H)):
        rows = self.output(['xdotool', 'search', '--pid', str(pid)]).split()
        assert len(rows) == 1, f'expected one window, found {rows}'
        self.window = rows[0]
        self.report['game_window'] = self.window
        self.report['window_size'] = list(size)
        self.call(['xprop', '-id', self.window, '-f', 'STEAM_GAME', '32c', '-set', 'STEAM_GAME', str(APPID)])
        self.call(['xdotool', 'windowsize', self.window, str(size[0]), str(size[1])])
        for key in ('GAMESCOPECTRL_BASELAYER_WINDOW', 'GAMESCOPECTRL_BASELAYER_APPID'):
            raw = self.output(['xprop', '-root', key])
            self.original[key] = raw.split(' = ', 1)[1] if ' = ' in raw else None
        (self.case / 'focus-before.json').write_text(json.dumps(self.original, indent=2) + '\n')

    def state(self):
        text = self.output(['xprop', '-root', 'GAMESCOPE_FOCUSED_APP', '_NET_ACTIVE_WINDOW'])
        active = re.search(r'window id # (0x[0-9a-fA-F]+)', text)
        app = re.search(r'GAMESCOPE_FOCUSED_APP\(CARDINAL\) = (\d+)', text)
        active_id = int(active.group(1), 16) if active else None
        own_id = int(self.window)            # xdotool reports the same window in decimal
        owner = ''
        if active_id and active_id != own_id:
            probe = subprocess.run(['xdotool', 'getwindowpid', str(active_id)], env=self.env,
                                   capture_output=True, text=True, timeout=6)
            owner = (probe.stdout or probe.stderr).strip().replace('\n', ' ')[:120]
        return dict(exact_window=bool(active_id == own_id),
                    exact_app=bool(app and int(app.group(1)) == APPID),
                    active_window=active_id, active_window_owner=owner, properties=text)

    def focus(self):
        """Bring the game to the front and confirm Gamescope agrees on both app id and window id."""
        row = {}
        consecutive = 0
        for attempt in range(40):
            if attempt in (0, 3, 11, 23):
                self.set_property('GAMESCOPECTRL_BASELAYER_APPID', f'413091, {APPID}, 769')
                self.set_property('GAMESCOPECTRL_BASELAYER_WINDOW', self.window)
            row = self.state()
            consecutive = consecutive + 1 if row['exact_window'] and row['exact_app'] else 0
            if consecutive >= 4:
                return
            time.sleep(.25)
        self.report['last_focus_state'] = row
        raise RuntimeError('no exact app/window handshake; no input sent. saw: ' + row['properties'][:600])

    def capture(self, name):
        self.focus()
        path = self.case / name
        result = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab',
                                 '-window_id', self.window, '-i', ':0', '-frames:v', '1', str(path)],
                                env=self.env, capture_output=True, text=True, timeout=8)
        assert path.is_file() and path.read_bytes().startswith(bytes.fromhex('89504e470d0a1a0a')), result.stderr[-500:]
        self.report['captures'].append(dict(file=name, bytes=path.stat().st_size))

    def write_command(self, line):
        """One FIFO line with the foreground verified first; the game logs every line it accepts."""
        self.focus()
        row = self.state()
        assert row['exact_window'] and row['exact_app'], 'foreground lost before input'
        fd = os.open(self.case / 'input.fifo', os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            assert stat.S_ISFIFO(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077
            os.write(fd, line.encode())
        finally:
            os.close(fd)

    def send(self, sequence, key='K'):
        """One confirmed click through a private owner-only FIFO.

        K represents the Deck's south button. The menu policy maps it to the game's confirm bit.
        Use J on older releases where the keyboard sends the game's original A bit directly."""
        self.write_command(f'{sequence}:{key}*10\n')

    def stick(self, sequence, lx=0, ly=0, rx=0, ry=0, hold=60):
        """Hold the sticks (int16 units) for `hold` frames. TOTK walks Link with the left stick only —
        the d-pad opens menus but never moves him — so a scene that explores needs this channel."""
        self.write_command(f'{sequence}:A,{lx},{ly},{rx},{ry}*{hold}\n')

    def device_sample(self):
        row = dict(time=time.time(), **self.state())
        for device in Path('/sys/class/drm').glob('card[0-9]*/device'):
            for name in ('gpu_busy_percent', 'mem_info_vram_used'):
                path = device / name
                if path.is_file():
                    try:
                        row[str(path)] = path.read_text().strip()
                    except OSError:
                        pass
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                row[line.split(':', 1)[0]] = line.split(':', 1)[1].strip()
        return row

    def device_state(self):
        power = {}
        for hw in Path('/sys/class/hwmon').glob('hwmon*'):
            for name in ('name', 'power1_cap', 'power1_average', 'temp1_input'):
                path = hw / name
                if path.is_file():
                    try:
                        power[str(path)] = path.read_text().strip()
                    except OSError:
                        pass
        props = self.output(['xprop', '-root']).splitlines()
        return dict(power_limits=power,
                    gamescope_rate_properties=[line for line in props
                                               if re.search(r'GAMESCOPE.*(FPS|RATE|LIMIT|REFRESH|VRR)', line)])

    def restore_focus(self):
        restored = {}
        for key, value in self.original.items():
            if value is None:
                self.call(['xprop', '-root', '-remove', key])
            else:
                self.set_property(key, value)
            raw = self.output(['xprop', '-root', key])
            restored[key] = raw.split(' = ', 1)[1] if ' = ' in raw else None
        self.report['focus_restored'] = restored == self.original
        return self.report['focus_restored']


def parse_size(text):
    """`1280x800` as (1280, 800), rejecting anything that is not a smaller size of the panel's own aspect ratio.

    Only sizes of the panel's own shape are allowed, so a reduced window cannot change how much of the world is on
    screen or stretch it. Cross-multiplied, so the match is exact rather than rounded. Note what this does NOT do:
    with the game's dynamic resolution patched off the scene keeps its mode's fixed size, so a smaller window measures
    the swapchain and upscale path only. Measured on the Deck: 1280x800, 960x600 and 640x400 run within 0.4 ms of each
    other, which is what told us the scene targets do not track the window. To move scene pixels, run an arm of
    TOTK_OPERATION_MODE (see --env); handheld against docked is 1280x720 against 1600x900.
    """
    match = re.fullmatch(r'(\d+)x(\d+)', text.strip())
    if not match:
        raise SystemExit(f'--window-size wants WxH (e.g. 960x600), got {text!r}')
    w, h = int(match[1]), int(match[2])
    if w * WINDOW_H != h * WINDOW_W:
        raise SystemExit(f'--window-size {w}x{h} is not the panel aspect ratio of {WINDOW_W}x{WINDOW_H} '
                         f'(e.g. 960x600, 640x400)')
    if w < WINDOW_W // 2 or w > WINDOW_W:
        raise SystemExit(f'--window-size {w}x{h}: keep the width between {WINDOW_W // 2} and the panel at {WINDOW_W}')
    return w, h


def arm_env(items, baseline):
    """One A/B arm's extra environment, checked against the variables the harness itself owns.

    An arm is meant to move exactly one development switch (e.g. TOTK_VK_NO_LOCAL_BARRIER=1), so a name the harness
    already sets is refused: otherwise the arm silently moves the baseline under the measurement -- the pool mode, the
    isolated save paths and the TSV output are what makes two runs comparable at all.
    TOTK_POOL_IMPORT is reserved even in the copy arm, where the harness deliberately leaves it unset: the runtime
    prefers an import over a copy, so setting it from an arm would flip the baseline without appearing in it.
    """
    extra = {}
    for item in items:
        key, sep, value = item.partition('=')
        if not sep or not key or not key.replace('_', '').isalnum() or not key[0].isalpha():
            raise SystemExit(f'--env wants KEY=VALUE, got {item!r}')
        if key in baseline or key in RESERVED_ENV:
            raise SystemExit(f'--env {key}: the harness sets this variable itself, an arm may not override it')
        extra[key] = value
    return extra


def thread_cpu(pid):
    """Per-thread CPU time of the running game, so a sample says which thread is spending it."""
    rows = {}
    for task in Path(f'/proc/{pid}/task').iterdir():
        try:
            raw = (task / 'stat').read_text()
            tail = raw.rsplit(') ', 1)[1].split()
            name = raw[raw.index('(') + 1:raw.rfind(')')]
            fields = dict(name=name, user_ticks=int(tail[11]), kernel_ticks=int(tail[12]))
        except (OSError, ValueError):
            continue        # a thread that exited mid-snapshot
        rows[task.name] = fields
    return dict(ticks_per_second=os.sysconf('SC_CLK_TCK'), threads=rows)


def last_frame(path):
    """Highest frame number in the timing TSV, reading only its end (called once per sample second)."""
    with path.open('rb') as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - 65536))
        tail = stream.read().decode('utf-8', 'replace')
    numbers = [int(line.split('\t', 1)[0]) for line in tail.splitlines() if line.split('\t', 1)[0].isdigit()]
    return max(numbers) if numbers else 0


def render_window(path, offset):
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_LOG_BYTES:
        raise RuntimeError('the render log passed its budget')
    with path.open('rb') as stream:
        stream.seek(offset)
        counters = re.findall(rb'\[vk\] present (\d+): shaders loaded [^\n]*?; draws (\d+),', stream.read())
    if len(counters) < 2:
        return None
    first, before = map(int, counters[-2])
    last, after = map(int, counters[-1])
    if last <= first or after < before:
        return None
    return dict(first_present=first, last_present=last, draws_per_frame=(after - before) / (last - first))


def wait_until(child, deadline, probe, message):
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError('the game exited while waiting for ' + message)
        result = probe()
        if result:
            return result
        time.sleep(.5)
    raise RuntimeError('timed out waiting for ' + message)


def thread_cpu_by_name(pid, previous):
    """CPU milliseconds per thread *name* since the previous call, so a sample says who was busy that second.

    Named rather than per-thread-id: the recording pool reuses names, and the point is which kind of work ran.
    Threads that appeared or exited between the snapshots are counted under their own name from/to zero.
    """
    now = thread_cpu(pid)
    out = {}
    for row in now['threads'].values():
        out[row['name']] = out.get(row['name'], 0.0) + row['user_ticks'] + row['kernel_ticks']
    ticks = now['ticks_per_second']
    delta = {name: round((value - previous.get(name, value)) * 1000 / ticks, 1) for name, value in out.items()}
    return {name: value for name, value in delta.items() if value > 0}, out


def frames_in(case, first, last):
    """The complete frames of one sample window as frame -> metric -> value."""
    frames = {}
    for line in (case / 'frame-timing.tsv').read_text().splitlines():
        fields = line.split('\t')
        if len(fields) != 3 or not fields[0].isdigit():
            continue
        number = int(fields[0])
        if first < number < last:
            row = frames.setdefault(number, {})
            assert fields[1] not in row, (number, fields[1])
            row[fields[1]] = float(fields[2])
    assert set(frames) == set(range(first + 1, last)), 'the game stopped writing frames mid-sample'
    assert all(all(key in row for key in REQUIRED_METRICS) for row in frames.values())
    return frames


# The game's own per-pass breakdown of the profiled window, as the backend logs it (backend_vk.c pp_report): the total
# line names the presents covered, then one row per pass kind (extent, colour count, formats, first shader) ranked by
# the GPU time it took over the window.
PASS_PROFILE = re.compile(r'pass profile of presents (?P<from>\d+)\.\.(?P<to>\d+): (?P<passes>\d+) passes over '
                          r'(?P<frames>\d+) presents, (?P<inpass>[\d.]+) ms in passes, (?P<between>[\d.]+) ms between '
                          r'them, (?P<span>[\d.]+) ms first to last \((?P<per_present>[\d.]+) ms in passes per present\)')
PASS_LINE = re.compile(r'(?P<ms>[\d.]+) ms x(?P<count>\d+) +(?P<kind>\S+) +(?P<draws>\d+) draws avg +per present '
                       r'(?P<per_present>[\d.]+) ms + peak (?P<peak>[\d.]+) ms')


def attribute_long_frames(frames, samples, threshold=50.0, top=4):
    """Which thread names were busy in the second that held each long frame, against the sample's own median.

    One sample row covers the second before it was taken: its CPU deltas and the frame number read at the end of
    that second. The game's TSV timestamps are seconds since process start, so the row that reports frame F ties
    the two clocks at F's own `@t_s`; that offset puts a long frame in a second. A second holds about 30 frames, so
    this names a candidate, and only a candidate: with one long frame in the second it is the same second's work,
    not proof that the work is the cause.
    """
    # Counted on the frame interval alone: a long frame the clock cannot place is still a long frame that was seen,
    # and dropping it here would report a cleaner run than the sample actually was.
    long = sorted((f for f, row in frames.items() if row.get('@frame_ms', 0) > threshold),
                  key=lambda f: frames[f].get('@t_s', 0.0))
    if not long or not samples:
        return dict(long_frames=len(long), attributed=0, note='no long frame in this window or no per-second samples')
    anchors = [(s['time'], s['last_frame']) for s in samples if 'last_frame' in s and 'thread_cpu_ms' in s]
    if not anchors:
        return dict(long_frames=len(long), attributed=0, note='the samples carry no per-thread CPU')
    offsets = []
    by_frame = {f: row for f, row in frames.items()}
    for wall, frame in anchors:
        row = by_frame.get(frame)
        if row and '@t_s' in row:
            offsets.append(wall - row['@t_s'])
    if not offsets:
        untied = ('the timing TSV carries no @t_s row: the sample clock cannot be tied to the frame clock'
                  if not any('@t_s' in row for row in frames.values())
                  else 'no sampled frame is present in the timing TSV')
        return dict(long_frames=len(long), attributed=0, note=untied)
    offset = statistics.median(offsets)
    busy = defaultdict(list)
    for sample in samples:
        for name, ms in (sample.get('thread_cpu_ms') or {}).items():
            busy[name].append(ms)
    median = {name: statistics.median(values) for name, values in busy.items()}
    rows = []
    for f in long:
        if '@t_s' not in frames[f]:
            continue
        wall = offset + frames[f]['@t_s']
        holder = None
        for sample in samples:
            if 'thread_cpu_ms' not in sample or 'last_frame' not in sample:
                continue
            if sample.get('prev_time', sample['time'] - 1) <= wall < sample['time']:
                holder = sample
                break
        if holder is None:
            continue
        excess = sorted(((name, ms - median.get(name, 0.0)) for name, ms in holder['thread_cpu_ms'].items()),
                        key=lambda pair: -pair[1])[:top]
        rows.append(dict(frame=f, frame_ms=round(frames[f]['@frame_ms'], 2), second=round(wall, 2),
                         busy_in_second=holder['thread_cpu_ms'],
                         above_the_window_median=[dict(thread=name, ms=round(ms, 1)) for name, ms in excess]))
    return dict(long_frames=len(long), attributed=len(rows), clock_offset_s=round(offset, 3),
                window_median_thread_cpu_ms={name: round(value, 1) for name, value in median.items()},
                resolution='one sample second covers about 30 frames: a candidate, not a cause',
                frames=rows)


def summarize(case):
    """Percentiles over the frames the verified sample window covers exclusively."""
    sampling = json.loads((case / 'sampling-report.json').read_text())
    session = json.loads((case / 'session.json').read_text())
    result = json.loads((case / 'result.json').read_text())
    assert sampling['valid_foreground_sample'] and sampling['focus_restored'], 'unusable sample'
    assert result['player_saves_unchanged'], 'the player save changed'
    first, last = sampling['timing_start_frame'], sampling['timing_end_frame']
    frames = frames_in(case, first, last)
    percentile = lambda values, fraction: values[max(0, math.ceil(len(values) * fraction) - 1)]
    metrics = {}
    for key in REQUIRED_METRICS + ['@work_ms', '@proc_cpu_ms', '@upload_ms', '@mprotect_ms']:
        values = sorted(row[key] for row in frames.values() if key in row and row[key] >= 0)
        if values:
            metrics[key] = dict(frames=len(values), mean=statistics.mean(values), p50=percentile(values, .5),
                                p95=percentile(values, .95), p99=percentile(values, .99), max=values[-1])
    intervals = [row['@frame_ms'] for row in frames.values()]
    workload = {}
    for key in ('@draws', '@passes'):
        values = [row[key] for row in frames.values() if key in row and row[key] >= 0]
        if any(values):
            workload[key[1:]] = dict(mean=statistics.mean(values), frames=len(values))
    gpu_busy = {}
    for row in sampling.get('device_samples', []):
        for key, value in row.items():
            if key.endswith('/gpu_busy_percent') and str(value).isdigit():
                gpu_busy.setdefault(key, []).append(int(value))
    # The write-watch scan is booked per code location (nvn_dirty.h NVN_SCAN_WHO_*), so a frame budget spent in it can
    # be traced to the logic that asked. The rows are absent in a build without the attribution, so an empty report here
    # means "not measured", never "nothing to see".
    scan = {}
    for key in {k for row in frames.values() for k in row if k.startswith('@scan_')}:
        values = [row[key] for row in frames.values() if key in row]
        name = key[len('@scan_'):]
        counting = key.endswith('_calls')
        entry = scan.setdefault(name[:-len('_calls')] if counting else name, {})
        if counting:
            entry['calls_per_frame'] = round(statistics.mean(values), 2)
            entry['frames_with_calls'] = sum(1 for value in values if value)
        else:
            entry['ms_per_frame'] = round(statistics.mean(values), 3)
            entry['ms_p99'] = round(percentile(sorted(values), .99), 3)
            entry['frames_over_1ms'] = sum(1 for value in values if value > 1.0)
    total_scan_ms = sum(e.get('ms_per_frame', 0.0) for e in scan.values())
    if scan:
        scan['total'] = dict(ms_per_frame=round(total_scan_ms, 3),
                             share_of_frame_ms=round(100 * total_scan_ms
                                                     / statistics.mean(intervals), 1))
    # The game's own log holds the render-pass breakdown of the profiled frame, if that run asked for one. It is a
    # GPU-side split of one frame, so it is reported apart from the sample-window numbers and never as a frame rate.
    passes = None
    recording_threads = None
    log = case / 'data/ultratears/ultratears.log'
    if log.is_file():
        for line in log.read_text(errors='replace').splitlines():
            if (thread_count := re.search(r'\[vk\] recording threads: (\d+)', line)):
                recording_threads = int(thread_count[1])
            total = PASS_PROFILE.search(line)
            if total:
                passes = dict(presents=[int(total['from']), int(total['to'])], profiled_presents=int(total['frames']),
                              passes=int(total['passes']), in_pass_ms=float(total['inpass']),
                              between_ms=float(total['between']), span_ms=float(total['span']),
                              in_pass_ms_per_present=float(total['per_present']), kinds=[])
                continue
            one = PASS_LINE.search(line)
            if one and passes is not None and len(passes['kinds']) < 12:   # the log already sorts them by time
                # kind: extent/colour count/colour format/depth format/first shader, as pp_report writes it.
                fields = one['kind'].split('/')
                passes['kinds'].append(dict(ms=float(one['ms']), count=int(one['count']), targets=one['kind'],
                                            extent=fields[0], shader=fields[-1], draws_avg=int(one['draws']),
                                            ms_per_present=float(one['per_present']), peak_ms=float(one['peak'])))
    summary = dict(source_commit=session['source_commit'], pool_mode=session['pool_mode'],
                   pool_mem=session.get('pool_mem', 'n/a'),
                   window_size=session.get('window_size', [WINDOW_W, WINDOW_H]),
                   scope=session.get('scope', 'one scene; one window; foreground verified every sample'),
                   scene=session.get('scene', 'not labeled'),
                   settings_sha256=session.get('settings_sha256'),
                   hud_settle_seconds=session.get('hud_settle_seconds'),
                   world_render_window=sampling.get('world_render_window'),
                   verified_focus_samples=sampling['samples'],
                   sample_seconds=sampling['sample_end_time'] - sampling['sample_start_time'],
                   first_exclusive_frame=first, last_exclusive_frame=last, selected_frames=len(frames),
                   game_present_fps_from_mean_interval=1000 / statistics.mean(intervals),
                   frame_threshold_counts={str(cutoff): sum(value > cutoff for value in intervals)
                                           for cutoff in (16.7, 25, 33.4, 50, 100)},
                   metrics_ms=metrics,
                   workload=workload,
                   recording_threads=recording_threads,
                   gpu_busy_percent={key: dict(samples=len(values), median=statistics.median(values))
                                     for key, values in gpu_busy.items()},
                   write_watch_scan=scan or None,
                   present_ticks={key: dict(Counter(row[key] for row in frames.values() if key in row))
                                  for key in ('@present_guest_ticks', '@present_effective_ticks')},
                   gamescope_rate_properties=sampling.get('gamescope_rate_properties', []),
                   power_limits=sampling.get('power_limits', {}),
                   original_save_files=result['player_save_files'],
                   original_saves_unchanged=result['player_saves_unchanged'],
                   focus_restored=True, hardware_validated=False,
                   gpu_passprof_after_s=session.get('gpu_passprof_after_s'),
                   gpu_pass_profile=passes or None,
                   limits=(['GPU pass profiling active: this run is a pass breakdown, not a frame-rate sample']
                           if session.get('gpu_passprof_after_s') else []) +
                          ([('presenting window %dx%d, below the panel: the scene keeps its fixed size, so this run '
                             'measures the upscale path; comparable only with the same size'
                             % tuple(session['window_size']))]
                           if tuple(session.get('window_size', [WINDOW_W, WINDOW_H])) != (WINDOW_W, WINDOW_H) else []) +
                          ['single scene, short sample', 'game present cadence is not panel scanout',
                           'first and last partial frames excluded',
                           'instrumentation overhead not measured separately',
                           'queue timings are host submission intervals, not GPU execution'])
    summary['long_frame_attribution'] = attribute_long_frames(
        frames, json.loads((case / 'sampling-report.json').read_text()).get('device_samples') or [])
    if summary['long_frame_attribution'].get('attributed'):
        summary['limits'].append('long-frame thread attribution is per sample second: a candidate thread, not a cause')
    (case / 'timing-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def run(args):
    case, release = Path(args.dir).resolve(), Path(args.release).resolve()
    size = parse_size(args.window_size)
    for name in ('savagewind', 'ultratears', 'astralchain'):
        assert subprocess.run(['pgrep', '-x', name], capture_output=True).returncode == 1, f'{name} already running'
    assert case.is_dir() and not any(case.iterdir()), f'{case} is not an empty case directory'
    assert not any(p.is_symlink() for p in (case, *case.parents)), 'no symlink allowed in the case path'
    bundle = json.loads((release / 'bundle.json').read_text())
    assert bundle['source_commit'] == args.commit, f'release is {bundle["source_commit"]}, expected {args.commit}'
    assert shutil.disk_usage(case).free > MIN_FREE_BYTES, 'less than 2 GiB free on the target volume'
    fixture = Path(args.save_fixture).resolve()
    assert fixture.is_dir() and any(fixture.rglob('*')), f'no save fixture under {fixture}'

    before = inventory(fixture)
    (case / 'player-before.json').write_text(json.dumps(before, indent=2) + '\n')
    state = case / 'data/ultratears/userdata'
    state.parent.mkdir(parents=True)
    shutil.copytree(fixture, state)
    assert rel_inventory(state) == rel_inventory(fixture), 'the save copy does not match the fixture'
    cache = case / 'cache/totk-native'
    cache.mkdir(parents=True)
    seed = Path.home() / '.cache/totk-native/compiled.bin'
    if seed.is_file() and seed.stat().st_size < 200 * 2**20:      # a bounded seed, not game data
        shutil.copy2(seed, cache / 'compiled.bin')
    (case / 'config').mkdir()
    settings_sha256 = None
    if args.settings_fixture:
        config = Path(args.settings_fixture).expanduser()
        assert config.is_file() and not config.is_symlink() and config.stat().st_size <= 16 * 1024
        contents = config.read_bytes()
        assert len(contents) <= 16 * 1024
        isolated = case / 'config' / 'totk-native'
        isolated.mkdir()
        (isolated / 'control.ini').write_bytes(contents)
        settings_sha256 = hashlib.sha256(contents).hexdigest()
    os.mkfifo(case / 'input.fifo', 0o600)

    env = dict(os.environ, DISPLAY=':0', XDG_RUNTIME_DIR='/run/user/1000',
               DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus',
               XDG_DATA_HOME=str(case / 'data'), XDG_CACHE_HOME=str(case / 'cache'),
               XDG_CONFIG_HOME=str(case / 'config'), SDL_VIDEO_DRIVER='x11', SDL_VIDEODRIVER='x11',
               TOTK_GYRO='1', TOTK_STATS='1',
               DM_NVN_TSV=str(case / 'frame-timing.tsv'), DM_NVN_TSV_CALLS='0')
    for key in ('TOTK_POOL_COPY', 'TOTK_POOL_IMPORT', 'TOTK_WRITE_WATCH', 'TOTK_POOL_MEM',
                'TOTK_INPUT_SCRIPT', 'TOTK_INPUT_FIFO', 'LD_PRELOAD', 'TOTK_HEADLESS', 'TOTK_SHOT'):
        env.pop(key, None)
    env['TOTK_POOL_COPY' if args.pool_mode == 'copy' else 'TOTK_POOL_IMPORT'] = '1'
    pool_mem = ''
    if args.pool_mode == 'copy':
        pool_mem = args.pool_mem
        if pool_mem != 'cached':
            env['TOTK_POOL_MEM'] = pool_mem
    env['TOTK_INPUT_FIFO'] = str(case / 'input.fifo')
    passprof = getattr(args, 'gpu_passprof_after', 0)
    if passprof:
        # A window of frames gets a timestamp pair per render pass; the report waits for the GPU, so that run is a
        # diagnostic and not a frame-rate sample. The window opens after the scene has settled, not at a frame number.
        env['TOTK_GPU_PASSPROF'] = str(passprof)
    # An A/B arm of one development switch: the caller names the variable, the harness owns every other one.
    extra = arm_env(getattr(args, 'env', []), env)
    env.update(extra)

    command = ['bwrap', '--ro-bind', '/', '/', '--proc', '/proc', '--dev-bind', '/dev', '/dev',
               '--bind', str(case), str(case), '--tmpfs', '/tmp',
               '--ro-bind', '/tmp/.X11-unix', '/tmp/.X11-unix', '--die-with-parent', str(release / 'run.sh')]
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    started = time.time()
    sample_deadline = time.monotonic() + args.maximum_seconds - args.sample_seconds
    with (case / 'launch.log').open('xb') as log:
        child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (case / 'session.json').write_text(json.dumps(dict(
        pid=child.pid, started=started, source_commit=args.commit, pool_mode=args.pool_mode,
        pool_mem=pool_mem or 'cached (the default kind)',
        release=str(release), scene=args.scene, save_isolated=True, maximum_seconds=args.maximum_seconds,
        settings_sha256=settings_sha256, hud_settle_seconds=args.hud_settle_seconds,
        window_size=list(size), gpu_passprof_after_s=passprof or None,
        extra_env=extra or None,
        command=command), indent=2) + '\n')

    deck = Deck(case, env)
    sampling = deck.report          # one report: focus state, captures, power and thread CPU, even on failure
    try:
        time.sleep(args.warmup_seconds)
        rows = subprocess.check_output(['pgrep', '-x', 'ultratears'], text=True).split()
        assert len(rows) == 1, f'expected one game process, found {rows}'
        pid = int(rows[0])
        assert Path(f'/proc/{pid}/exe').resolve() == release / 'ultratears', 'a different build is running'
        assert os.getpgid(pid) == child.pid, "the game is not in this run's process group"
        deck.bind_game(pid, size)
        deck.capture('00-title.png')
        timing = case / 'frame-timing.tsv'
        render_log = case / 'data/ultratears/ultratears.log'
        for seq, capture in enumerate(('01-continue.png', '02-select-save.png', '03-confirm-load.png'), 1):
            deck.send(seq, args.confirm_key)
            target = last_frame(timing) + MENU_SETTLE_FRAMES
            wait_until(child, sample_deadline, lambda: last_frame(timing) >= target, 'the next save menu')
            deck.capture(capture)
        deck.send(4, args.confirm_key)
        offset = render_log.stat().st_size if render_log.is_file() else 0
        time.sleep(args.load_seconds)
        if args.min_scene_draws:
            def world_window():
                row = render_window(render_log, offset)
                return row if row and row['draws_per_frame'] >= args.min_scene_draws else None

            sampling['world_render_window'] = wait_until(child, sample_deadline, world_window,
                                                         'a full gameplay render window after loading the save')
        # Deterministic scene driving (development FIFO only): every --stick entry runs here, in order, before the sample.
        for entry in getattr(args, 'stick', []):
            seq, lx, ly, hold = (int(value) for value in entry.split(','))
            deck.stick(seq + 1, lx=lx, ly=ly, hold=hold)
            time.sleep(hold / 30 + 1)           # let the hold elapse at the game's own frame clock
        ready = time.monotonic() + args.hud_settle_seconds
        wait_until(child, sample_deadline, lambda: time.monotonic() >= ready, 'the HUD settle interval')
        deck.capture('03-world-before-sample.png' if args.min_scene_draws else '04-before-sample.png')
        sampling.update(deck.device_state())
        sampling['thread_cpu_start'] = thread_cpu(pid)
        assert timing.is_file() and timing.stat().st_size < MAX_TSV_BYTES, 'no frame timing being written'
        sampling['timing_start_frame'] = max(int(line.split('\t', 1)[0])
                                             for line in timing.read_text().splitlines()
                                             if line.split('\t', 1)[0].isdigit())
        sampling['sample_start_time'] = time.time()
        _, cpu_seen = thread_cpu_by_name(pid, {})   # first real delta is measured from here
        prev_sample_time = sampling['sample_start_time']
        with (case / 'foreground-samples.jsonl').open('x') as stream:
            for _ in range(args.sample_seconds):
                if child.poll() is not None:
                    raise RuntimeError('the game exited during the sample')
                row = deck.device_sample()
                row['prev_time'] = prev_sample_time
                row['last_frame'] = last_frame(timing)
                row['thread_cpu_ms'], cpu_seen = thread_cpu_by_name(pid, cpu_seen)
                prev_sample_time = row['time']
                stream.write(json.dumps(row) + '\n')
                stream.flush()
                sampling['samples'] += 1
                if not row['exact_window'] or not row['exact_app']:
                    raise RuntimeError('foreground lost; partial samples retained')
                if (case / 'launch.log').stat().st_size > MAX_LOG_BYTES:
                    raise RuntimeError('the launch log passed its budget')
                time.sleep(1)
        sampling['sample_end_time'] = time.time()
        sampling['device_samples'] = [json.loads(line) for line in
                                      (case / 'foreground-samples.jsonl').read_text().splitlines() if line.strip()]
        assert timing.stat().st_size < MAX_TSV_BYTES, 'the timing file passed its budget'
        sampling['timing_end_frame'] = max(int(line.split('\t', 1)[0])
                                          for line in timing.read_text().splitlines()
                                          if line.split('\t', 1)[0].isdigit())
        sampling['valid_foreground_sample'] = True
        sampling['thread_cpu_end'] = thread_cpu(pid)
        deck.capture('04-world-after-sample.png' if args.min_scene_draws else '05-after-sample.png')
    except BaseException as error:              # the game is stopped and the focus restored either way
        sampling['error'] = str(error)
        raise
    finally:
        stopped = child.poll() is None
        if stopped:
            os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        sampling['focus_restored'] = deck.restore_focus()
        (case / 'sampling-report.json').write_text(json.dumps(sampling, indent=2) + '\n')

    saves_unchanged = inventory(fixture) == before
    result = dict(returncode=child.returncode, elapsed_seconds=time.time() - started,
                  requested_stop=stopped, player_saves_unchanged=saves_unchanged,
                  player_save_files=len(before), screenshot_exists=any(case.glob('*.png')),
                  focus_restored=sampling['focus_restored'], hardware_validated=False,
                  scope='frame-time sample with continuously verified foreground; physical input not validated')
    (case / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    assert saves_unchanged, 'the save fixture changed: keeping the case for inspection'
    print(json.dumps(summarize(case), indent=2))


def main():
    both = argparse.ArgumentParser(add_help=False)
    both.add_argument('--dir', required=True, help='this case only; never shared between arms')
    top = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = top.add_subparsers(dest='command', required=True)
    run_parser = commands.add_parser('run', parents=[both], help='measure one arm on the Deck')
    run_parser.add_argument('--release', required=True, help='release directory with bundle.json and run.sh')
    run_parser.add_argument('--pool-mode', required=True, choices=('import', 'copy'))
    run_parser.add_argument('--pool-mem', default='cached', choices=('cached', 'uncached', 'device'),
                            help='which host-visible memory the copies use (copy arm only)')
    run_parser.add_argument('--commit', required=True, help='source_commit the release must report')
    run_parser.add_argument('--save-fixture', default=str(Path.home() / '.local/share/ultratears/'
                                                          'test-profiles/v8-opening-20261102/ultratears/userdata'))
    run_parser.add_argument('--settings-fixture', help='copy this control.ini into the isolated case before launch')
    run_parser.add_argument('--scene', required=True,
                            help='what the run is standing in, from this case\'s own screenshots '
                                 '(the harness cannot know the game\'s location)')
    run_parser.add_argument('--confirm-key', choices=('K', 'J'), default='K',
                            help='use J for an older release that does not route keyboard input through the menu policy')
    run_parser.add_argument('--min-scene-draws', type=int, default=WORLD_MIN_DRAWS,
                            help='minimum mean draws in a complete Vulkan report window after the final confirmation; '
                                 'use 0 only for a deliberate menu diagnostic')
    run_parser.add_argument('--warmup-seconds', type=int, default=30)
    run_parser.add_argument('--load-seconds', type=int, default=30)
    run_parser.add_argument('--hud-settle-seconds', type=int, default=12,
                            help='wait this long after loading and optional movement before the start screenshot and sample')
    run_parser.add_argument('--sample-seconds', type=int, default=50)
    run_parser.add_argument('--maximum-seconds', type=int, default=240)
    run_parser.add_argument('--window-size', default=f'{WINDOW_W}x{WINDOW_H}',
                            help='presenting window size WxH; TOTK renders its scene at this size, so it is the '
                                 'knob that separates pixel-bound GPU work from per-draw overhead (default: the Deck '
                                 'panel size, as the game is played)')
    run_parser.add_argument('--gpu-passprof-after', type=int, default=0, metavar='SECONDS',
                            help='open a GPU timestamp window over the render passes this many seconds into the run '
                                 '(diagnostic run; the game reports the window by pass kind)')
    run_parser.add_argument('--stick', action='append', default=[], metavar='SEQ,LX,LY,HOLD',
                            help='hold the left stick (int16 units) for HOLD frames, run after the load and before '
                                 'the sample; repeatable, run in order. TOTK moves Link with the stick only, so a '
                                 'scene that explores (and redraws the map) needs these. Start SEQ at 4; the harness '
                                 'adds one to leave room for the load confirmation in the FIFO log.')
    run_parser.add_argument('--env', action='append', default=[], metavar='KEY=VALUE',
                            help='extra environment variable for the game, repeatable, for an A/B arm of one '
                                 'development switch (e.g. TOTK_VK_NO_LOCAL_BARRIER=1). Names already set by the '
                                 'harness itself are refused: an arm must not move the baseline under the measurement. '
                                 'Every accepted variable is recorded in the case\'s session.json.')
    commands.add_parser('summarize', parents=[both], help='recompute one completed case')
    args = top.parse_args()
    if args.command == 'summarize':
        print(json.dumps(summarize(Path(args.dir).resolve()), indent=2))
    else:
        if args.min_scene_draws < 0:
            run_parser.error('--min-scene-draws must be nonnegative')
        if args.hud_settle_seconds < 0:
            run_parser.error('--hud-settle-seconds must be nonnegative')
        run(args)


if __name__ == '__main__':
    main()
