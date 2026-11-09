"""Cross-user access, HLS/resource ownership and identity invalidation contracts."""
from contextlib import nullcontext
from threading import Lock
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_media_center_router import create_media_center_router
from api import jellyfin_playback
from core.auth import SessionStore, SESSION_COOKIE_NAME, SESSION_KIND_MOBILE

A, B, ITEM, SERIES = "1" * 32, "2" * 32, "3" * 32, "4" * 32
BASE = "/api/media-center"


@pytest.fixture
def household(monkeypatch, tmp_path):
    users = {
        "a": {"id": "a", "role": "member", "enabled": True, "jellyfin_user_id": A},
        "b": {"id": "b", "role": "member", "enabled": True, "jellyfin_user_id": B},
    }
    store = SessionStore()
    tokens = {name: store.create(user_id=name) for name in users}
    state = SimpleNamespace(jellyfin_cache_lock=Lock(), jellyfin_config_generation=7,
                            jellyfin_cfg={"url": "http://jf", "api_key": "fixture-secret", "user_id": B})
    def web(cookies, **_):
        token = cookies.get(SESSION_COOKIE_NAME, "")
        return token if store.validate(token, "web", touch=False) else ""
    def mobile(headers, **_):
        token = headers.get("authorization", "").removeprefix("Bearer ")
        return token if store.validate(token, SESSION_KIND_MOBILE, touch=False) else ""
    def current(headers, cookies):
        token = mobile(headers) or web(cookies)
        return users.get(store.user_id(token, touch=False)) if token else None
    backend = SimpleNamespace(state=state, SESSION_STORE=store, current_user=current,
                              authenticated_web_token=web, authenticated_mobile_token=mobile,
                              clean_movie_title=lambda text: text,
                              get_jellyfin_movie_identities=lambda: [{"id": ITEM, "title": "Demo", "tmdb_id": "1"}],
                              get_jellyfin_series=lambda: [])
    flags = {"disabled": False, "playback": True, "visible": True}
    data = {A: {"PlaybackPositionTicks": 45 * 60 * 10_000_000}, B: {"PlaybackPositionTicks": 20 * 60 * 10_000_000}}
    calls, saved, closed = [], [], []
    def read(_url, _key, path, params):
        calls.append((path, dict(params)))
        if path.startswith("/Users/"):
            return {"Id": path.rsplit("/", 1)[-1], "Policy": {"IsDisabled": flags["disabled"], "EnableMediaPlayback": flags["playback"]}}
        profile = params.get("UserId")
        assert profile in (A, B)
        item = {"Id": ITEM, "Type": "Episode", "Name": "Pilot", "SeriesName": "Demo", "SeriesId": SERIES,
                "ParentIndexNumber": 1, "IndexNumber": 1, "RunTimeTicks": 7200 * 10_000_000,
                "UserData": dict(data[profile]), "ImageTags": {"Primary": "fixture"}}
        if path == "/Items" and params.get("Ids") == SERIES:
            return {"Items": [{"Id": SERIES, "Type": "Series", "Name": "Demo"}]}
        return {"Items": [item] if flags["visible"] else []}
    def save(_url, _key, profile, item, body):
        saved.append((profile, item, dict(body)))
        data[profile].update(body)
        return dict(data[profile])
    monkeypatch.setattr("api.api_movie_playback_router._jellyfin_json", read)
    monkeypatch.setattr("api.api_movie_playback_router._save_jellyfin_data", save)
    monkeypatch.setattr("api.api_movie_playback_router.home_layout_file", lambda: tmp_path / "home.json")
    monkeypatch.setattr(jellyfin_playback, "negotiate", lambda *args: {
        "path": "/master.m3u8?api_key=fixture-secret", "mode": "hls", "duration_ticks": 7200 * 10_000_000,
        "headers": {}, "play_session_id": "play", "device_id": "device",
    })
    monkeypatch.setattr(jellyfin_playback.requests, "delete", lambda *_a, **_kw: nullcontext(SimpleNamespace(status_code=204)))
    def upstream(url, **kw):
        content = b"#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"key\"\nchild.m3u8\nsegment.ts\n" if ".m3u8" in url else b"video"
        return SimpleNamespace(status_code=200, headers={"Content-Type": "application/vnd.apple.mpegurl" if ".m3u8" in url else "video/mp2t"},
                               iter_content=lambda *_a, **_kw: iter([content]), close=lambda: closed.append(url))
    monkeypatch.setattr(jellyfin_playback.requests, "get", upstream)
    manager = jellyfin_playback.PlaybackSessions()
    monkeypatch.setattr('api.api_movie_playback_router.PlaybackSessions', lambda: manager)
    app = FastAPI(); app.include_router(create_media_center_router(backend))
    clients = {name: TestClient(app) for name in users}
    for name, client in clients.items(): client.cookies.set(SESSION_COOKIE_NAME, tokens[name])
    def open_session(name="a"):
        response = clients[name].post(f"{BASE}/movies/session?item_id={ITEM}")
        assert response.status_code == 200, response.text
        return response.json()
    env = SimpleNamespace(**locals())
    try:
        yield env
    finally:
        # Revoked/profile-switched clients cannot close their old session via HTTP.
        # Release real session timers and playback leases even after a failed test.
        for token in list(manager.sessions):
            manager.close(token)
        for client in clients.values():
            client.close()


