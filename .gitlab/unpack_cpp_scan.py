"""Extract the bounded public-header artifact without requiring tar in the analyzer image."""
from pathlib import Path, PurePosixPath
import json
import shutil
import tarfile

base = Path('out').resolve()
if (base / 'cppscan').exists():
    raise SystemExit('Refusing to overlay an existing analysis directory')
with tarfile.open(base / 'cppscan.tar.gz', 'r:gz') as archive:
    entries = archive.getmembers()
    if sum(entry.size for entry in entries) > 512 * 2**20:
        raise SystemExit('Public header archive exceeds bound')
    for entry in entries:
        name = PurePosixPath(entry.name)
        if name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0] != 'cppscan':
            raise SystemExit('Invalid public header path')
        if not (entry.isfile() or entry.isdir()):
            raise SystemExit('Public header artifact must not contain links or special files')
        target = base.joinpath(*name.parts)
        if entry.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(entry) as source, target.open('xb') as stream:
                shutil.copyfileobj(source, stream)
database = base / 'cppscan/compile_commands.json'
rows = json.loads(database.read_text())
for row in rows:
    compiler = row['arguments'][0]
    if compiler not in ('clang', 'clang++') or not shutil.which(compiler):
        raise SystemExit('Expected the analyzer-provided Clang compiler')
    row['arguments'][0] = shutil.which(compiler)
database.write_text(json.dumps(rows, indent=2) + '\n')
print('Public compile database and header artifact extracted; analyzer compiler paths resolved')
