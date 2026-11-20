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
           --gpu-passprof-at <present> takes the GPU time of every render pass of that one frame
       python3 tools/deck_pool_ab.py summarize --dir <case-dir>   # one completed case
"""
import argparse
from collections import Counter
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
REQUIRED_METRICS = ['@frame_ms', '@nvn_ms', '@sub_wall_ms', '@sub_cpu_ms',
                    '@queue_lock_ms', '@queue_api_ms', '@present_effective_ticks']


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

    def bind_game(self, pid):
        rows = self.output(['xdotool', 'search', '--pid', str(pid)]).split()
        assert len(rows) == 1, f'expected one window, found {rows}'
        self.window = rows[0]
        self.report['game_window'] = self.window
        self.call(['xprop', '-id', self.window, '-f', 'STEAM_GAME', '32c', '-set', 'STEAM_GAME', str(APPID)])
        self.call(['xdotool', 'windowsize', self.window, '1280', '800'])
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

    def send(self, sequence, key='J'):
        """One confirmed click through a private owner-only FIFO; the game maps it to its A button."""
        self.focus()
        row = self.state()
        assert row['exact_window'] and row['exact_app'], 'foreground lost before input'
        fd = os.open(self.case / 'input.fifo', os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            assert stat.S_ISFIFO(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077
            os.write(fd, f'{sequence}:{key}*3\n'.encode())
        finally:
            os.close(fd)

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
    summary = dict(source_commit=session['source_commit'], pool_mode=session['pool_mode'],
                   pool_mem=session.get('pool_mem', 'n/a'),
                   scope=session.get('scope', 'one scene; one window; foreground verified every sample'),
                   scene=session.get('scene', 'opening cave'),
                   verified_focus_samples=sampling['samples'],
                   sample_seconds=sampling['sample_end_time'] - sampling['sample_start_time'],
                   first_exclusive_frame=first, last_exclusive_frame=last, selected_frames=len(frames),
                   game_present_fps_from_mean_interval=1000 / statistics.mean(intervals),
                   frame_threshold_counts={str(cutoff): sum(value > cutoff for value in intervals)
                                           for cutoff in (16.7, 25, 33.4, 50, 100)},
                   metrics_ms=metrics,
                   present_ticks={key: dict(Counter(row[key] for row in frames.values() if key in row))
                                  for key in ('@present_guest_ticks', '@present_effective_ticks')},
                   gamescope_rate_properties=sampling.get('gamescope_rate_properties', []),
                   power_limits=sampling.get('power_limits', {}),
                   original_save_files=result['player_save_files'],
                   original_saves_unchanged=result['player_saves_unchanged'],
                   focus_restored=True, hardware_validated=False,
                   gpu_passprof_at=session.get('gpu_passprof_at'),
                   limits=(['GPU pass profiling active: this run is a pass breakdown, not a frame-rate sample']
                           if session.get('gpu_passprof_at') else []) +
                          ['single scene, short sample', 'game present cadence is not panel scanout',
                           'first and last partial frames excluded',
                           'instrumentation overhead not measured separately',
                           'queue timings are host submission intervals, not GPU execution'])
    (case / 'timing-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def run(args):
    case, release = Path(args.dir).resolve(), Path(args.release).resolve()
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
    passprof = getattr(args, 'gpu_passprof_at', 0)
    if passprof:
        # One frame gets a timestamp pair per render pass; the report waits for the GPU, so that run is a diagnostic.
        env['TOTK_GPU_PASSPROF'] = str(passprof)

    command = ['bwrap', '--ro-bind', '/', '/', '--proc', '/proc', '--dev-bind', '/dev', '/dev',
               '--bind', str(case), str(case), '--tmpfs', '/tmp',
               '--ro-bind', '/tmp/.X11-unix', '/tmp/.X11-unix', '--die-with-parent', str(release / 'run.sh')]
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    started = time.time()
    with (case / 'launch.log').open('xb') as log:
        child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (case / 'session.json').write_text(json.dumps(dict(
        pid=child.pid, started=started, source_commit=args.commit, pool_mode=args.pool_mode,
        pool_mem=pool_mem or 'cached (the default kind)',
        release=str(release), scene=args.scene, save_isolated=True, maximum_seconds=args.maximum_seconds,
        gpu_passprof_at=passprof or None,
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
        deck.bind_game(pid)
        deck.capture('00-title.png')
        deck.send(1)
        time.sleep(4)
        deck.capture('01-continue.png')
        deck.send(2)
        time.sleep(4)
        deck.capture('02-select-save.png')
        deck.send(3)
        time.sleep(args.load_seconds)
        deck.capture('03-world-before-sample.png')
        sampling.update(deck.device_state())
        sampling['thread_cpu_start'] = thread_cpu(pid)
        timing = case / 'frame-timing.tsv'
        assert timing.is_file() and timing.stat().st_size < MAX_TSV_BYTES, 'no frame timing being written'
        sampling['timing_start_frame'] = max(int(line.split('\t', 1)[0])
                                             for line in timing.read_text().splitlines()
                                             if line.split('\t', 1)[0].isdigit())
        sampling['sample_start_time'] = time.time()
        with (case / 'foreground-samples.jsonl').open('x') as stream:
            for _ in range(args.sample_seconds):
                if child.poll() is not None:
                    raise RuntimeError('the game exited during the sample')
                row = deck.device_sample()
                stream.write(json.dumps(row) + '\n')
                stream.flush()
                sampling['samples'] += 1
                if not row['exact_window'] or not row['exact_app']:
                    raise RuntimeError('foreground lost; partial samples retained')
                if (case / 'launch.log').stat().st_size > MAX_LOG_BYTES:
                    raise RuntimeError('the launch log passed its budget')
                time.sleep(1)
        sampling['sample_end_time'] = time.time()
        assert timing.stat().st_size < MAX_TSV_BYTES, 'the timing file passed its budget'
        sampling['timing_end_frame'] = max(int(line.split('\t', 1)[0])
                                          for line in timing.read_text().splitlines()
                                          if line.split('\t', 1)[0].isdigit())
        sampling['valid_foreground_sample'] = True
        sampling['thread_cpu_end'] = thread_cpu(pid)
        deck.capture('04-world-after-sample.png')
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
    run_parser.add_argument('--scene', default='opening cave')
    run_parser.add_argument('--warmup-seconds', type=int, default=30)
    run_parser.add_argument('--load-seconds', type=int, default=30)
    run_parser.add_argument('--sample-seconds', type=int, default=50)
    run_parser.add_argument('--maximum-seconds', type=int, default=240)
    run_parser.add_argument('--gpu-passprof-at', type=int, default=0,
                            help='present number whose render passes get GPU timestamps (diagnostic run)')
    commands.add_parser('summarize', parents=[both], help='recompute one completed case')
    args = top.parse_args()
    if args.command == 'summarize':
        print(json.dumps(summarize(Path(args.dir).resolve()), indent=2))
    else:
        run(args)


if __name__ == '__main__':
    main()