def test_members_progress_and_actions_are_profile_scoped(household):
    e = household
    url = f"{BASE}/movies/progress?item_id={ITEM}"
    assert e.clients['a'].get(url).json()['position_ticks'] == 45 * 60 * 10_000_000
    assert e.clients['b'].get(url).json()['position_ticks'] == 20 * 60 * 10_000_000
    body = {"profile_id": A, "generation": 7, "position_ticks": 100}
    assert e.clients['a'].post(url, json=body).status_code == 204
    assert e.saved[-1][0] == A
    assert e.clients['b'].get(url).json()['position_ticks'] == 20 * 60 * 10_000_000
    assert e.clients['b'].post(url, json=body).status_code == 409
    rail = f"{BASE}/continue-watching"
    hidden = e.clients['a'].post(f"{rail}/{ITEM}/action", json={"profile_id": A, "generation": 7, "action": "hide"})
    assert hidden.status_code == 200
    assert e.clients['a'].get(rail).json()['items'] == []
    assert len(e.clients['b'].get(rail).json()['items']) == 1
    assert e.clients['b'].post(f"{rail}/{ITEM}/action", json={"profile_id": B, "generation": 7, "action": "undo", "undo_token": hidden.json()['undo_token']}).status_code == 409


@pytest.mark.parametrize('role', ['admin', 'member'])
def test_enabled_roles_can_play_but_configuration_stays_admin_only(household, role):
    e = household; e.users['a']['role'] = role
    session = e.open_session()
    assert 'fixture-secret' not in str(session)
    if role == 'member':
        assert e.clients['a'].get(f'{BASE}/config').status_code == 403
        for path in ('probe', 'activate'):
            assert e.clients['a'].post(f'{BASE}/{path}', json={}).status_code == 403
    e.clients['a'].delete(f"{BASE}/playback/{session['id']}")


@pytest.mark.parametrize('route', ['movies/progress?item_id='+ITEM, 'continue-watching', f'continue-watching/{ITEM}/details', f'continue-watching/{ITEM}/image', f'episodes/{ITEM}/navigation'])
@pytest.mark.parametrize('denial', ['unlinked', 'disabled_user', 'unknown_role', 'jellyfin_disabled', 'playback_disabled'])
def test_deny_all_personal_routes_without_valid_permission(household, route, denial):
    e = household
    if denial == 'unlinked': e.users['a']['jellyfin_user_id'] = ''
    elif denial == 'disabled_user': e.users['a']['enabled'] = False
    elif denial == 'unknown_role': e.users['a']['role'] = 'guest'
    elif denial == 'jellyfin_disabled': e.flags['disabled'] = True
    else: e.flags['playback'] = False
    assert e.clients['a'].get(f'{BASE}/{route}').status_code in (401, 403)
    assert not e.saved


def test_no_session_or_wrong_kind_never_authorizes_playback(household):
    e = household
    e.clients['a'].cookies.clear()
    assert e.clients['a'].get(f'{BASE}/continue-watching').status_code == 401
    wrong = e.store.create(user_id='a')
    assert e.clients['a'].get(f'{BASE}/continue-watching', headers={'Authorization': f'Bearer {wrong}'}).status_code == 401
    mobile = e.store.create(kind=SESSION_KIND_MOBILE, user_id='a')
    assert e.clients['a'].get(f'{BASE}/continue-watching', headers={'Authorization': f'Bearer {mobile}'}).status_code == 200


def test_hls_manifest_segments_keys_and_control_are_private(household):
    e = household; session = e.open_session(); a, b = e.clients['a'], e.clients['b']
    manifest = a.get(session['url']); assert manifest.status_code == 200
    assert 'fixture-secret' not in manifest.text
    import re
    assets = re.findall(r'/api/media-center/playback/[^\s"]+', manifest.text)
    for path in [session['url'], *assets]:
        assert b.get(path).status_code == 404
        assert a.get(path).status_code == 200
    for suffix in ('heartbeat', 'seek'):
        assert b.post(f"{BASE}/playback/{session['id']}/{suffix}").status_code == 404
    assert b.delete(f"{BASE}/playback/{session['id']}").status_code == 404
    assert a.delete(f"{BASE}/playback/{session['id']}").status_code == 204


