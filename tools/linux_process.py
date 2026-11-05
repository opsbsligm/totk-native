"""Start build tools at reduced priority and within the permitted CPU affinity."""
import os


def limited_command(cmd, mask):
    if mask <= 0:
        raise ValueError('CPU mask must not be empty')
    allowed = sorted(os.sched_getaffinity(0))
    cpus = [cpu for cpu in allowed if mask & (1 << cpu)]
    if not cpus:
        cpus = allowed[:bin(mask).count('1')]
    if not cpus:
        raise ValueError('No permitted build CPU')
    return ['nice', '-n', '10', 'taskset', '--cpu-list', ','.join(map(str, cpus)), *map(str, cmd)]
