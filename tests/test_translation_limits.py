import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import auth
import server
from ui_translator import MAX_GLOBAL_OUTBOUND_REQUESTS, UITranslator


def test_rate_limiter_charges_work_units_and_caps_tracked_keys():
    limiter = auth.RateLimiter(
        max_requests=5,
        window_seconds=300,
        max_tracked_keys=16,
    )
    assert limiter.allow("client", cost=3)
    assert not limiter.allow("client", cost=3)
    for index in range(40):
        assert limiter.allow(f"client-{index}")
    assert len(limiter._hits) <= 16


def test_translation_outbound_budget_is_global(tmp_path):
    translator = UITranslator(cache_path=tmp_path / "translations.json")
    active = 0
    maximum = 0
    lock = threading.Lock()

    def fake_translate(text, _target):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return f"translated-{text}"

    translator._translate_one_unbounded = fake_translate
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(
            lambda index: translator.translate_many([f"text-{index}"], "en"),
            range(12),
        ))

    assert all(result[0].startswith("translated-") for result in results)
    assert maximum <= MAX_GLOBAL_OUTBOUND_REQUESTS


def test_public_translation_rejects_oversize_and_work_amplification(monkeypatch):
    monkeypatch.setattr(server, "auth_required", lambda: True)
    monkeypatch.setattr(
        server,
        "PUBLIC_TRANSLATE_WORK_LIMITER",
        auth.RateLimiter(max_requests=3, window_seconds=300),
    )
    monkeypatch.setattr(
        server.UI_TRANSLATOR,
        "translate_many",
        lambda texts, _target: list(texts),
    )
    client = TestClient(server.app)

    too_many = client.post(
        "/api/ui/translate",
        json={"target_language": "en", "texts": ["x"] * 121},
    )
    assert too_many.status_code == 422

    too_large = client.post(
        "/api/ui/translate",
        json={"target_language": "en", "texts": ["x" * 501] * 60},
    )
    assert too_large.status_code == 413

    too_expensive = client.post(
        "/api/ui/translate",
        json={"target_language": "en", "texts": ["a", "b", "c", "d"]},
    )
    assert too_expensive.status_code == 429