@pytest.mark.parametrize('mutation', ['revoke', 'profile', 'disable', 'generation', 'switch_round_trip', 'policy', 'hidden_item'])
def test_old_hls_sessions_stop_after_access_changes(household, mutation):
    e = household; session = e.open_session()
    if mutation == 'revoke': e.store.revoke(e.tokens['a'])
    elif mutation == 'profile': e.users['a']['jellyfin_user_id'] = B
    elif mutation == 'disable': e.users['a']['enabled'] = False
    elif mutation == 'generation': e.state.jellyfin_config_generation += 1
    elif mutation == 'switch_round_trip':
        assert e.store.switch_user(e.tokens['a'], 'b'); assert e.store.switch_user(e.tokens['a'], 'a')
    elif mutation == 'policy': e.flags['playback'] = False
    else: e.flags['visible'] = False
    assert e.clients['a'].get(session['url']).status_code in (401, 403, 404, 409)
    assert e.clients['a'].post(f"{BASE}/playback/{session['id']}/heartbeat").status_code in (401,403,404,409)


def test_invisible_title_match_never_opens_global_admin_stream(household):
    e = household; e.flags['visible'] = False
    assert e.clients['a'].post(f'{BASE}/movies/session?title=Demo&tmdb_id=1').status_code == 404
    assert e.clients['a'].get(f'{BASE}/movies/stream?item_id={ITEM}').status_code == 404
    assert not e.saved


def test_concurrent_users_do_not_mix_progress(household):
    from concurrent.futures import ThreadPoolExecutor
    e = household
    def update(name):
        profile, value = (A, 111) if name == 'a' else (B, 222)
        return e.clients[name].post(f'{BASE}/movies/progress?item_id={ITEM}', json={
            'profile_id': profile, 'generation': 7, 'position_ticks': value,
        }).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(update, ['a', 'b'])) == [204, 204]
    assert e.data[A]['PlaybackPositionTicks'] == 111
    assert e.data[B]['PlaybackPositionTicks'] == 222


def test_profile_changed_during_network_read_discards_old_result(household, monkeypatch):
    e = household
    def delayed(*args):
        result = e.read(*args)
        if args[2] == '/UserItems/Resume': e.users['a']['jellyfin_user_id'] = B
        return result
    monkeypatch.setattr('api.api_movie_playback_router._jellyfin_json', delayed)
    response = e.clients['a'].get(f'{BASE}/continue-watching')
    assert response.status_code == 409
    assert 'Pilot' not in response.text


def test_supplied_user_ids_do_not_change_progress_owner(household):
    e = household
    result = e.clients['a'].get(f'{BASE}/movies/progress?item_id={ITEM}&UserId={B}&profile_id={B}', headers={'X-User-Id': 'b'})
    assert result.status_code == 200
    assert result.json()['profile_id'] == A
    assert result.headers['cache-control'] == 'no-store'


def test_authorization_context_is_transient_and_rotated_on_switch(tmp_path, monkeypatch):
    import json
    from core.auth import SessionPersistenceError
    path = tmp_path / 'sessions.json'
    store = SessionStore(path); token = store.create(user_id='a')
    before = store.authorization_context(token)
    store.create(user_id='other')  # Serializing sessions must never include the opaque object.
    assert '_authorization_context' not in path.read_text()
    assert json.loads(path.read_text())
    reloaded = SessionStore(path)
    assert reloaded.authorization_context(token) != before
    def failed(): raise SessionPersistenceError('fixture')
    monkeypatch.setattr(store, '_save_locked', failed)
    with pytest.raises(SessionPersistenceError): store.switch_user(token, 'b')
    assert store.authorization_context(token) == before


@pytest.mark.parametrize('remote', [False, True])
def test_long_stream_stops_on_revocation_or_policy_change(household, monkeypatch, remote):
    import asyncio
    from api.playback_access import PlaybackAccess
    from api.guarded_stream import GuardedStream
    from starlette.requests import Request
    e = household
    now = [0.0]
    monkeypatch.setattr('api.playback_access.monotonic', lambda: now[0])
    request = Request({'type': 'http', 'headers': [(b'cookie', f'{SESSION_COOKIE_NAME}={e.tokens["a"]}'.encode())]})
    access = PlaybackAccess(e.backend, e.read); access.enabled_user(request)
    access.profile(request, 'http://jf')
    invalidated = []
    guard = access.stream_guard(request, lambda: access.profile(request, 'http://jf', force=True), invalidate=lambda: invalidated.append(True))
    def chunks():
        if guard(): yield b'first'
        now[0] = 11
        if remote: e.flags['playback'] = False
        else: e.store.revoke(e.tokens['a'])
        if guard(): yield b'forbidden'
    closed = []
    response = GuardedStream(SimpleNamespace(close=lambda: closed.append(True)), chunks())
    async def consume(): return [chunk async for chunk in response.body_iterator]
    assert asyncio.run(consume()) == [b'first']
    response.close()
    assert invalidated == [True] and closed == [True]
