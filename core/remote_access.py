"""Own-domain setup artifacts and bounded, DNS-pinned HTTPS instance checks."""
from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit
import zipfile

import urllib3
import yaml


CLOUDFLARED_IMAGE = "cloudflare/cloudflared:2026.10.4@sha256:c6c7ae1d5dfdcb094ad344ed68ccffc26635c9c6be80965664c33baf064b0515"
PROOF_PATH = "/api/public/remote-access/verify"
SERVICE_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}")


class RemoteAccessError(ValueError):
    """A safe, user-facing configuration or verification error."""


def public_hostname(value: str) -> str:
    raw = value.strip()
    if not raw.startswith("https://"):
        raw = "https://" + raw
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError
        if len(host) > 253 or len(host.split(".")) < 2 or host.endswith((".local", ".lan", ".localhost", ".internal", ".home", ".test", ".invalid")):
            raise ValueError
        if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return host
    except (ValueError, UnicodeError):
        pass
    raise RemoteAccessError("Eigene öffentliche Domain eingeben, z. B. royal.meine-domain.de; nur HTTPS ohne Port oder Pfad.")


def _port() -> int:
    try:
        port = int(os.environ.get("PORT", "8765"))
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    raise RemoteAccessError("Der interne Royal-Port ist ungültig konfiguriert.")


def plan(domain: str, service: str, local_host: str = "") -> dict:
    host = public_hostname(domain)
    if not SERVICE_RE.fullmatch(service) or service == "cloudflare-tunnel":
        raise RemoteAccessError("Ungültiger Docker-Compose-Dienstname.")
    # Keep existing explicit LAN/public names, never carry over a wildcard.
    candidates = [host, "localhost", "127.0.0.1", "::1", local_host]
    candidates.extend(os.environ.get("ROYAL_ALLOWED_HOSTS", "").replace(";", ",").split(","))
    allowed = []
    for candidate in candidates:
        candidate = candidate.strip().lower()
        if candidate and candidate != "*" and re.fullmatch(r"[a-z0-9.\[\]:_-]+", candidate) and candidate not in allowed:
            allowed.append(candidate)
    return {
        "url": f"https://{host}", "hostname": host, "service": service,
        "origin": f"http://127.0.0.1:{_port()}",
        "allowed_hosts": ",".join(allowed), "image": CLOUDFLARED_IMAGE,
        "command": f"docker compose -f docker-compose.yml -f docker-compose.remote.yml up -d --force-recreate {service} cloudflare-tunnel",
    }


