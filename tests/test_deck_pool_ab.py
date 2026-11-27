"""The Deck A/B harness must reject incomplete samples and report the submission side honestly."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deck_pool_ab', ROOT / 'tools/deck_pool_ab.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def write_case(case, first, last, drop=(), frame_ms=lambda number: 16.0 + number % 3, t_s=None):
    """A completed case with a synthetic frame TSV: frames (first, last) except those dropped."""
    rows = []
    for number in range(first, last + 1):
        if number in drop:
            continue
        interval = frame_ms(number)
        for key, value in [('@frame_ms', interval), ('@nvn_ms', interval / 2), ('@sub_wall_ms', interval / 2),
                           ('@sub_cpu_ms', interval / 4), ('@queue_lock_ms', 0.0), ('@queue_api_ms', 0.2),
                           ('@work_ms', interval), ('@proc_cpu_ms', 50.0), ('@present_effective_ticks', 1.0),
                           ('@present_guest_ticks', 2.0)]:
            rows.append(f'{number}\t{key}\t{value}')
        if t_s is not None:
            rows.append(f'{number}\t@t_s\t{t_s(number):.3f}')
    (case / 'frame-timing.tsv').write_text('\n'.join(rows) + '\n')
    (case / 'session.json').write_text(json.dumps(dict(source_commit='a' * 40, pool_mode='copy',
                                                      scene='opening cave')))
    (case / 'sampling-report.json').write_text(json.dumps(
        dict(samples=50, valid_foreground_sample=True, focus_restored=True,
             timing_start_frame=first, timing_end_frame=last, sample_start_time=100.0, sample_end_time=150.0,
             power_limits={'/sys/class/hwmon/hwmon6/power1_cap': '15000000'}, gamescope_rate_properties=[])))
    (case / 'result.json').write_text(json.dumps(dict(player_saves_unchanged=True, player_save_files=77)))


class HarnessTest(unittest.TestCase):
    def test_percentiles_cover_only_the_sample_window(self):
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200)
            summary = harness.summarize(case)
            self.assertEqual(summary['selected_frames'], 99)                 # (first, last) exclusive
            self.assertEqual(summary['first_exclusive_frame'], 100)
            self.assertAlmostEqual(summary['game_present_fps_from_mean_interval'],
                                   1000 / (16.0 + sum(n % 3 for n in range(101, 200)) / 99), places=6)
            for key in harness.REQUIRED_METRICS:
                self.assertIn(key, summary['metrics_ms'], key)
            self.assertEqual(summary['metrics_ms']['@queue_api_ms']['p95'], 0.2)
            self.assertFalse(summary['hardware_validated'])
            self.assertIn('queue timings are host submission intervals, not GPU execution',
                          summary['limits'])
            self.assertTrue((case / 'timing-summary.json').is_file())

    def test_a_gpu_pass_profiled_run_is_flagged_as_a_diagnostic(self):
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200)
            session = json.loads((case / 'session.json').read_text())
            session['gpu_passprof_after_s'] = 40
            (case / 'session.json').write_text(json.dumps(session))
            summary = harness.summarize(case)
            self.assertEqual(summary['gpu_passprof_after_s'], 40)
            self.assertIn('GPU pass profiling active: this run is a pass breakdown, not a frame-rate sample',
                          summary['limits'])
            self.assertIsNone(summary['gpu_pass_profile'])       # no log in this case: nothing invented

    def test_the_render_pass_breakdown_is_read_from_the_game_log(self):
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200)
            session = json.loads((case / 'session.json').read_text())
            session['gpu_passprof_after_s'] = 40
            (case / 'session.json').write_text(json.dumps(session))
            log = case / 'data/ultratears/ultratears.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(
                '[totk-gfx] [vk] some unrelated line mentioning passes\n'
                '[totk-gfx] [vk] pass profile of presents 1180..1183: 1972 passes over 4 presents, '
                '73.32 ms in passes, 11.04 ms between them, 84.36 ms first to last '
                '(18.33 ms in passes per present)\n'
                '[totk-gfx] [vk]     3.569 ms x4  1280x720/6c/fmt25/d34/1606026991dc  3353 draws avg '
                'per present 0.89 ms  peak 3.569 ms\n'
                '[totk-gfx] [vk]     0.316 ms x8  640x360/8c/fmt25/d32/ffd00d5e6cb2  2 draws avg '
                'per present 0.08 ms  peak 0.101 ms\n')
            profile = harness.summarize(case)['gpu_pass_profile']
            self.assertEqual(profile['presents'], [1180, 1183])
            self.assertEqual(profile['profiled_presents'], 4)
            self.assertEqual((profile['passes'], profile['in_pass_ms'], profile['between_ms'], profile['span_ms'],
                              profile['in_pass_ms_per_present']), (1972, 73.32, 11.04, 84.36, 18.33))
            # One row per pass *kind*: count is how many passes of that shape the window held.
            self.assertEqual(profile['kinds'][0], dict(ms=3.569, count=4,
                                                       targets='1280x720/6c/fmt25/d34/1606026991dc',
                                                       extent='1280x720', shader='1606026991dc', draws_avg=3353,
                                                       ms_per_present=0.89, peak_ms=3.569))
            self.assertEqual(len(profile['kinds']), 2)
            self.assertEqual(profile['timing_method'], 'legacy_recording_order')
            log.write_text(log.read_text().replace('ms in passes per present)\n', 'ms in passes per present) [timestamp union]\n'))
            self.assertEqual(harness.summarize(case)['gpu_pass_profile']['timing_method'], 'timestamp_union')

    def test_a_long_frame_is_attributed_to_the_thread_busy_in_its_second(self):
        """The clock tie is the load-bearing part: the TSV counts from process start, the samples from wall clock."""
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            # Frame n starts 0.5 + n/30 s after process start, so every sample taken on second boundaries ties the
            # two clocks at 105 s: frame 150 starts at 110.5 s, mid-second inside the sample reported at 111.
            write_case(case, 100, 200, frame_ms=lambda n: 90.0 if n == 150 else 30.0, t_s=lambda n: 0.5 + n / 30)
            samples = []
            for second in range(109, 113):                     # wall clock; (second - 105.5) * 30 is the last frame
                row = dict(time=float(second), last_frame=int((second - 105.5) * 30),
                           thread_cpu_ms={'totk-translate': 900.0, 'totk-record-1': 900.0})
                if second == 111:                              # the second that holds frame 150
                    row['thread_cpu_ms']['totk-record-1'] = 1400.0
                samples.append(row)
            report = json.loads((case / 'sampling-report.json').read_text())
            report['device_samples'] = samples
            (case / 'sampling-report.json').write_text(json.dumps(report))
            summary = harness.summarize(case)
            found = summary['long_frame_attribution']
            self.assertEqual(found['long_frames'], 1)
            self.assertEqual(found['attributed'], 1)
            self.assertAlmostEqual(found['clock_offset_s'], 105.0, places=3)   # every sample agrees on this tie
            entry = found['frames'][0]
            self.assertEqual(entry['frame'], 150)
            self.assertEqual(entry['above_the_window_median'][0]['thread'], 'totk-record-1')
            self.assertGreater(entry['above_the_window_median'][0]['ms'], 400.0)
            self.assertIn('candidate thread, not a cause', ' '.join(summary['limits']))

    def test_attribution_reports_what_it_could_not_place(self):
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200, frame_ms=lambda n: 90.0 if n == 150 else 30.0)   # no @t_s: no clock tie
            summary = harness.summarize(case)
            found = summary['long_frame_attribution']
            self.assertEqual(found['long_frames'], 1)           # the long frame is still reported
            self.assertEqual(found['attributed'], 0)            # only the clock tie is missing
            self.assertIn('per-second samples', found['note'])
            self.assertNotIn('long-frame thread attribution', ' '.join(summary['limits']))

    def test_write_watch_scans_are_booked_per_code_location(self):
        """The scan rows say who asked the kernel; without them the report must say "not measured"."""
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200)
            self.assertIsNone(harness.summarize(case)['write_watch_scan'])   # a build without the attribution
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200)
            rows = (case / 'frame-timing.tsv').read_text().rstrip('\n').split('\n')
            for n in range(101, 200):
                rows += [f'{n}\t@scan_tex_stale\t1.2', f'{n}\t@scan_tex_stale_calls\t400',
                         f'{n}\t@scan_gpu_write\t0.4', f'{n}\t@scan_gpu_write_calls\t10']
            (case / 'frame-timing.tsv').write_text('\n'.join(rows) + '\n')
            scan = harness.summarize(case)['write_watch_scan']
            self.assertEqual(scan['tex_stale']['calls_per_frame'], 400)
            self.assertEqual(scan['tex_stale']['ms_per_frame'], 1.2)
            self.assertEqual(scan['tex_stale']['frames_with_calls'], 99)
            self.assertEqual(scan['tex_stale']['frames_over_1ms'], 99)
            self.assertAlmostEqual(scan['total']['ms_per_frame'], 1.6, places=3)
            self.assertGreater(scan['total']['share_of_frame_ms'], 8.0)   # 1.6 ms of a ~17 ms frame

    def test_window_sizes_offered_are_the_panel_shape_only(self):
        """The window is a measured variable, so a wrong size has to fail before the game starts, not skew the sample."""
        self.assertEqual(harness.parse_size('1280x800'), (1280, 800))
        self.assertEqual(harness.parse_size(' 960x600 '), (960, 600))
        for bad in ('1280x720',      # the panel's width at a different height: a different amount of world
                    '960x540',       # 16:9 on a 16:10 panel
                    '600x400',       # right shape, below the smallest size offered
                    '1440x900',      # larger than the panel
                    'big'):
            with self.assertRaises(SystemExit, msg=bad):
                harness.parse_size(bad)

    def test_a_reduced_window_size_is_stated_as_the_upscale_path(self):
        """A frame time measured at 640x400 is not comparable with one at the panel size, and it is not a smaller
        scene either (the scene keeps its fixed size), so the summary has to say which one it was."""
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200)
            panel = harness.summarize(case)
            self.assertEqual(panel['window_size'], [1280, 800])
            self.assertNotIn('below the panel', ' '.join(panel['limits']))

            session = json.loads((case / 'session.json').read_text())
            session['window_size'] = [640, 400]
            (case / 'session.json').write_text(json.dumps(session))
            reduced = harness.summarize(case)
            self.assertEqual(reduced['window_size'], [640, 400])
            stated = ' '.join(reduced['limits'])
            self.assertIn('presenting window 640x400', stated)
            self.assertIn('the scene keeps its fixed size', stated)

    def test_an_arm_may_only_move_one_switch_of_its_own(self):
        """An --env arm that would move the harness's own baseline fails before the game starts."""
        baseline = {'TOTK_POOL_COPY': '1', 'XDG_DATA_HOME': '/case/data', 'DM_NVN_TSV': '/case/f.tsv'}
        self.assertEqual(harness.arm_env(['TOTK_VK_NO_LOCAL_BARRIER=1'], baseline),
                         {'TOTK_VK_NO_LOCAL_BARRIER': '1'})
        self.assertEqual(harness.arm_env([], baseline), {})
        for bad in ('TOTK_POOL_COPY=1',     # the arm's pool mode, already set by the harness
                    'TOTK_POOL_IMPORT=1',   # the runtime prefers import: this flips a copy arm
                    'TOTK_POOL_MEM=device', # a second variable of the same arm
                    'DM_NVN_TSV=/tmp/x',    # the measurement output itself
                    'LD_PRELOAD=/tmp/x.so'):
            with self.assertRaises(SystemExit, msg=bad):
                harness.arm_env([bad], baseline)
        for bad in ('BARRIER', '1BAD=1', 'A-B=1', '=1'):
            with self.assertRaises(SystemExit, msg=bad):
                harness.arm_env([bad], baseline)

    def test_last_frame_reads_the_end_of_a_growing_tsv(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'frame-timing.tsv'
            path.write_text(''.join(f'{n}\t@frame_ms\t30.0\n' for n in range(1, 5001)))
            self.assertEqual(harness.last_frame(path), 5000)
            path.write_text('# kind: header only\n')
            self.assertEqual(harness.last_frame(path), 0)

    def test_a_frame_missing_mid_sample_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200, drop={150})
            with self.assertRaises(AssertionError):
                harness.summarize(case)

    def test_an_unverified_foreground_sample_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200)
            report = json.loads((case / 'sampling-report.json').read_text())
            report['valid_foreground_sample'] = False
            (case / 'sampling-report.json').write_text(json.dumps(report))
            with self.assertRaises(AssertionError):
                harness.summarize(case)

    def test_a_changed_player_save_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200)
            result = json.loads((case / 'result.json').read_text())
            result['player_saves_unchanged'] = False
            (case / 'result.json').write_text(json.dumps(result))
            with self.assertRaises(AssertionError):
                harness.summarize(case)

    def test_a_duplicate_metric_row_for_one_frame_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 130)
            tsv = case / 'frame-timing.tsv'
            tsv.write_text(tsv.read_text() + '110\t@frame_ms\t99.0\n')
            with self.assertRaises(AssertionError):
                harness.summarize(case)

    def test_inventory_reads_content_and_refuses_a_symlink(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'a.bin').write_bytes(b'one')
            self.assertEqual(set(harness.inventory(root)), {str(root / 'a.bin')})
            self.assertEqual(harness.rel_inventory(root)['a.bin']['size'], 3)
            try:
                (root / 'link').symlink_to(root / 'a.bin')
            except OSError:                          # a filesystem without symlink support
                return
            with self.assertRaises(AssertionError):
                harness.inventory(root)


if __name__ == '__main__':
    unittest.main()
