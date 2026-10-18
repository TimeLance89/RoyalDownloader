"""Optional Linux process/cgroup counters; absent counters stay absent."""

from pathlib import Path


def _integer(path):
    try:
        value = path.read_text().strip()
        return int(value) if value != "max" else "unlimited"
    except (OSError, ValueError):
        return None


def _pairs(path):
    try:
        return {key: int(value) for key, value in
                (line.split() for line in path.read_text().splitlines())}
    except (OSError, ValueError):
        return None


def container_memory(root=Path("/sys/fs/cgroup")):
    memory = {}
    for name in ("current", "max", "peak"):
        value = _integer(root / f"memory.{name}")
        if value is not None:
            memory[name] = value
    events = _pairs(root / "memory.events")
    if events is not None:
        memory["events"] = events
    if memory:
        return {"cgroup_version": 2, **memory}
    legacy = root / "memory"
    for name, filename in (("current", "memory.usage_in_bytes"),
                           ("max", "memory.limit_in_bytes"),
                           ("peak", "memory.max_usage_in_bytes"),
                           ("allocation_failures", "memory.failcnt")):
        value = _integer(legacy / filename)
        if value is not None:
            memory[name] = value
    oom = _pairs(legacy / "memory.oom_control")
    if oom is not None:
        memory["oom_control"] = oom
    return {"cgroup_version": 1, **memory} if memory else {}


def process_resources(root=Path("/proc/self")):
    result = {}
    try:
        for line in (root / "status").read_text().splitlines():
            key, _, raw = line.partition(":")
            if key in {"VmRSS", "VmHWM"}:
                parts = raw.split()
                if len(parts) == 2 and parts[1] == "kB":
                    result["rss_bytes" if key == "VmRSS" else "peak_rss_bytes"] = int(parts[0]) * 1024
            elif key == "Threads":
                result["native_thread_count"] = int(raw.strip())
    except (OSError, ValueError):
        pass
    try:
        result["open_fd_count"] = sum(1 for _ in (root / "fd").iterdir())
    except OSError:
        pass
    return result