def bundle(config: dict, token: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_+/=-]{40,8192}", token):
        raise RemoteAccessError("Nur den Tunnel-Token aus Cloudflare einfügen, keinen Befehl oder API-Schlüssel.")
    service = config["service"]
    overlay = {
        "services": {
            service: {"environment": {
                "ROYAL_ALLOWED_HOSTS": config["allowed_hosts"],
                "ROYAL_TRUSTED_PROXIES": "127.0.0.1/32,::1/128",
                "TRUST_CLOUDFLARE_HEADERS": "true", "TRUST_X_FORWARDED_FOR": "false",
            }},
            "cloudflare-tunnel": {
                "image": CLOUDFLARED_IMAGE, "restart": "unless-stopped",
                "network_mode": f"service:{service}", "depends_on": [service],
                "user": "${PUID:-1000}:${PGID:-1000}", "read_only": True,
                "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
                "pids_limit": 128, "mem_limit": "256m", "cpus": 1.0,
                "command": ["tunnel", "--no-autoupdate", "run", "--token-file", "/run/secrets/cloudflare_tunnel_token"],
                "secrets": ["cloudflare_tunnel_token"],
            },
        },
        "secrets": {"cloudflare_tunnel_token": {"file": "./cloudflare-tunnel.token"}},
    }
    readme = f"""Royal: eigene Domain einrichten

Adresse: {config['url']}
Cloudflare: öffentliche Anwendungsroute für {config['hostname']}, Typ HTTP,
Service-URL: {config['origin']} (Host-Header NICHT überschreiben).
Voraussetzung: eigene Domain mit aktivem DNS bei Cloudflare, eigener remotely
managed Tunnel. Kein Quick Tunnel, keine Royal-Subdomain. Cloudflare-Konto und
Domain werden vom Benutzer verwaltet; Domainkosten trägt der Benutzer.

1. ZIP auf dem NAS im Ordner der BESTEHENDEN docker-compose.yml entpacken.
   Vorher Compose-Datei sichern. Dieses Overlay ergänzt die bestehende Installation.
   Es ersetzt keine Medienpfade. Standard-Dienst: {service}.
   Bei NAS-Container-Oberflächen ohne Compose-Projekt: nicht blind importieren;
   zuerst vorhandene Installation als Compose-Projekt mit denselben Mounts sichern.
2. Token gehört nur dem ausführenden NAS-Benutzer (PUID/PGID wie im Projekt).
   Auf dem NAS: chmod 600 cloudflare-tunnel.token
   Bei anderem Besitzer zuerst passend chown PUID:PGID setzen.
3. Im selben Ordner ausführen (Royal wird kurz neu gestartet):
   {config['command']}
4. In Royal unter Einstellungen > Externer Zugriff die HTTPS-Adresse prüfen.
   Danach dort anmelden und Authenticator unter Zugang aktivieren.

Sicherheit: Die ZIP enthält den Tunnel-Token. Nicht teilen, nicht in Git ablegen.
Token bei Verlust im Cloudflare-Dashboard rotieren. Der Assistent speichert ihn
nicht. Die lokale Token-Datei wird vom Tunnel benötigt und bleibt auf dem NAS.
Keine Router-Portfreigabe nötig. Bestehende WAN-Portfreigaben entfernen und
IPv6-Firewall prüfen. LAN-Zugriff bleibt verfügbar. Andere Reverse-Proxys müssen
getrennt auf präzise vertrauenswürdige Absender geprüft werden.
Bei bestehendem Tunnel diesen zuerst sichern; nur eine Connector-Konfiguration
für diese Route betreiben. Der Assistent verändert keine Cloudflare-Einstellungen.
Cloudflare Access ist optional; dessen Login kann die automatische Prüfung blockieren.

Rücknahme: cloudflare-tunnel stoppen/entfernen, Route im Cloudflare-Dashboard
entfernen, ursprüngliches Compose-Projekt ohne Overlay neu erstellen. Eine spätere
Neuerstellung von Royal muss auch den Tunnel neu erstellen (gemeinsamer Netzwerkraum).
"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in {
            "docker-compose.remote.yml": yaml.safe_dump(overlay, sort_keys=False),
            "cloudflare-tunnel.token": token + "\n", "README.txt": readme,
            ".gitignore.remote-access": "cloudflare-tunnel.token\nroyal-remote-access.zip\n",
        }.items():
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = 0o100600 << 16
            archive.writestr(entry, content.encode("utf-8"))
    return output.getvalue()


def public_ips(host: str) -> list[str]:
    addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise RemoteAccessError("Die Domain muss ausschließlich auf öffentliche IP-Adressen zeigen.")
    return addresses


def fetch_public(host: str, ip: str, path: str) -> tuple[int, dict]:
    # Connect to the validated numeric address, while retaining SNI/certificate
    # validation for the domain. No DNS rebinding, redirects, cookies or env proxy.
    with urllib3.HTTPSConnectionPool(ip, port=443, server_hostname=host, assert_hostname=host,
                                   cert_reqs="CERT_REQUIRED", maxsize=1) as pool:
        response = pool.request("GET", path, headers={"Host": host, "Accept": "application/json"},
                                timeout=urllib3.Timeout(total=6, connect=3, read=3),
                                retries=False, redirect=False, preload_content=False)
        try:
            raw = response.read(16385)
            if len(raw) > 16384:
                raise RemoteAccessError("Unerwartet große Antwort der öffentlichen Adresse.")
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                payload = {}
            return response.status, payload if isinstance(payload, dict) else {}
        finally:
            response.close()


class RemoteAccessVerifier:
    """At most one outstanding job, including DNS calls that outlive the UI timeout."""

    def __init__(self, fetch=fetch_public, resolve=public_ips, clock=time.monotonic):
        self.fetch = fetch
        self.resolve = resolve
        self.clock = clock
        self.lock = threading.Lock()
        self.proofs: dict[str, tuple[str, float, str]] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="royal-domain-check")
        self.pending = None
        self.last_started = float("-inf")

    def proof(self, challenge: str, host: str) -> str | None:
        with self.lock:
            entry = self.proofs.get(challenge)
            return entry[0] if entry and entry[1] > self.clock() and entry[2] == host else None

    def _verify(self, host: str) -> dict:
        challenge, expected = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.lock:
            self.proofs[challenge] = (expected, self.clock() + 30, host)
        try:
            addresses = self.resolve(host)
            # Reject unsafe injected/custom resolver results as well.
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
                raise RemoteAccessError("Die Domain zeigt auf eine nicht öffentliche IP-Adresse.")
            ip = addresses[0]
            status, payload = self.fetch(host, ip, f"{PROOF_PATH}?challenge={challenge}")
            if status != 200 or not secrets.compare_digest(str(payload.get("proof", "")), expected):
                raise RemoteAccessError("Diese Royal-Installation wurde nicht bestätigt. Tunnel-Route, Host-Freigabe und ggf. Cloudflare Access prüfen.")
            status, auth = self.fetch(host, ip, "/api/auth/status")
            if status != 200 or auth.get("configured") is not True or auth.get("authenticated") is not False or auth.get("required") is not True:
                raise RemoteAccessError("Der öffentliche Zugang verlangt keine bestätigte Royal-Anmeldung. Zugangsschutz prüfen.")
            status, _ = self.fetch(host, ip, "/api/queue")
            if status != 401:
                raise RemoteAccessError("Die geschützte API hat anonyme Zugriffe nicht eindeutig abgewiesen.")
            import qrcode
            import qrcode.image.svg
            output = io.BytesIO()
            qrcode.make(f"https://{host}", image_factory=qrcode.image.svg.SvgPathFillImage).save(output)
            return {"verified": True, "url": f"https://{host}",
                    "checks": ["HTTPS-Zertifikat gültig", "Diese Royal-Installation bestätigt", "Anmeldung erforderlich", "Geschützte API weist anonyme Zugriffe ab"],
                    "qr_data_url": "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode()}
        except RemoteAccessError:
            raise
        except (OSError, urllib3.exceptions.HTTPError) as exc:
            raise RemoteAccessError("HTTPS-Adresse nicht erreichbar. DNS, Tunnel-Verbindung und Zertifikat prüfen.") from exc
        finally:
            with self.lock:
                self.proofs.pop(challenge, None)

    async def verify(self, domain: str) -> dict:
        host = public_hostname(domain)
        with self.lock:
            if (self.pending is not None and not self.pending.done()) or self.clock() - self.last_started < 10:
                raise RemoteAccessError("Eine Prüfung läuft bereits oder wurde gerade beendet. Kurz warten und erneut prüfen.")
            self.last_started = self.clock()
            self.pending = self.executor.submit(self._verify, host)
            future = self.pending
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=22)
        except TimeoutError as exc:
            raise RemoteAccessError("Prüfung dauert zu lange. DNS und Tunnel prüfen; eine laufende Prüfung wird nicht mehrfach gestartet.") from exc

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
