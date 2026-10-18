from core.runtime_resources import container_memory, process_resources


def test_v2_memory_and_oom_counts_are_reported_without_inventing_missing_peak(tmp_path):
    (tmp_path / "memory.current").write_text("1024\n")
    (tmp_path / "memory.max").write_text("max\n")
    (tmp_path / "memory.events").write_text("oom 2\noom_kill 1\n")
    assert container_memory(tmp_path) == {
        "cgroup_version": 2, "current": 1024, "max": "unlimited", "events": {"oom": 2, "oom_kill": 1},
    }


def test_v1_memory_failure_count_is_distinct_from_oom_kills(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    (root / "memory.usage_in_bytes").write_text("1024\n")
    (root / "memory.limit_in_bytes").write_text("8192\n")
    (root / "memory.max_usage_in_bytes").write_text("4096\n")
    (root / "memory.failcnt").write_text("7\n")
    (root / "memory.oom_control").write_text("under_oom 0\noom_kill 2\n")
    assert container_memory(tmp_path) == {
        "cgroup_version": 1, "current": 1024, "max": 8192, "peak": 4096,
        "allocation_failures": 7, "oom_control": {"under_oom": 0, "oom_kill": 2},
    }


def test_process_counters_include_native_threads_and_fd_usage(tmp_path):
    (tmp_path / "status").write_text("Name:\tfixture\nVmRSS:\t123 kB\nVmHWM:\t456 kB\nThreads:\t7\n")
    (tmp_path / "fd").mkdir()
    (tmp_path / "fd" / "0").touch()
    assert process_resources(tmp_path) == {
        "rss_bytes": 123 * 1024, "peak_rss_bytes": 456 * 1024,
        "native_thread_count": 7, "open_fd_count": 1,
    }


def test_unavailable_or_malformed_counters_are_not_reported_as_zero(tmp_path):
    assert container_memory(tmp_path) == {}
    assert process_resources(tmp_path) == {}
    (tmp_path / "memory.current").write_text("broken")
    (tmp_path / "memory.events").write_text("invalid line with extra data")
    assert container_memory(tmp_path) == {}
