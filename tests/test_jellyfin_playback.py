from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import jellyfin_playback as playback


@pytest.fixture
def session_manager(monkeypatch):
    monkeypatch.setattr(playback.requests, 'delete', lambda *a, **kw: nullcontext(SimpleNamespace(status_code=204)))
    manager = playback.PlaybackSessions()
    try:
        yield manager
    finally:
        for token in list(manager.sessions):
            manager.close(token)


def test_negotiate_uses_server_hls_timeline_and_profile(monkeypatch, session_manager):
    def post(url, **kw):
        assert url == 'http://jf/base/Items/item/PlaybackInfo'
        body = kw['json']
        assert body['StartTimeTicks'] == 0
        assert body['AllowAudioStreamCopy'] is False
        assert body['DeviceProfile']['TranscodingProfiles'][0]['Protocol'] == 'hls'
        return nullcontext(SimpleNamespace(status_code=200,json=lambda:{'PlaySessionId':'play','MediaSources':[{'Protocol':'File','Id':'source','TranscodingUrl':'/base/master.m3u8?api_key=secret','RunTimeTicks':100}]}))
    monkeypatch.setattr(playback.requests,'post',post)
    s=session_manager;r=s.open('http://jf/base','secret','item','profile',7,'user')
    assert r['mode']=='hls'
    assert 'secret' not in str(r)
    session=s.get(r['id'],'user','profile',7)
    assert session['play_session_id']=='play'
    for context in [('other','profile',7),('user','other',7),('user','profile',8)]:
        with pytest.raises(HTTPException) as error: s.get(r['id'],*context)
        assert error.value.status_code==404
    with pytest.raises(HTTPException): s.asset(session,'http://evil/segment.ts',session['base'])


def test_manifest_rewrites_nested_segments_keys_and_ranges(monkeypatch):
    s=playback.PlaybackSessions()
    session={'token':'token','base':'http://jf','headers':{},'assets':{}}
    url=s.asset(session,'http://jf/video/master.m3u8?api_key=secret','http://jf/')
    closed=[]
    response=SimpleNamespace(status_code=200,headers={'Content-Type':'application/vnd.apple.mpegurl'},iter_content=lambda _:iter([b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key?api_key=secret"\nchild.m3u8?api_key=secret\n']),close=lambda:closed.append(True))
    monkeypatch.setattr(playback.requests,'get',lambda *a,**kw:response)
    result=s.response(session,url.rsplit('/',1)[-1],None)
    assert 'secret' not in result.body.decode()
    assert result.body.count(b'/api/media-center/playback/token/asset/')==2
    assert 'http://jf/video/child.m3u8?api_key=secret' in session['assets'].values()
    assert closed==[True]
    def get(url,**kw):
        assert kw['headers']['Range']=='bytes=100-200'
        return SimpleNamespace(status_code=206,headers={'Content-Type':'video/mp4','Content-Range':'bytes 100-200/1000','Content-Length':'101'},iter_content=lambda _:iter([b'x']),close=lambda:None)
    monkeypatch.setattr(playback.requests,'get',get)
    binary=s.asset(session,'http://jf/video/file.mp4','http://jf/')
    r=s.response(session,binary.rsplit('/',1)[-1],'bytes=100-200')
    assert r.status_code==206 and r.headers['content-range']=='bytes 100-200/1000'


def test_interrupt_and_expiry_stop_only_the_owned_encoder(monkeypatch, session_manager):
    stopped=[]
    monkeypatch.setattr(playback,'negotiate',lambda *a:{'path':'/master.m3u8','mode':'hls','duration_ticks':100,'headers':{},'play_session_id':'play','device_id':'device'})
    monkeypatch.setattr(playback.requests,'delete',lambda url,**kw: stopped.append(kw['params']) or nullcontext(SimpleNamespace(status_code=204)))
    sessions=session_manager
    result=sessions.open('http://jf','secret','item','profile',1,'owner')
    session=sessions.get(result['id'],'owner','profile',1)
    sessions.interrupt(session)
    assert sessions.get(result['id'],'owner','profile',1) is session
    assert stopped==[{'deviceId':'device','playSessionId':'play'}]
    session['expiry'].cancel()
    session['used']-=130
    sessions._expire(result['id'])
    assert result['id'] not in sessions.sessions
    assert len(stopped)==2
