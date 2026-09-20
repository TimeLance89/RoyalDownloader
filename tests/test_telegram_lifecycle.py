import threading
import time

import pytest

from integrations.telegram_bot import TelegramBot


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_telegram_blocking_poll_stops_then_restarts_without_a_second_worker():
    config = {"enabled": True, "bot_token": "token"}
    bot = TelegramBot(lambda: config, lambda *_args: None)
    entered = threading.Event()
    release = threading.Event()

    def blocking_request(*_args, **_kwargs):
        entered.set()
        release.wait(0.5)
        return {"ok": True, "result": []}

    bot._request = blocking_request
    bot.start()
    assert entered.wait(0.5)
    assert bot.stop_and_wait(0.01) is False
    with pytest.raises(RuntimeError, match="beendet sich noch"):
        bot.start()

    release.set()
    assert _wait_until(lambda: not bot.is_alive())

    entered.clear()
    release.clear()
    bot.start()
    assert entered.wait(0.5)
    release.set()
    assert bot.stop_and_wait(0.5) is True
