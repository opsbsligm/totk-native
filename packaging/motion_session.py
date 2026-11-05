"""Own a reversible Deck IMU-mode lease for one native game session.

Steam can set IMU_MODE=0 for its sensorless virtual gamepad. The native reader
remains read-only; this parent changes only raw sensor bits, never buttons or
lizard mode, and restores the prior mode if it still owns that exact value.
"""
import fcntl
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

SETTING_IMU_MODE = 0x30
RAW_SENSORS = 0x18
REPORT_BYTES = 65
HIDIOCSFEATURE = 0xC0004806 | (REPORT_BYTES << 16)
HIDIOCGFEATURE = 0xC0004807 | (REPORT_BYTES << 16)


def setting(fd, value=None):
    if value is not None:
        report = bytearray(REPORT_BYTES)
        report[:6] = bytes([0, 0x87, 3, SETTING_IMU_MODE, value & 255, value >> 8])
        fcntl.ioctl(fd, HIDIOCSFEATURE, report)
        return value
    # Steam may interleave its own feature request on this HID interface. Retry
    # only the bounded read query; never infer a mode from an unrelated reply.
    for _ in range(5):
        report = bytearray(REPORT_BYTES)
        report[:6] = bytes([0, 0x89, 3, SETTING_IMU_MODE, 0, 0])
        fcntl.ioctl(fd, HIDIOCSFEATURE, report)
        time.sleep(0.02)
        reply = bytearray(REPORT_BYTES)
        fcntl.ioctl(fd, HIDIOCGFEATURE, reply)
        if reply[:4] == bytes([0, 0x89, 3, SETTING_IMU_MODE]):
            return reply[4] | reply[5] << 8
    raise OSError('Unexpected IMU settings responses; refusing to change controller')


def open_imu():
    for device in Path('/sys/class/hidraw').glob('hidraw[0-9]*'):
        fd = None
        try:
            if 'HID_ID=0003:000028DE:00001205' not in (device / 'device/uevent').read_text().splitlines():
                continue
            fd = os.open('/dev/' + device.name, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
            deadline = time.monotonic() + 0.12
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.04)[0]:
                    report = os.read(fd, 64)
                    if len(report) == 64 and report[:4] == bytes([1, 0, 9, 64]):
                        return fd
        except OSError:
            pass
        if fd is not None:
            os.close(fd)
    return None


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: totk-motion-session.py /absolute/path/run.sh')
    target = Path(sys.argv[1]).resolve(strict=True)
    expected = Path(__file__).resolve().parent / 'game.sh'
    if target != expected:
        raise SystemExit('Unexpected native launch target')
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'ultratears'
    data.mkdir(parents=True, exist_ok=True)
    session_lock = (data / 'motion-session.lock').open('a')
    fcntl.flock(session_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    logfile = (data / 'motion-session.log').open('w')

    def log(message):
        print(message, file=sys.stderr, flush=True)
        print(message, file=logfile, flush=True)

    child = None
    pending = 0
    fd = None
    original = applied = None

    def forward(sig, _frame):
        nonlocal pending
        pending = sig
        if child is not None and child.poll() is None:
            child.send_signal(sig)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    try:
        if os.environ.get('TOTK_GYRO', '1') != '0' and os.environ.get('TOTK_STEAMDECK_GYRO') != '0':
            fd = open_imu()
            if fd is not None:
                try:
                    original = setting(fd)
                    applied = original | RAW_SENSORS
                    if applied != original:
                        setting(fd, applied)
                        if setting(fd) != applied:
                            raise OSError('IMU mode readback mismatch')
                    log(f'[deck-motion-session] IMU mode {original:#x} -> {applied:#x}; sensor bits only')
                except OSError as error:
                    log(f'[deck-motion-session] IMU lease unavailable: {error}')
        if pending:
            return 128 + pending
        session_fd = os.environ.get('NATIVE_SESSION_FD')
        inherited = (int(session_fd),) if session_fd is not None else ()
        child = subprocess.Popen([str(target)], pass_fds=inherited)
        if pending:
            child.send_signal(pending)
        attempts = 0
        lease_checks = 0
        while child.poll() is None:
            time.sleep(0.5)
            if fd is not None and applied is not None and not pending and attempts < 3 and lease_checks < 20:
                try:
                    # Steam may finish applying the app profile after the ELF starts.
                    # Only reapply an observed all-off mode; never overwrite another mode.
                    lease_checks += 1
                    current = setting(fd)
                    if current == 0 and applied != 0:
                        setting(fd, applied)
                        attempts += 1
                        if setting(fd) != applied:
                            raise OSError('Reapplied IMU mode readback mismatch')
                        log('[deck-motion-session] Steam disabled IMU; reapplied sensor lease')
                except OSError as error:
                    log(f'[deck-motion-session] IMU lease check deferred: {error}')
        return child.returncode if child.returncode >= 0 else 128 - child.returncode
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if fd is not None:
            try:
                if original is not None and applied is not None and setting(fd) == applied:
                    setting(fd, original)
                    if setting(fd) != original:
                        raise OSError('Restored IMU mode readback mismatch')
                    log(f'[deck-motion-session] restored IMU mode {original:#x}')
            except OSError as error:
                log(f'[deck-motion-session] IMU restore unverified: {error}')
            os.close(fd)
        logfile.close()
        session_lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
