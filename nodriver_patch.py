"""
Kontrollierter Fix für einen Defekt in nodriver 0.50.3 (die neueste Version –
kein Upgrade verfügbar).

Problem: nodrivers `Connection._listener` ist die einzige Coroutine, die den
CDP-Websocket liest. Ihre Fehlerschleife sieht so aus:

    while True:
        try:
            raw = await ws.recv()
            ...
        except ConnectionClosed: break
        except CancelledError:  break
        except Exception as e:
            logger.error(f"background listener error: {e}")   # <- KEIN break/sleep

Wenn `websockets` (>=14, hier 16.0) unter bestimmtem Timing die Assertion
`cannot call get() concurrently` wirft (ein redundanter/verrenneter Listener
liegt auf demselben Socket), wird dieser Fehler NICHT abgefangen-und-beendet,
sondern die Schleife ruft sofort wieder `ws.recv()` auf → derselbe Fehler →
Tausende Log-Zeilen pro Sekunde UND eine CPU-Dauerlast (Busy-Loop). Genau das
erzeugt den beobachteten `AssertionError: cannot call get() concurrently`-Spam.

Fix: `_listener` so ersetzen, dass er bei der Concurrency-Assertion diesen
(redundanten) Listener sauber beendet – der legitime Listener auf dem Socket
läuft normal weiter, die Extraktion funktioniert also unverändert – und bei
anderen unerwarteten Fehlern nach wenigen Versuchen mit kurzer Pause aussteigt
statt endlos zu drehen.

Reines Hochsetzen des Loglevels würde nur die Ausgabe verstecken, nicht die
Busy-Loop stoppen – deshalb dieser Patch.
"""

import asyncio
import json
import logging

logger = logging.getLogger("nodriver.patch")

_applied = False
_cdp_checked = False


def ensure_cdp_utf8() -> None:
    """Repariert einen Auslieferungsfehler von nodriver 0.50.3: `cdp/network.py`
    enthält in Zeile 1345 ('±Inf') das Zeichen ± als rohes Latin-1-Byte 0xB1 –
    OHNE Encoding-Deklaration. Python 3 kann die Datei dann nicht kompilieren
    (`SyntaxError: Non-UTF-8 code ...`), wodurch bereits `import nodriver`
    scheitert und die komplette VOE-Browser-Extraktion tot ist.

    Auf frischen Installationen (z.B. im Docker-Container) tritt das IMMER auf;
    das alte Windows-Setup lief nur, weil die Datei dort irgendwann als UTF-8
    neu gespeichert wurde. Fix: betroffene cdp/*.py einmalig als Latin-1 lesen
    und als gültiges UTF-8 zurückschreiben (0xB1 -> 0xC2 0xB1). Muss VOR dem
    ersten `import nodriver` laufen, findet die Dateien daher über find_spec
    (ohne nodriver zu importieren). Idempotent + fehlertolerant."""
    global _cdp_checked
    if _cdp_checked:
        return
    _cdp_checked = True
    try:
        import importlib.util
        import os
        spec = importlib.util.find_spec("nodriver")
        if not spec or not spec.origin:
            return
        cdp_dir = os.path.join(os.path.dirname(spec.origin), "cdp")
        if not os.path.isdir(cdp_dir):
            return
        for name in sorted(os.listdir(cdp_dir)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(cdp_dir, name)
            try:
                data = open(path, "rb").read()
            except OSError:
                continue
            try:
                data.decode("utf-8")
                continue  # bereits gültiges UTF-8
            except UnicodeDecodeError:
                pass
            try:
                # Latin-1 kann jedes Byte abbilden -> als UTF-8 zurückschreiben.
                open(path, "wb").write(data.decode("latin-1").encode("utf-8"))
                logger.info("nodriver_patch: %s nach UTF-8 repariert", name)
            except OSError as exc:
                logger.warning("nodriver_patch: %s nicht reparierbar: %s", name, exc)
    except Exception as exc:  # niemals den Start blockieren
        logger.debug("nodriver_patch: ensure_cdp_utf8 übersprungen: %s", exc)


def apply() -> None:
    """Idempotent: ersetzt Connection._listener durch eine robuste Variante."""
    global _applied
    if _applied:
        return
    ensure_cdp_utf8()   # kaputte cdp-Quelle reparieren, BEVOR nodriver importiert wird
    try:
        import nodriver.core.connection as _conn
    except Exception as exc:  # nodriver nicht installiert -> nichts zu tun
        logger.debug("nodriver_patch: import fehlgeschlagen: %s", exc)
        return

    websockets = _conn.websockets

    async def _patched_listener(self):
        ws = self.socket
        if ws is None:
            raise RuntimeError("Listener started without an active socket connection.")
        consecutive = 0
        while True:
            try:
                raw = await ws.recv()
                consecutive = 0
                if not raw:
                    continue
                message = json.loads(raw)
                if "id" in message:
                    future = self._mapper.pop(message["id"], None)
                    if future and not future.done():
                        future.set_result(message)
                elif "method" in message:
                    await self.process_event(message, None)
            except websockets.exceptions.ConnectionClosed:
                self._fail_pending_futures(ConnectionError("Connection closed"))
                break
            except asyncio.CancelledError as e:
                self._fail_pending_futures(e)
                break
            except AssertionError as e:
                # 'cannot call get() concurrently': ein redundanter Listener liegt
                # auf demselben Socket. Diesen hier beenden (der legitime Listener
                # bleibt aktiv) statt endlos zu spammen.
                if "concurrent" in str(e).lower():
                    logger.debug("listener: redundanter recv – beende diesen Listener")
                    break
                consecutive += 1
                if consecutive > 5:
                    logger.debug("listener: zu viele Fehler – Stopp: %s", e)
                    break
            except Exception as e:  # noqa: BLE001 – Schutz vor Busy-Loop
                consecutive += 1
                if consecutive > 5:
                    logger.debug("listener: zu viele Fehler – Stopp: %s", e)
                    break
                await asyncio.sleep(0.2)

    _conn.Connection._listener = _patched_listener
    _applied = True
    logger.debug("nodriver_patch: Connection._listener ersetzt.")
