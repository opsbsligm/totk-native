"""Require real analysis of every public runtime compilation unit."""
import json
from pathlib import Path
import re
import subprocess
import sys


def coverage(log, expected):
    clean = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', log)
    success = re.findall(r'Successfully analyzed[^\n]*\n[^\n]*clangsa:\s*(\d+)', clean)
    failures = re.findall(r'Failed to analyze[^\n]*\n[^\n]*clangsa:\s*(\d+)', clean)
    totals = re.findall(r'Total analyzed compilation commands:\s*(\d+)', clean)
    passed = len(success) == 1 and len(totals) == 1 and int(success[0]) == expected and int(totals[0]) == expected
    passed = passed and all(int(count) == 0 for count in failures)
    passed = passed and 'Analysis of at least one translation unit failed' not in clean
    return dict(expected_units=expected, successful_units=[int(n) for n in success],
                failed_units=[int(n) for n in failures], total_units=[int(n) for n in totals], complete=passed)


def main():
    output = Path('out/cppscan')
    rows = json.loads((output / 'compile_commands.json').read_text())
    if not rows:
        raise SystemExit('Empty compilation database')
    report = Path('gl-sast-report.json')
    report.unlink(missing_ok=True)
    with (output / 'analysis.log').open('w') as log:
        process = subprocess.Popen(['/analyzer', 'run'], stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace')
        for line in process.stdout:
            log.write(line)
            print(line, end='', flush=True)
        status = process.wait()
    result = coverage((output / 'analysis.log').read_text(), len(rows))
    result['analyzer_exit'] = status
    result['report_present'] = report.is_file()
    result['complete'] = result['complete'] and status == 0 and report.is_file()
    if report.is_file():
        result['report_scan_status'] = json.loads(report.read_text()).get('scan', {}).get('status')
        result['complete'] = result['complete'] and result['report_scan_status'] == 'success'
    (output / 'coverage-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    if not result['complete']:
        raise SystemExit('C/C++ analysis did not cover every compiled runtime unit')


if __name__ == '__main__':
    main()
