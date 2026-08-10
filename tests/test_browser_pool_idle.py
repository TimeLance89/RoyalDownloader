from types import SimpleNamespace

import server  # noqa: F401 - registers the application service backend
from application_services import download_lifecycle


class _Pool:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


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
