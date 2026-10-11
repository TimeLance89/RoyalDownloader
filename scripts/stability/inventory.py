"""AST inventory of every backend module; risk seams are not confirmed bugs."""
import argparse
import ast
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folders = ['core', 'application_services', 'media', 'providers', 'storage', 'updates',
               'integrations', 'modules', 'api', 'features']
    paths = list(args.root.glob('*.py'))
    for folder in folders:
        paths.extend((args.root / folder).glob('*.py'))
    rows = []
    for path in sorted(paths):
        source = path.read_text()
        tree = ast.parse(source)
        seams = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if any(word in name for word in ('Thread', 'Executor', 'Lock', 'Semaphore',
                                                 'join', 'sleep', 'open', 'write', 'save')):
                    seams.append({'line': node.lineno, 'call': name,
                                  'timeout_keyword': any(k.arg == 'timeout' for k in node.keywords)})
        rows.append({'path': str(path.relative_to(args.root)), 'lines': len(source.splitlines()),
                     'functions': sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)),
                     'async_functions': sum(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree)),
                     'risk_seams': seams})
    result = {'files': len(rows), 'lines': sum(row['lines'] for row in rows), 'modules': rows}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'files': result['files'], 'lines': result['lines']}))


if __name__ == '__main__':
    main()
