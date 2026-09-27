"""Native ES-module graph and architectural dependency direction.

Includes static imports, re-exports and literal dynamic imports. Nonliteral
dynamic imports are disallowed so the graph remains statically verifiable.
"""
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1] / "web"
TOKENS = re.compile(
    r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'
    r"'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|[A-Za-z_$][\w$]*|[^\s]"
)


def module_imports(source):
    tokens = [t for t in TOKENS.findall(source) if not t.startswith(("//", "/*"))]
    targets = []
    for index, token in enumerate(tokens):
        if token not in ("import", "export"):
            continue
        if index and tokens[index - 1] == ".":
            continue
        rest = tokens[index + 1:]
        if not rest or rest[0] == ".":  # import.meta
            continue
        if token == "import" and rest[0] == "(":
            assert len(rest) > 2 and rest[1][0] in "\"'" and rest[2] == ")", (
                "Dynamic imports must have a literal module path"
            )
            targets.append(rest[1][1:-1])
        elif token == "import" and rest[0][0] in "\"'":
            targets.append(rest[0][1:-1])
        else:
            for offset, part in enumerate(rest):
                if part == ";":
                    break
                if part == "from" and offset + 1 < len(rest) and rest[offset + 1][0] in "\"'":
                    targets.append(rest[offset + 1][1:-1])
                    break
    return targets


def cycles(graph):
    visited, active, trail, found = set(), set(), [], []

    def visit(node):
        if node in active:
            found.append(trail[trail.index(node):] + [node])
            return
        if node in visited:
            return
        active.add(node)
        trail.append(node)
        for dependency in sorted(graph[node]):
            visit(dependency)
        trail.pop()
        active.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    return found


def layer_violations(graph):
    forbidden = {
        "core": {"shared", "features", "shell", "composition", "app.js"},
        "shared": {"features", "shell", "composition", "app.js"},
        "features": {"shell", "composition", "app.js"},
        "shell": {"composition", "app.js"},
    }
    return [
        (source, target)
        for source, targets in graph.items()
        for target in targets
        if target.split("/")[0] in forbidden.get(source.split("/")[0], set())
    ]


def frontend_graph():
    modules = list((ROOT / "js").rglob("*.js"))
    graph = {}
    for path in modules:
        targets = []
        for specifier in module_imports(path.read_text(encoding="utf-8")):
            assert specifier.startswith("."), (path, specifier)
            target = (path.parent / specifier).resolve()
            assert target in modules, (path, specifier)
            targets.append(target.relative_to(ROOT / "js").as_posix())
        graph[path.relative_to(ROOT / "js").as_posix()] = targets
    return graph


def test_import_inventory_covers_reexports_dynamic_and_side_effects():
    assert module_imports('''
        // import fake from './ignored.js';
        const example = "import './also-ignored.js'";
        import './side.js';
        import { name } from './normal.js';
        export { name } from './export.js';
        export * from './all.js';
        const lazy = import('./lazy.js');
        const location = import.meta.url;
    ''') == ['./side.js', './normal.js', './export.js', './all.js', './lazy.js']
    with pytest.raises(AssertionError, match="literal"):
        module_imports('import(moduleName);')


def test_cycle_detector_rejects_self_and_indirect_cycles():
    assert cycles({"a": ["b"], "b": ["c"], "c": []}) == []
    assert cycles({"a": ["b"], "b": ["c"], "c": ["a"]}) == [["a", "b", "c", "a"]]
    assert cycles({"a": ["a"]}) == [["a", "a"]]


@pytest.mark.parametrize("source,target", [
    ("core/api.js", "features/home/index.js"),
    ("core/store.js", "shell/actions.js"),
    ("core/store.js", "composition/index.js"),
    ("shared/components/card.js", "features/home/actions.js"),
    ("features/home/index.js", "composition/home.js"),
    ("features/home/index.js", "shell/actions.js"),
])
def test_layer_guard_detects_reverse_dependencies(source, target):
    assert layer_violations({source: [target], target: []}) == [(source, target)]


def test_frontend_import_graph_is_acyclic_and_obeys_layers():
    graph = frontend_graph()
    assert not cycles(graph), cycles(graph)
    assert not layer_violations(graph), layer_violations(graph)


def test_registry_cannot_return_and_root_only_composes_domains():
    for path in (ROOT / "js").rglob("*.js"):
        assert "sharedPresentation" not in path.read_text(encoding="utf-8"), path
    entry = ROOT / "js/composition/index.js"
    assert all(target.startswith("./") for target in module_imports(entry.read_text(encoding="utf-8")))
    assert not (ROOT / "js/composition.js").exists()
    assert not (ROOT / "js/shell/presentation.js").exists()
