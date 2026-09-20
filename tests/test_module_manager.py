from core.module_manager import ModuleManager


def test_existing_installations_default_all_builtin_modules_to_enabled():
    manager = ModuleManager(lambda: {}, lambda _states: True)
    assert all(module["enabled"] for module in manager.payload()["modules"])


def test_module_state_is_persisted_and_lifecycle_is_stopped():
    saved = []
    calls = []
    manager = ModuleManager(lambda: {}, lambda states: saved.append(states) or True)
    manager.set_lifecycle(lambda module_id, enabled: calls.append((module_id, enabled)))

    manager.set_enabled("seerr-sync", False)

    assert saved[-1]["seerr-sync"] is False
    assert calls == [("seerr-sync", False)]
    module = next(item for item in manager.payload()["modules"] if item["id"] == "seerr-sync")
    assert module["status"] == "disabled"
