"""Built-in module registry with persisted state and lifecycle ownership."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import RLock
from typing import Callable


@dataclass(frozen=True)
class ModuleManifest:
    id: str
    name: str
    description: str
    category: str
    resources: dict[str, str]
    background_services: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    optional_requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    core: bool = False


BUILTIN_MODULES = (
    ModuleManifest("jellyfin-recommendations", "Jellyfin-Empfehlungen", "Erstellt im Hintergrund persönliche Startseiten-Empfehlungen aus Jellyfin.", "Integration", {"cpu": "Niedrig", "ram": "Niedrig", "network": "Niedrig", "storage": "Niedrig"}, ("jellyfin-recommender",)),
    ModuleManifest("seerr-sync", "Seerr-Synchronisierung", "Gleicht Medienanfragen mit Seerr ab und hält den Request-Status aktuell.", "Integration", {"cpu": "Niedrig", "ram": "Niedrig", "network": "Mittel", "storage": "Niedrig"}, ("seerr-request-bridge",)),
    ModuleManifest("telegram-control", "Telegram-Steuerung", "Ermöglicht Status, Suche und Download-Steuerung über einen Telegram-Bot.", "Integration", {"cpu": "Niedrig", "ram": "Niedrig", "network": "Niedrig", "storage": "Niedrig"}, ("telegram-bot",)),
    ModuleManifest("automatic-updates", "Automatische Updates", "Prüft im Hintergrund auf Royal- und yt-dlp-Updates. Manuelle Updates bleiben verfügbar.", "Wartung", {"cpu": "Niedrig", "ram": "Niedrig", "network": "Niedrig", "storage": "Niedrig"}, ("automatic-updater", "ytdlp-runtime-updater")),
)


class ModuleDependencyError(ValueError):
    def __init__(self, module_id: str, dependents: list[str]):
        self.module_id = module_id
        self.dependents = dependents
        super().__init__(f"Modul {module_id} wird benötigt von: {', '.join(dependents)}")


class ModuleManager:
    """Owns module configuration and delegates actual work to lifecycle hooks."""

    def __init__(self, load: Callable[[], dict], save: Callable[[dict], bool]):
        self._load = load
        self._save = save
        self._lock = RLock()
        self._manifests = {manifest.id: manifest for manifest in BUILTIN_MODULES}
        raw = load() if callable(load) else {}
        self._enabled = {module_id: bool(raw.get(module_id, True)) for module_id in self._manifests}
        self._status = {module_id: "disabled" if not enabled else "configured" for module_id, enabled in self._enabled.items()}
        self._errors: dict[str, str] = {}
        self._lifecycle: Callable[[str, bool], None] | None = None

    def set_lifecycle(self, callback: Callable[[str, bool], None]) -> None:
        self._lifecycle = callback

    def _dependents(self, module_id: str) -> list[str]:
        return sorted(item.id for item in self._manifests.values() if module_id in item.requires and self._enabled[item.id])

    def payload(self) -> dict:
        with self._lock:
            modules = []
            for manifest in BUILTIN_MODULES:
                modules.append({
                    **asdict(manifest),
                    "enabled": self._enabled[manifest.id],
                    "status": self._status[manifest.id],
                    "error": self._errors.get(manifest.id, ""),
                    "used_by": self._dependents(manifest.id),
                })
            return {"modules": modules, "presets": {"minimal": [], "standard": [item.id for item in BUILTIN_MODULES], "custom": [item.id for item in BUILTIN_MODULES if self._enabled[item.id]]}}

    def start_enabled(self) -> None:
        for module_id, enabled in tuple(self._enabled.items()):
            if enabled:
                self._apply_lifecycle(module_id, True)

    def set_enabled(self, module_id: str, enabled: bool, cascade: bool = False) -> dict:
        with self._lock:
            manifest = self._manifests.get(module_id)
            if manifest is None:
                raise KeyError(module_id)
            if manifest.core and not enabled:
                raise ValueError("Core-Module können nicht deaktiviert werden.")
            dependents = self._dependents(module_id) if not enabled else []
            if dependents and not cascade:
                raise ModuleDependencyError(module_id, dependents)
            changes = [module_id, *dependents]
            for changed in changes:
                self._enabled[changed] = enabled
                self._status[changed] = "configured" if enabled else "disabled"
                self._errors.pop(changed, None)
            if not self._save(dict(self._enabled)):
                raise RuntimeError("Modulkonfiguration konnte nicht gespeichert werden.")
        for changed in changes:
            self._apply_lifecycle(changed, enabled)
        return self.payload()

    def _apply_lifecycle(self, module_id: str, enabled: bool) -> None:
        callback = self._lifecycle
        if callback is None:
            return
        try:
            callback(module_id, enabled)
            with self._lock:
                self._status[module_id] = "running" if enabled else "disabled"
        except Exception as exc:  # optional modules must never stop the core
            with self._lock:
                self._status[module_id] = "error"
                self._errors[module_id] = str(exc)
