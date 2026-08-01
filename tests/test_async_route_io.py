import asyncio
import threading

import server
from api_system_router import legacy_health


def test_slow_config_persistence_does_not_stall_health(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def slow_save(_language):
        entered.set()
        assert release.wait(timeout=2)
        return True

    monkeypatch.setattr(server.appconfig, "save_ui_language", slow_save)

    async def scenario():
        write_task = asyncio.create_task(
            server.api_ui_config_set(server.UILanguageBody(language="de"))
        )
        assert await asyncio.to_thread(entered.wait, 1)
        health = await asyncio.wait_for(legacy_health(), timeout=0.1)
        release.set()
        await write_task
        return health

    assert asyncio.run(scenario()) == {"status": "ok"}


def test_slow_taste_persistence_does_not_stall_health(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def slow_record(*_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=2)
        return True

    monkeypatch.setattr(server.state.taste_profile, "record_event", slow_record)

    async def scenario():
        write_task = asyncio.create_task(server.api_taste_event(server.TasteEventBody(
            action="open", source="test", media_type="movie", item_key="movie:1",
        )))
        assert await asyncio.to_thread(entered.wait, 1)
        health = await asyncio.wait_for(legacy_health(), timeout=0.1)
        release.set()
        await write_task
        return health

    assert asyncio.run(scenario()) == {"status": "ok"}
