"""Validate individually tracked map-ready inputs and materialise a derived cache."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(value, prefix):
    if not isinstance(value, str) or '\\' in value:
        raise ValueError(f'Unsafe source path: {value!r}')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in prefix or str(path) != value:
        raise ValueError(f'Unsafe source path: {value!r}')
    return Path(path)


def prepare(root=ROOT):
    manifest = json.loads((root / 'data/input-manifest.json').read_text())
    inputs = root / 'data/inputs'
    if (root / 'data').is_symlink() or inputs.is_symlink() or not inputs.is_dir():
        raise ValueError('Missing or unsafe committed input directory: data/inputs')
    expected = {}
    cache_paths = set()
    for row in manifest['inputs']:
        path = safe_path(row['path'], {'inputs'})
        target = safe_path(row['cache_path'], {'.naturalearth-cache', '.wikidata-cache', '.inao-cache'})
        if str(path) in expected or str(target) in cache_paths:
            raise ValueError(f'Duplicate input or cache path: {path}')
        expected[str(path)] = row
        cache_paths.add(str(target))
    # Always inspect committed files, even when a complete old cache exists.
    actual = set()
    allowed_dirs = {p for name in expected for p in (root / 'data' / name).parents if p != root}
    for path in inputs.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'Unsafe source path (symlink): {path}')
        if path.is_dir() and path not in allowed_dirs:
            raise ValueError(f'Unexpected source directory: {path}')
        if path.is_file():
            actual.add(str(path.relative_to(root / 'data')))
    if actual != set(expected):
        raise FileNotFoundError(f'Committed source inventory differs: missing={sorted(set(expected)-actual)}, unexpected={sorted(actual-set(expected))}')
    for name, row in expected.items():
        path = root / 'data' / name
        if path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
            raise ValueError(f'Source checksum mismatch: {name}')
    cache = root / '.cache'
    if cache.is_symlink():
        raise ValueError('Unsafe cache directory: .cache')
    for old in cache.rglob('*'):
        if old.is_symlink():
            raise ValueError(f'Unsafe cache path (symlink): {old}')
        if old.is_file() and str(old.relative_to(cache)) not in cache_paths:
            old.unlink()
    for name, row in expected.items():
        dest = cache / row['cache_path']
        for ancestor in (dest, *dest.parents):
            if ancestor == root:
                break
            if ancestor.is_symlink():
                raise ValueError(f'Unsafe cache path (symlink): {ancestor}')
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_file() or digest(dest) != row['sha256']:
            shutil.copyfile(root / 'data' / name, dest)
    return cache
