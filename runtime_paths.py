"""
Zentrale Auflösung des Verzeichnisses für persistenten App-State.

Damit dieselbe Codebasis unverändert unter Windows (Entwicklung) UND in einem
Docker-Container (NAS, 24/7) läuft, wird der Ablageort für persistente Dateien
(Cookies, Hoster-Intel, Einstellungen/Watchlist) über eine Umgebungsvariable
gesteuert:

    SERIENDL_DATA_DIR   – Zielordner für persistenten State (z.B. ein Docker-
                          Volume wie /app/data). Ist er NICHT gesetzt, bleibt das
                          bisherige Verhalten erhalten (Dateien neben dem Code).

Der Download-Zielordner ist NICHT hier, sondern in config.py (DOWNLOAD_DIR) –
er ist eine eigene, im UI änderbare Nutzereinstellung.
"""

import os
from pathlib import Path

_PROJECT_DIR = Path(__file__).parent.resolve()


def data_dir() -> Path:
    """Verzeichnis für persistenten App-State. Über SERIENDL_DATA_DIR steuerbar;
    Default = Projektordner (unverändertes Verhalten ohne die Variable)."""
    env = os.environ.get("SERIENDL_DATA_DIR", "").strip()
    base = Path(env) if env else _PROJECT_DIR
    if env:
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return base
