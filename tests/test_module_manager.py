import pytest

from core.module_manager import ModuleDependencyError, ModuleManager, ModuleManifest


def test_existing_installations_default_all_builtin_modules_to_enabled():
    manager = ModuleManager(lambda: {}, lambda _states: True)
    assert all(module["enabled"] for module in manager.payload()["modules"])


def test_module_state_is_persisted_and_lifecycle_is_stopped():
    saved = []
    module = ModuleManifest("seerr-sync", "Seerr", "", "", {})
    manager = ModuleManager(
        lambda: {},
        lambda states: saved.append(states) or True,
        (module,),
    )
    controller = _Controller()
    controller.running = True
    manager.register_controller("seerr-sync", controller)

    manager.set_enabled("seerr-sync", False)

    assert saved[-1]["seerr-sync"] is False
    assert controller.running is False
    module = next(item for item in manager.payload()["modules"] if item["id"] == "seerr-sync")
    assert module["status"] == "disabled"


class _Controller:
    def __init__(self, fail_stop=False, configured=True):
        self.running = False
        self.fail_stop = fail_stop
        self.configured = configured
        self.starts = 0
    def start(self):
        self.starts += 1
        self.running = True
    def stop(self):
        if self.fail_stop: return False
        self.running = False; return True
    def health(self): return self.running, "läuft" if self.running else "gestoppt"
    def configuration_state(self): return self.configured, "konfiguriert" if self.configured else "Token fehlt"


def _manager(*modules, states=None):
    saved=[]
    manager=ModuleManager(lambda: states or {}, lambda value: saved.append(value) or True, modules)
    for module in modules: manager.register_controller(module.id, _Controller())
    return manager, saved


def test_required_dependencies_enable_transitively_and_disable_only_with_cascade():
    base=ModuleManifest("base","Base","","",{})
    middle=ModuleManifest("middle","Middle","","",{},requires=("base",))
    leaf=ModuleManifest("leaf","Leaf","","",{},requires=("middle",))
    manager,_=_manager(base,middle,leaf,states={"base":False,"middle":False,"leaf":False})
    manager.set_enabled("leaf",True)
    assert {item["id"] for item in manager.payload()["modules"] if item["enabled"]} == {"base","middle","leaf"}
    with pytest.raises(ModuleDependencyError): manager.set_enabled("base",False)
    manager.set_enabled("base",False,cascade=True)
    assert not any(item["enabled"] for item in manager.payload()["modules"])


def test_conflicts_and_cycles_are_rejected():
    left=ModuleManifest("left","Left","","",{},conflicts=("right",))
    right=ModuleManifest("right","Right","","",{})
    manager,_=_manager(left,right,states={"left":True,"right":False})
    with pytest.raises(ModuleDependencyError): manager.set_enabled("right",True)
    with pytest.raises(ModuleDependencyError): ModuleManager(lambda:{},lambda _:True,(
        ModuleManifest("a","A","","",{},requires=("b",)), ModuleManifest("b","B","","",{},requires=("a",)),
    ))


def test_persist_failure_never_changes_runtime_or_intent():
    module=ModuleManifest("module","Module","","",{})
    controller=_Controller(); controller.running = True
    manager=ModuleManager(lambda:{"module":True},lambda _:False,(module,)); manager.register_controller("module",controller)
    with pytest.raises(RuntimeError): manager.set_enabled("module",False)
    assert manager.payload()["modules"][0]["enabled"] is True
    assert controller.running is True


def test_missing_configuration_is_not_reported_as_running():
    module = ModuleManifest("telegram", "Telegram", "", "", {})
    manager = ModuleManager(lambda: {"telegram": True}, lambda _: True, (module,))
    manager.register_controller("telegram", _Controller(configured=False))

    manager.start_enabled()

    status = manager.payload()["modules"][0]
    assert status["enabled"] is True
    assert status["configured"] is False
    assert status["runtime_status"] == "needs_configuration"
    assert status["health"] == "unavailable"


def test_repeated_start_does_not_start_an_healthy_module_twice():
    module = ModuleManifest("module", "Module", "", "", {})
    controller = _Controller()
    manager = ModuleManager(lambda: {"module": True}, lambda _: True, (module,))
    manager.register_controller("module", controller)

    manager.start_enabled()
    manager.start_enabled()

    assert controller.starts == 1


def test_core_manifest_cannot_be_disabled():
    core = ModuleManifest("core", "Core", "", "", {}, core=True)
    manager, _ = _manager(core, states={"core": True})

    with pytest.raises(ValueError, match="Core-Module"):
        manager.set_enabled("core", False)


def test_optional_dependency_is_a_visible_reduced_capability():
    optional = ModuleManifest("optional", "Optional", "", "", {})
    main = ModuleManifest(
        "main", "Main", "", "", {}, optional_requires=("optional",),
    )
    manager, _ = _manager(optional, main, states={"optional": False, "main": True})

    payload = {entry["id"]: entry for entry in manager.payload()["modules"]}
    assert payload["main"]["missing_optional"] == ["optional"]


def test_shutdown_keeps_persisted_intent_and_reports_a_worker_that_will_not_stop():
    module = ModuleManifest("module", "Module", "", "", {})
    controller = _Controller(fail_stop=True)
    controller.running = True
    manager = ModuleManager(lambda: {"module": True}, lambda _: True, (module,))
    manager.register_controller("module", controller)

    manager.stop_all()

    status = manager.payload()["modules"][0]
    assert status["enabled"] is True
    assert status["runtime_status"] == "stopping"
