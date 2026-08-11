import stat
from types import SimpleNamespace

import server  # noqa: F401 - registers the application service backend
from application_services import download_lifecycle, source_resolution


class _Pool:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_existing_completed_media_is_made_readable_for_jellyfin(tmp_path):
    media = tmp_path / "The.Return.2006.mp4"
    media.write_bytes(b"movie")
    media.chmod(stat.S_IRUSR | stat.S_IWUSR)

    download_lifecycle._ensure_jellyfin_media_readable(media)

    mode = media.stat().st_mode
    assert mode & stat.S_IRGRP
    assert mode & stat.S_IROTH


def test_idle_provider_cooldown_closes_browser_pools(monkeypatch):
    voe_pool = _Pool()
    embed_pool = _Pool()
    fake_state = SimpleNamespace(
        dl_queue=SimpleNamespace(active_count=lambda: 0, pending_count=lambda: 0),
        provider_waiting_jobs={"series:test": {}},
        voe_pool=voe_pool,
        embed_pool=embed_pool,
    )
    monkeypatch.setattr(download_lifecycle, "state", fake_state)
    monkeypatch.setattr(download_lifecycle, "_reconcile_idle_queue_state_locked", lambda: 0)
    monkeypatch.setattr(download_lifecycle, "log", lambda *_args: None)

    download_lifecycle._on_queue_done_locked()

    assert voe_pool.closed is True
    assert embed_pool.closed is True
    assert fake_state.voe_pool is None
    assert fake_state.embed_pool is None


def test_all_hoster_fallbacks_share_one_browser_pool(monkeypatch):
    primary_pool = _Pool()
    duplicate_pool = _Pool()
    fake_state = SimpleNamespace(
        voe_pool=primary_pool,
        embed_pool=duplicate_pool,
    )
    monkeypatch.setattr(source_resolution, "state", fake_state)
    monkeypatch.setattr(source_resolution, "log", lambda *_args: None)

    pool = source_resolution._shared_browser_pool("test")

    assert pool is primary_pool
    assert fake_state.voe_pool is primary_pool
    assert fake_state.embed_pool is None
    assert duplicate_pool.closed is True
