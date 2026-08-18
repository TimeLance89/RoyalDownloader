"""Authenticated API/UI surface for user-driven SerienStream verification."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from serienstream_verification import (
    DEFAULT_EPISODE_URL,
    SERIESSTREAM_VERIFICATION,
)

router = APIRouter(tags=["administration", "serienstream"])


class VerificationStartBody(BaseModel):
    episode_url: str = DEFAULT_EPISODE_URL


class VerificationClickBody(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class VerificationScrollBody(BaseModel):
    delta_y: float = Field(ge=-1600, le=1600)


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(400, str(exc))
    return HTTPException(409, str(exc))


@router.get("/api/v1/providers/serienstream/verification")
@router.get("/api/providers/serienstream/verification")
async def verification_status():
    return await run_in_threadpool(SERIESSTREAM_VERIFICATION.status)


@router.post("/api/v1/providers/serienstream/verification/start")
@router.post("/api/providers/serienstream/verification/start")
async def verification_start(body: VerificationStartBody):
    try:
        return await run_in_threadpool(SERIESSTREAM_VERIFICATION.start, body.episode_url)
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/api/v1/providers/serienstream/verification/frame")
@router.get("/api/providers/serienstream/verification/frame")
async def verification_frame():
    try:
        image = await run_in_threadpool(SERIESSTREAM_VERIFICATION.screenshot)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return Response(
        image,
        media_type="image/png",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.post("/api/v1/providers/serienstream/verification/click")
@router.post("/api/providers/serienstream/verification/click")
async def verification_click(body: VerificationClickBody):
    try:
        return await run_in_threadpool(
            SERIESSTREAM_VERIFICATION.click,
            body.x,
            body.y,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/api/v1/providers/serienstream/verification/scroll")
@router.post("/api/providers/serienstream/verification/scroll")
async def verification_scroll(body: VerificationScrollBody):
    try:
        return await run_in_threadpool(
            SERIESSTREAM_VERIFICATION.scroll,
            body.delta_y,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/api/v1/providers/serienstream/verification/finish")
@router.post("/api/providers/serienstream/verification/finish")
async def verification_finish():
    try:
        return await run_in_threadpool(SERIESSTREAM_VERIFICATION.finish)
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/api/v1/providers/serienstream/verification/cancel")
@router.post("/api/providers/serienstream/verification/cancel")
async def verification_cancel():
    await run_in_threadpool(SERIESSTREAM_VERIFICATION.close)
    return {"active": False, "phase": "idle", "cancelled": True}


_VERIFICATION_UI = r'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Royal · SerienStream freischalten</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#090b10;color:#f3f5f7}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 20% 0,#25201a 0,#0d1016 36%,#07090d 100%)}
main{max-width:1180px;margin:auto;padding:28px 18px 48px}.head{display:flex;gap:20px;align-items:flex-end;justify-content:space-between;margin-bottom:20px}
.kicker{font-size:12px;letter-spacing:.22em;color:#cfad71}h1{font-size:clamp(28px,5vw,48px);margin:5px 0 7px}p{color:#aeb5c0;max-width:760px;line-height:1.55}
.panel{border:1px solid #2b3039;border-radius:18px;background:#10141bcc;box-shadow:0 20px 70px #0008;overflow:hidden}.toolbar{padding:14px 16px;border-bottom:1px solid #262b33;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button{border:1px solid #3d434d;border-radius:10px;background:#171c24;color:#f4f5f7;padding:10px 14px;font-weight:700;cursor:pointer}button.primary{background:#c99c54;color:#101010;border-color:#c99c54}button:disabled{opacity:.45;cursor:not-allowed}
.badge{margin-left:auto;padding:7px 10px;border-radius:999px;background:#252a33;color:#dce1e7;font-size:12px}.badge.ok{background:#143b2d;color:#9df0c6}.badge.warn{background:#4b3215;color:#ffd99a}
.viewport{position:relative;background:#050607;display:grid;place-items:center;min-height:420px}.viewport img{display:block;max-width:100%;height:auto;cursor:crosshair;user-select:none}.empty{padding:70px 20px;color:#8c95a2;text-align:center}
.status{padding:14px 16px;border-top:1px solid #262b33;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0c0f14;border:1px solid #242a33;border-radius:10px;padding:10px}.stat span{display:block;font-size:10px;letter-spacing:.12em;color:#7e8794}.stat strong{display:block;margin-top:5px;font-size:13px;overflow-wrap:anywhere}
.notice{margin-top:18px;padding:14px 16px;border:1px solid #473c28;background:#19150f;border-radius:12px;color:#dfc89e}.error{color:#ff9b9b}.success{color:#93edbd}
</style>
</head>
<body><main>
<div class="head"><div><div class="kicker">ROYAL · PROVIDER SESSION</div><h1>SerienStream freischalten</h1><p>Royal zeigt dir einen echten Chromium-Tab der SerienStream-Episodenseite. Klicke die Verifikation selbst an. Royal löst oder manipuliert die Challenge nicht; nach erfolgreicher Bestätigung wird nur die entstandene Browser-Sitzung übernommen.</p></div></div>
<section class="panel">
<div class="toolbar">
<button id="start" class="primary">Freischaltung starten</button>
<button id="up" disabled>↑ Scrollen</button><button id="down" disabled>↓ Scrollen</button>
<button id="finish" disabled>Session übernehmen &amp; prüfen</button><button id="cancel" disabled>Abbrechen</button>
<span id="badge" class="badge">Nicht gestartet</span>
</div>
<div id="viewport" class="viewport"><div class="empty">Starte die Freischaltung. Danach erscheint hier der Browser.</div></div>
<div class="status"><div class="stat"><span>PHASE</span><strong id="phase">idle</strong></div><div class="stat"><span>BROWSER</span><strong id="browser">—</strong></div><div class="stat"><span>COOKIES</span><strong id="cookies">—</strong></div><div class="stat"><span>VERIFIKATION</span><strong id="verify">—</strong></div></div>
</section>
<div id="message" class="notice">Nach dem Start klickst du im Bild ausschließlich selbst. Wenn SerienStream die Bestätigung akzeptiert hat, übernimmt Royal die Session und prüft sofort einen echten Embed-Redirect.</div>
</main>
<script>
const root='/api/providers/serienstream/verification';
const $=id=>document.getElementById(id);let active=false,pollTimer=0,finishing=false;
async function req(path='',opts={}){const response=await fetch(root+path,{credentials:'same-origin',headers:{'Content-Type':'application/json',...(opts.headers||{})},...opts});let data={};try{data=await response.json()}catch{}if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);return data}
function message(text,kind=''){const el=$('message');el.textContent=text;el.className='notice '+kind}
function render(s){active=!!s.active;$('phase').textContent=s.phase||'idle';$('browser').textContent=s.browser_url||'—';$('cookies').textContent=(s.cookie_names||[]).join(', ')||'—';$('verify').textContent=s.has_clearance?'Browser-Freigabe erkannt':((s.page||{}).turnstile?'Bestätigung wartet':'Noch nicht erkannt');$('up').disabled=!active;$('down').disabled=!active;$('finish').disabled=!active;$('cancel').disabled=!active;$('start').disabled=active;const badge=$('badge');badge.textContent=s.has_clearance?'Bestätigung erkannt':active?'Browser aktiv':'Nicht gestartet';badge.className='badge '+(s.has_clearance?'ok':active?'warn':'');if(s.error)message(s.error,'error')}
function frame(){if(!active){$('viewport').innerHTML='<div class="empty">Keine aktive Browser-Sitzung.</div>';return}let img=$('frame');if(!img){$('viewport').innerHTML='<img id="frame" alt="SerienStream Browseransicht">';img=$('frame');img.addEventListener('click',clickFrame)}img.src=root+'/frame?t='+Date.now()}
async function refresh(){try{const s=await req();render(s);frame();if(s.has_clearance&&!finishing)await finish()}catch(e){message(e.message,'error')}finally{clearTimeout(pollTimer);if(active)pollTimer=setTimeout(refresh,1300)}}
async function clickFrame(event){if(!active)return;const img=event.currentTarget;const rect=img.getBoundingClientRect();const x=(event.clientX-rect.left)/rect.width;const y=(event.clientY-rect.top)/rect.height;try{render(await req('/click',{method:'POST',body:JSON.stringify({x,y})}));frame()}catch(e){message(e.message,'error')}}
async function finish(){if(finishing)return;finishing=true;try{const s=await req('/finish',{method:'POST',body:'{}'});render(s);if(s.verified){active=false;frame();message(`Freigeschaltet. Embed-Ziel erreicht: ${s.final_host||'extern'}. Wartende SerienStream-Jobs dürfen wieder anlaufen.`,'success');clearTimeout(pollTimer)}else{message('SerienStream bestätigt die Sitzung noch nicht. Bitte die sichtbare Verifikation abschließen.','error')}}catch(e){message(e.message,'error')}finally{finishing=false}}
$('start').addEventListener('click',async()=>{message('Chromium und SerienStream werden vorbereitet …');try{const s=await req('/start',{method:'POST',body:JSON.stringify({})});render(s);frame();refresh()}catch(e){message(e.message,'error')}});
$('finish').addEventListener('click',finish);$('cancel').addEventListener('click',async()=>{try{render(await req('/cancel',{method:'POST',body:'{}'}));active=false;frame();message('Freischaltung beendet.')}catch(e){message(e.message,'error')}});
$('up').addEventListener('click',async()=>{try{render(await req('/scroll',{method:'POST',body:JSON.stringify({delta_y:-650})}));frame()}catch(e){message(e.message,'error')}});$('down').addEventListener('click',async()=>{try{render(await req('/scroll',{method:'POST',body:JSON.stringify({delta_y:650})}));frame()}catch(e){message(e.message,'error')}});
req().then(s=>{render(s);if(s.active){frame();refresh()}}).catch(e=>message(e.message,'error'));
</script></body></html>'''


@router.get("/api/providers/serienstream/verification/ui", response_class=HTMLResponse)
async def verification_ui():
    return HTMLResponse(
        _VERIFICATION_UI,
        headers={"Cache-Control": "no-store, max-age=0"},
    )
