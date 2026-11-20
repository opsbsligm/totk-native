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


def write_case(case, first, last, drop=(), frame_ms=lambda number: 16.0 + number % 3):
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
