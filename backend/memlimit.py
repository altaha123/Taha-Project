"""
How much memory this instance is allowed to hold.

The figure was written down as 512 in three places, which was right for one
Render plan and wrong the day the plan changed: the scan went on stopping
itself early for a ceiling that was no longer there, and /health/memory went
on reporting it. The container knows its own limit, so it is asked.

Order: MEM_LIMIT_MB if someone set it on purpose, then the container's own
limit (cgroup v2, then v1), then 512 as the old default.
"""
import os

_PATHS = ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes")
# A cgroup with no limit reports a number near 2**63. Anything above this is
# "no limit", not an instance size.
_UNLIMITED_MB = 1024 * 1024


def detect(default=512, paths=_PATHS, env=None):
    """(megabytes, where the figure came from)."""
    env = os.environ if env is None else env
    raw = str(env.get("MEM_LIMIT_MB", "") or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw), "MEM_LIMIT_MB"
    for p in paths:
        try:
            with open(p) as f:
                v = f.read().strip()
        except OSError:
            continue
        if v.isdigit():
            mb = int(v) // (1024 * 1024)
            if 0 < mb < _UNLIMITED_MB:
                return mb, "container limit"
    return default, "default"


LIMIT_MB, SOURCE = detect()
