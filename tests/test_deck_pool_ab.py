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
            session['gpu_passprof_at'] = 900
            (case / 'session.json').write_text(json.dumps(session))
            summary = harness.summarize(case)
            self.assertEqual(summary['gpu_passprof_at'], 900)
            self.assertIn('GPU pass profiling active: this run is a pass breakdown, not a frame-rate sample',
                          summary['limits'])
            self.assertIsNone(summary['gpu_pass_profile'])       # no log in this case: nothing invented

    def test_the_render_pass_breakdown_is_read_from_the_game_log(self):
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            write_case(case, 100, 200)
            session = json.loads((case / 'session.json').read_text())
            session['gpu_passprof_at'] = 900
            (case / 'session.json').write_text(json.dumps(session))
            log = case / 'data/ultratears/ultratears.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(
                '[totk-gfx] [vk] some unrelated line mentioning passes\n'
                '[totk-gfx] [vk] pass profile of present 900: 493 passes, 18.33 ms in passes, '
                '2.76 ms between them, 21.09 ms first to last\n'
                '[totk-gfx] [vk]     3.569 ms  pass  115  1280x720  6 colour (fmt 0x25) depth 0x34  '
                '3353 draws  fs 1606026991dc\n'
                '[totk-gfx] [vk]     0.316 ms  pass  411  640x360  8 colour (fmt 0x25) depth 0x32  '
                '2 draws  fs ffd00d5e6cb2\n')
            profile = harness.summarize(case)['gpu_pass_profile']
            self.assertEqual(profile['present'], 900)
            self.assertEqual((profile['passes'], profile['in_pass_ms'], profile['between_ms'], profile['span_ms']),
                             (493, 18.33, 2.76, 21.09))
            # 'index' is the pass's position in the frame, not a count of passes: the report is one row per pass.
            self.assertEqual(profile['top'][0], dict(ms=3.569, index=115, extent='1280x720',
                                                     draws=3353, shader='1606026991dc'))
            self.assertEqual(len(profile['top']), 2)

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
