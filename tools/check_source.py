"""Parse public Python sources and reject game artifacts in the tracked source set."""
import ast
import hashlib
from pathlib import Path
from source_tree import source_files

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'.nsp', '.nsz', '.xci', '.xcz', '.nca', '.nso', '.keys', '.bfttf', '.webm'}


def main():
    names = source_files(ROOT)
    count = 0
    for name in filter(None, names):
        path = ROOT / name
        public_fixture = name == 'tests/fixtures/synthetic-av.webm' and hashlib.sha256(path.read_bytes()).hexdigest() == 'e53e3426e33fb645bab14be66e8430c3fba9ba2cb1c12f5ab8ae85c422eab30d'
        if (path.suffix.lower() in FORBIDDEN and not public_fixture) or Path(name).parts[0] in ('generated', 'extracted', 'data', 'Keys'):
            raise SystemExit('Private artifact in public source: ' + name)
        if path.is_symlink():
            raise SystemExit('Review source symlinks before sharing: ' + name)
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=name)
            count += 1
    print(f'{count} tracked Python files parsed; no private game artifacts')


if __name__ == '__main__':
    main()
