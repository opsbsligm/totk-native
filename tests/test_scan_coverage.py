"""A successful scanner process must not hide compilation failures."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('scan_coverage', Path(__file__).resolve().parents[1] / '.gitlab/run_cpp_scan.py')
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


class CoverageTests(unittest.TestCase):
    def test_partial_success_is_rejected(self):
        log = 'Successfully analyzed\nclangsa: 1\nFailed to analyze\nclangsa: 62\nTotal analyzed compilation commands: 63'
        self.assertFalse(scan.coverage(log, 63)['complete'])

    def test_missing_or_smaller_summary_is_rejected(self):
        self.assertFalse(scan.coverage('', 63)['complete'])
        self.assertFalse(scan.coverage('Successfully analyzed\nclangsa: 1\nTotal analyzed compilation commands: 1', 63)['complete'])

    def test_complete_summary_with_ansi_logging(self):
        log = '\x1b[32m[INFO] Successfully analyzed\x1b[0m\n[INFO] clangsa: 63\n[INFO] Total analyzed compilation commands: 63'
        self.assertTrue(scan.coverage(log, 63)['complete'])
        self.assertFalse(scan.coverage(log + '\nAnalysis of at least one translation unit failed', 63)['complete'])
