"""Bounded Telegram ingress: no unbounded threads or silent update loss."""

from __future__ import annotations

import threading
import time

from integrations.telegram_bot import TelegramBot


def _message(n):
    return {
        "update_id": n,
        "message": {
            "chat": {"id": 11}, "text": f"message-{n}",
            "from": {"username": "sender"},
        },
    }


def _callback(n):
    return {
        "update_id": n,
        "callback_query": {
            "id": f"callback-{n}",
            "data": "action:test",
            "message": {"chat": {"id": 11}},
            "from": {"username": "sender"},
        },
    }


def test_ingress_backpressure_preserves_offset_until_handler_is_admitted():
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    handled = []

    def slow(chat_id, text, sender):
        handled.append(text)
        started.set()
        release.wait(2)
        finished.set()

    bot = TelegramBot(lambda: {"enabled": True, "bot_token": "fake"}, slow)
    bot._handler_slots = threading.BoundedSemaphore(1)

    assert bot._dispatch_update(_message(17)) is True
    assert started.wait(1)
    assert bot._offset == 18
    assert bot._dispatch_update(_message(18)) is False
    assert bot._offset == 18
    assert handled == ["message-17"]

    release.set()
    assert finished.wait(1)
    deadline = time.monotonic() + 1
    while bot._handler_slots._value != 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert bot._dispatch_update(_message(18)) is True
    assert bot._offset == 19


def test_telegram_callback_backpressure_is_equally_bounded():
    entered = threading.Event()
    release = threading.Event()
    delivered = []

    def callback(chat, callback_id, data, sender):
        delivered.append(callback_id)
        entered.set()
        release.wait(1)

    bot = TelegramBot(
        lambda: {"enabled": True, "bot_token": "fake"},
        lambda *_args: None,
        callback_cb=callback,
    )
    bot._handler_slots = threading.BoundedSemaphore(1)
    assert bot._dispatch_update(_callback(31)) is True
    assert entered.wait(1)
    assert bot._dispatch_update(_callback(32)) is False
    assert bot._offset == 32
    release.set()
    assert delivered == ["callback-31"]


def test_callback_exceptions_release_admission_capacity():
    completed = threading.Event()
    errors = []

    def broken(*_args):
        completed.set()
        raise ValueError("expected synthetic error")

    bot = TelegramBot(
        lambda: {"enabled": True, "bot_token": "fake"},
        broken,
        lambda message, _level="": errors.append(message),
    )
    bot._handler_slots = threading.BoundedSemaphore(1)
    assert bot._dispatch_update(_message(40))
    assert completed.wait(1)

    deadline = time.monotonic() + 1
    while bot._handler_slots._value != 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert bot._dispatch_update(_message(41))
    assert bot._offset == 42
    assert any("synthetic error" in err for err in errors)


def test_invalid_message_does_not_allocate_threads_but_acknowledges_update():
    bot = TelegramBot(
        lambda: {"enabled": True, "bot_token": "fake"},
        lambda *_args: None,
    )
    assert bot._dispatch_update({"update_id": 5, "message": {"text": ""}}) is True
    assert bot._offset == 6
