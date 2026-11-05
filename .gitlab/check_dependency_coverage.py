"""Require generated scan input and SBOMs to cover the actual locked dependencies."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def name(value):
    return re.sub(r'[-_.]+', '-', value).lower()


def requirements(path):
    result, current = {}, None
    for line in path.read_text().splitlines():
        text = line.strip()
        if not text or text.startswith('#'):
            continue
        package = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s\\]+)\s*\\?', text)
        if package:
            current = name(package[1])
            if current in result:
                raise ValueError('Duplicate locked dependency: ' + current)
            result[current] = {'version': package[2], 'hashes': set()}
            continue
        digest = re.fullmatch(r'--hash=sha256:([0-9a-f]{64})\s*\\?', text)
        if digest and current:
            result[current]['hashes'].add(digest[1])
        else:
            raise ValueError('Unsupported requirement line in ' + str(path))
    if not result or any(not value['hashes'] for value in result.values()):
        raise ValueError('Every locked package needs content hashes')
    return result


def validate_input():
    original = requirements(ROOT / 'requirements-build.lock')
    generated = requirements(ROOT / '.gitlab/pipcompile.lock.txt')
    if original.keys() != generated.keys():
        raise ValueError('Generated scan lock changes the dependency inventory')
    for package, value in original.items():
        derived = generated[package]
        if value['version'] != derived['version'] or not value['hashes'] <= derived['hashes']:
            raise ValueError('Generated scan lock differs from locked package: ' + package)
    return {package: value['version'] for package, value in original.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-only', action='store_true')
    parser.add_argument('--sbom-dir', type=Path, default=ROOT / 'sca-artifacts')
    args = parser.parse_args()
    expected = {'pipcompile.lock.txt': validate_input()}
    art = ROOT / '.gitlab/art/pipcompile.lock.txt'
    if art.exists():
        expected['art/pipcompile.lock.txt'] = {p: v['version'] for p, v in requirements(art).items()}
    if args.input_only:
        print('Scan lock preserves all locked package versions and original artifact hashes')
        return
    for path in ROOT.rglob('packages.lock.json'):
        data = json.loads(path.read_text())
        packages = {}
        for framework in data['dependencies'].values():
            for package, value in framework.items():
                if 'resolved' in value:
                    key = name(package)
                    if key in packages and packages[key] != value['resolved']:
                        raise ValueError('Multiple versions need explicit framework-aware coverage')
                    packages[key] = value['resolved']
        expected[path.relative_to(ROOT).as_posix()] = packages
    observed = {}
    for path in args.sbom_dir.rglob('gl-sbom-*.cdx.json'):
        data = json.loads(path.read_text())
        properties = {p['name']: p['value'] for p in data.get('metadata', {}).get('properties', [])}
        source = properties.get('gitlab:dependency_scanning:input_file:path')
        if source in observed:
            raise ValueError('Ambiguous SBOM source: ' + source)
        observed[source] = {name(p['name']): p['version'] for p in data.get('components', [])}
    missing = {}
    for source, packages in expected.items():
        actual = observed.get(source, {})
        absent = {p: version for p, version in packages.items() if actual.get(p) != version}
        if source not in observed or absent:
            missing[source] = absent or {'sbom': 'missing'}
    result = dict(complete=not missing, locked_inputs={p: len(v) for p, v in expected.items()}, missing=missing)
    output = ROOT / 'out/dependency-coverage.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    if missing:
        raise SystemExit('Dependency scanning omitted locked packages or their SBOMs')


if __name__ == '__main__':
    main()
