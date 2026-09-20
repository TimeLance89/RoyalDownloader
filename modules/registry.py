"""Registry data is separate from the core manager and server composition."""
from core.module_manager import ModuleManifest

BUILTIN_MODULES = (
    ModuleManifest("jellyfin-recommendations", "Jellyfin-Empfehlungsdienst", "Aktualisiert Jellyfin-basierte Empfehlungen im Hintergrund.", "Integration", {"cpu":"Niedrig","ram":"Niedrig","network":"Niedrig","storage":"Niedrig"}, ("jellyfin-recommender",)),
    ModuleManifest("seerr-sync", "Seerr-Synchronisierung", "Gleicht Seerr-Anfragen im Hintergrund ab.", "Integration", {"cpu":"Niedrig","ram":"Niedrig","network":"Mittel","storage":"Niedrig"}, ("seerr-request-bridge",)),
    ModuleManifest("telegram-control", "Telegram-Steuerung", "Startet ausschließlich den Telegram-Long-Polling-Dienst.", "Integration", {"cpu":"Niedrig","ram":"Niedrig","network":"Niedrig","storage":"Niedrig"}, ("telegram-bot",)),
    ModuleManifest("automatic-updates", "Automatische Updateprüfung", "Prüft Royal im Hintergrund; die optionale yt-dlp-Prüfung folgt ihrer eigenen Laufzeitkonfiguration. Manuelle Wartung bleibt Core.", "Wartung", {"cpu":"Niedrig","ram":"Niedrig","network":"Niedrig","storage":"Niedrig"}, ("automatic-updater","ytdlp-runtime-updater")),
)
