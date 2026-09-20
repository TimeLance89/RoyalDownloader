"""Built-in module registry state, dependency graph, and worker lifecycle."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from threading import RLock
from typing import Callable, Protocol


RUNTIME_DISABLED = "disabled"
RUNTIME_STARTING = "starting"
RUNTIME_RUNNING = "running"
RUNTIME_STOPPING = "stopping"
RUNTIME_ERROR = "error"
RUNTIME_NEEDS_CONFIGURATION = "needs_configuration"
RUNTIME_DEPENDENCY_MISSING = "dependency_missing"

logger = logging.getLogger(__name__)


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


class ModuleController(Protocol):
    """Runtime boundary implemented by a module, never by the manager itself."""

    def start(self) -> None: ...

    def stop(self) -> bool: ...

    def health(self) -> tuple[bool, str]: ...

    def configuration_state(self) -> tuple[bool, str]: ...


class ModuleDependencyError(ValueError):
    def __init__(self, message: str, modules: list[str] | None = None):
        self.modules = modules or []
        super().__init__(message)


class ModuleManager:
    """Authoritative persisted intent and observable module runtime state.

    ``enabled`` is the user's persisted activation request. It is deliberately
    separate from configuration and runtime: an enabled module with missing
    credentials is ``needs_configuration`` rather than falsely ``running``.
    """

    def __init__(
        self,
        load: Callable[[], dict],
        save: Callable[[dict], bool],
        modules: tuple[ModuleManifest, ...] | None = None,
    ) -> None:
        if modules is None:
            from modules.registry import BUILTIN_MODULES

            modules = BUILTIN_MODULES
        self._load = load
        self._save = save
        self._lock = RLock()
        self._manifests = {item.id: item for item in modules}
        if len(self._manifests) != len(modules):
            raise ModuleDependencyError("Modul-IDs müssen eindeutig sein.")
        self._controllers: dict[str, ModuleController] = {}
        persisted = load() or {}
        # Missing keys preserve the first-release behaviour: all existing
        # integrations retain their previous enabled state after an upgrade.
        self._enabled = {
            module_id: bool(persisted.get(module_id, True))
            for module_id in self._manifests
        }
        self._runtime = {
            module_id: RUNTIME_DISABLED
            for module_id in self._manifests
        }
        self._errors: dict[str, str] = {}
        self._validate_graph()

    def register_controller(self, module_id: str, controller: ModuleController) -> None:
        if module_id not in self._manifests:
            raise KeyError(module_id)
        with self._lock:
            self._controllers[module_id] = controller

    def is_enabled(self, module_id: str) -> bool:
        with self._lock:
            if module_id not in self._manifests:
                raise KeyError(module_id)
            return self._enabled[module_id]

    def availability(self, module_id: str) -> tuple[bool, str]:
        """Whether an API may invoke this optional module right now."""
        with self._lock:
            if module_id not in self._manifests:
                raise KeyError(module_id)
            if not self._enabled[module_id]:
                return False, "Dieses optionale Modul ist deaktiviert."
            blocked = self._runtime_blocker(module_id)
            if blocked:
                return False, blocked
            configured, detail = self._configuration(module_id)
            if not configured:
                self._runtime[module_id] = RUNTIME_NEEDS_CONFIGURATION
                return False, detail
            healthy, detail = self._health(module_id)
            if not healthy:
                self._runtime[module_id] = RUNTIME_ERROR
                self._errors[module_id] = detail
                return False, detail
            if self._runtime[module_id] != RUNTIME_RUNNING:
                return False, self._errors.get(
                    module_id,
                    f"Modul ist derzeit {self._runtime[module_id]}.",
                )
            return True, "Modul läuft."

    def _validate_graph(self) -> None:
        module_ids = set(self._manifests)
        for item in self._manifests.values():
            unknown = set(
                item.requires + item.optional_requires + item.conflicts,
            ) - module_ids
            if unknown:
                raise ModuleDependencyError(
                    f"{item.id}: unbekannte Module {sorted(unknown)}",
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(module_id: str) -> None:
            if module_id in visiting:
                raise ModuleDependencyError(
                    f"Abhängigkeitszyklus bei {module_id}",
                )
            if module_id in visited:
                return
            visiting.add(module_id)
            for dependency in self._manifests[module_id].requires:
                visit(dependency)
            visiting.remove(module_id)
            visited.add(module_id)

        for module_id in self._manifests:
            visit(module_id)

    def _required_closure(self, module_id: str) -> set[str]:
        result: set[str] = set()

        def visit(current: str) -> None:
            for dependency in self._manifests[current].requires:
                if dependency not in result:
                    result.add(dependency)
                    visit(dependency)

        visit(module_id)
        return result

    def _active_dependents(self, module_id: str) -> set[str]:
        """All transitively active modules which require ``module_id``."""
        result: set[str] = set()

        def visit(target: str) -> None:
            for item in self._manifests.values():
                if (
                    item.id not in result
                    and self._enabled[item.id]
                    and target in item.requires
                ):
                    result.add(item.id)
                    visit(item.id)

        visit(module_id)
        return result

    def _ordered(self, module_ids: set[str], *, start: bool) -> list[str]:
        return sorted(
            module_ids,
            key=lambda module_id: len(self._required_closure(module_id)),
            reverse=not start,
        )

    def _configuration(self, module_id: str) -> tuple[bool, str]:
        controller = self._controllers.get(module_id)
        if controller is None:
            return False, "Lifecycle noch nicht registriert"
        try:
            return controller.configuration_state()
        except Exception as exc:
            return False, f"Konfigurationsprüfung fehlgeschlagen: {exc}"

    def _health(self, module_id: str) -> tuple[bool, str]:
        controller = self._controllers.get(module_id)
        if controller is None:
            return False, "Lifecycle noch nicht registriert"
        try:
            return controller.health()
        except Exception as exc:
            return False, f"Health-Prüfung fehlgeschlagen: {exc}"

    def _runtime_blocker(self, module_id: str) -> str:
        missing = [
            dependency
            for dependency in self._manifests[module_id].requires
            if not self._enabled[dependency]
        ]
        if missing:
            return f"Benötigte Module sind deaktiviert: {', '.join(sorted(missing))}"
        conflicts = [
            other
            for other, manifest in self._manifests.items()
            if other != module_id
            and self._enabled[other]
            and (
                other in self._manifests[module_id].conflicts
                or module_id in manifest.conflicts
            )
        ]
        if conflicts:
            return f"Konflikt mit aktivem Modul: {', '.join(sorted(conflicts))}"
        return ""

    def _normalized_startup_state(self) -> tuple[dict[str, bool], dict[str, str]]:
        """Repair old persisted states deterministically before workers start."""
        proposed = dict(self._enabled)
        notes: dict[str, str] = {}
        for module_id in self._manifests:
            if proposed[module_id]:
                for dependency in self._required_closure(module_id):
                    if not proposed[dependency]:
                        proposed[dependency] = True
                        notes[dependency] = (
                            f"Beim Start für abhängiges Modul {module_id} aktiviert"
                        )
        active: list[str] = []
        for module_id, manifest in self._manifests.items():
            if not proposed[module_id]:
                continue
            conflict = next((
                other for other in active
                if other in manifest.conflicts
                or module_id in self._manifests[other].conflicts
            ), None)
            if conflict:
                proposed[module_id] = False
                notes[module_id] = (
                    f"Beim Start wegen Konflikt mit {conflict} deaktiviert"
                )
            else:
                active.append(module_id)
        return proposed, notes

    def _apply_startup_normalization(self) -> None:
        proposed, notes = self._normalized_startup_state()
        if proposed == self._enabled:
            return
        if self._save(proposed):
            self._enabled = proposed
            self._errors.update(notes)
            logger.warning("Ungültige persistierte Modulzustände wurden normalisiert")
            return
        # Never run an invalid old graph when its correction cannot be durable.
        for module_id, detail in notes.items():
            self._errors[module_id] = f"{detail}; Persistenzkorrektur fehlgeschlagen"

    def _start(self, module_id: str) -> bool:
        controller = self._controllers.get(module_id)
        if controller is None:
            self._runtime[module_id] = RUNTIME_ERROR
            self._errors[module_id] = "Lifecycle noch nicht registriert"
            return False

        if self._runtime[module_id] == RUNTIME_RUNNING:
            healthy, _detail = self._health(module_id)
            if healthy:
                return True

        configured, detail = self._configuration(module_id)
        if not configured:
            self._runtime[module_id] = RUNTIME_NEEDS_CONFIGURATION
            self._errors.pop(module_id, None)
            logger.info("Modul %s wartet auf Konfiguration: %s", module_id, detail)
            return False

        self._runtime[module_id] = RUNTIME_STARTING
        logger.info("Modul %s startet", module_id)
        try:
            controller.start()
            healthy, detail = self._health(module_id)
        except Exception as exc:  # Module must not abort core startup.
            self._runtime[module_id] = RUNTIME_ERROR
            self._errors[module_id] = str(exc)
            logger.warning("Modul %s konnte nicht starten: %s", module_id, exc)
            return False

        if healthy:
            self._runtime[module_id] = RUNTIME_RUNNING
            self._errors.pop(module_id, None)
            logger.info("Modul %s läuft", module_id)
            return True

        self._runtime[module_id] = RUNTIME_ERROR
        self._errors[module_id] = detail
        logger.warning("Modul %s ist nicht betriebsbereit: %s", module_id, detail)
        return False

    def _stop(self, module_id: str) -> bool:
        controller = self._controllers.get(module_id)
        if controller is None:
            self._runtime[module_id] = RUNTIME_DISABLED
            self._errors.pop(module_id, None)
            return True

        self._runtime[module_id] = RUNTIME_STOPPING
        logger.info("Modul %s wird beendet", module_id)
        try:
            stopped = controller.stop()
        except Exception as exc:
            self._runtime[module_id] = RUNTIME_ERROR
            self._errors[module_id] = str(exc)
            logger.warning("Modul %s konnte nicht beendet werden: %s", module_id, exc)
            return False

        if stopped:
            self._runtime[module_id] = RUNTIME_DISABLED
            self._errors.pop(module_id, None)
            logger.info("Modul %s ist beendet", module_id)
            return True

        self._runtime[module_id] = RUNTIME_STOPPING
        self._errors[module_id] = "Worker beendet sich noch"
        logger.warning("Modul %s beendet sich noch", module_id)
        return False

    def _reconcile_one(self, module_id: str) -> None:
        """Make one module's desired state match its real worker state."""
        if not self._enabled[module_id]:
            if self._runtime[module_id] != RUNTIME_DISABLED:
                self._stop(module_id)
            return

        blocker = self._runtime_blocker(module_id)
        if blocker:
            if self._runtime[module_id] in {RUNTIME_RUNNING, RUNTIME_STOPPING}:
                self._stop(module_id)
            if self._runtime[module_id] != RUNTIME_STOPPING:
                self._runtime[module_id] = RUNTIME_DEPENDENCY_MISSING
                self._errors[module_id] = blocker
            return

        configured, detail = self._configuration(module_id)
        if not configured:
            if self._runtime[module_id] in {RUNTIME_RUNNING, RUNTIME_STOPPING}:
                self._stop(module_id)
            if self._runtime[module_id] != RUNTIME_STOPPING:
                self._runtime[module_id] = RUNTIME_NEEDS_CONFIGURATION
                self._errors.pop(module_id, None)
            return

        # A timed-out stop owns the worker until it really terminates. Once it
        # has terminated, restart exactly one worker if the old enabled intent
        # still applies (for example a rejected disable followed by re-enable).
        if self._runtime[module_id] == RUNTIME_STOPPING:
            if not self._stop(module_id):
                return

        healthy, detail = self._health(module_id)
        if self._runtime[module_id] == RUNTIME_RUNNING and healthy:
            return
        if self._runtime[module_id] == RUNTIME_RUNNING and not healthy:
            self._runtime[module_id] = RUNTIME_ERROR
            self._errors[module_id] = detail
        self._start(module_id)

    def reconcile(self, module_id: str | None = None) -> dict:
        """Re-evaluate configuration, graph constraints, health and workers.

        Configuration endpoints call this immediately. The server additionally
        runs ``reconcile_all`` periodically so an unexpectedly dead worker can
        never remain reported as running indefinitely.
        """
        with self._lock:
            if module_id is not None and module_id not in self._manifests:
                raise KeyError(module_id)
            if module_id is None:
                self._apply_startup_normalization()
                module_ids = self._ordered(set(self._manifests), start=True)
            else:
                module_ids = [module_id]
            for current in module_ids:
                self._reconcile_one(current)
            return self.payload()

    reconcile_all = reconcile

    def _restore_runtime(self, old_enabled: dict[str, bool], changed: set[str]) -> None:
        """Restore workers that did stop; never lie about one still stopping."""
        for module_id in self._ordered(changed, start=False):
            if not old_enabled[module_id]:
                self._stop(module_id)
        for module_id in self._ordered(changed, start=True):
            if (
                old_enabled[module_id]
                and self._runtime[module_id] != RUNTIME_STOPPING
            ):
                self._start(module_id)

    def _validate_conflicts(self, proposed: dict[str, bool], changes: set[str]) -> None:
        conflicts = {
            other
            for module_id in changes
            for other, manifest in self._manifests.items()
            if other != module_id
            and proposed[other]
            and (
                other in self._manifests[module_id].conflicts
                or module_id in manifest.conflicts
            )
        }
        if conflicts:
            raise ModuleDependencyError(
                f"Konflikt mit aktivem Modul: {', '.join(sorted(conflicts))}",
                sorted(conflicts),
            )

    def payload(self) -> dict:
        with self._lock:
            modules = []
            for item in self._manifests.values():
                configured, configuration_detail = self._configuration(item.id)
                healthy, health_detail = self._health(item.id)
                if self._runtime[item.id] == RUNTIME_RUNNING and not healthy:
                    self._runtime[item.id] = (
                        RUNTIME_NEEDS_CONFIGURATION
                        if not configured else RUNTIME_ERROR
                    )
                    if configured:
                        self._errors[item.id] = health_detail
                modules.append({
                    **asdict(item),
                    "enabled": self._enabled[item.id],
                    "runtime_status": self._runtime[item.id],
                    "status": self._runtime[item.id],  # Legacy API alias.
                    "configured": configured,
                    "configuration_detail": configuration_detail,
                    "health": "healthy" if healthy else "unavailable",
                    "health_detail": health_detail,
                    "error": self._errors.get(item.id, ""),
                    "used_by": sorted(self._active_dependents(item.id)),
                    "missing_optional": [
                        dependency
                        for dependency in item.optional_requires
                        if not self._enabled[dependency]
                    ],
                })
            return {
                "modules": modules,
                "presets": {
                    "minimal": [],
                    "standard": list(self._manifests),
                    "custom": [
                        module_id
                        for module_id, enabled in self._enabled.items()
                        if enabled
                    ],
                },
            }

    def start_enabled(self) -> None:
        self.reconcile_all()

    def stop_all(self) -> None:
        """Shutdown-only; persisted enablement remains unchanged for restart."""
        with self._lock:
            for module_id in self._ordered(
                {key for key, enabled in self._enabled.items() if enabled},
                start=False,
            ):
                self._stop(module_id)

    def set_enabled(
        self,
        module_id: str,
        enabled: bool,
        cascade: bool = False,
    ) -> dict:
        with self._lock:
            if module_id not in self._manifests:
                raise KeyError(module_id)
            if self._manifests[module_id].core and not enabled:
                raise ValueError("Core-Module können nicht deaktiviert werden.")

            dependents = self._active_dependents(module_id) if not enabled else set()
            if dependents and not cascade:
                raise ModuleDependencyError(
                    "Dieses Modul wird verwendet von: "
                    f"{', '.join(sorted(dependents))}",
                    sorted(dependents),
                )

            changed = (
                {module_id, *dependents}
                if not enabled
                else {module_id, *self._required_closure(module_id)}
            )
            old_enabled = dict(self._enabled)
            proposed = dict(old_enabled)
            proposed.update({key: enabled for key in changed})
            if enabled:
                self._validate_conflicts(proposed, changed)

            # Stop failures never reach persistence: a module that still owns a
            # worker remains enabled in both RAM and settings.ini.
            if not enabled:
                stopped = {
                    key: self._stop(key)
                    for key in self._ordered(changed, start=False)
                }
                if not all(stopped.values()):
                    # Do not restart the worker whose stop signal is still in
                    # flight. It remains ``stopping`` and reconciliation will
                    # restart it only after the old thread has actually ended.
                    self._restore_runtime(old_enabled, changed)
                    raise RuntimeError(
                        "Modul konnte nicht vollständig beendet werden; "
                        "Änderung wurde zurückgenommen.",
                    )
            else:
                # A failed start is an observable error state, not a failed
                # preference write. It is retried after reconfiguration/restart.
                for key in self._ordered(changed, start=True):
                    self._start(key)

            if not self._save(proposed):
                self._restore_runtime(old_enabled, changed)
                raise RuntimeError("Modulkonfiguration konnte nicht gespeichert werden.")

            self._enabled = proposed
            return self.payload()
