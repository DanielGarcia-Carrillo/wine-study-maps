"""Validate and materialise the checked-in, offline map-ready source snapshot."""
from pathlib import Path
import hashlib
import json
import tarfile

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def prepare(root=ROOT):
    manifest = json.loads((root / 'data/input-manifest.json').read_text())
    archive = root / 'data/map-inputs.tar.gz'
    if digest(archive) != manifest['archive_sha256']:
        raise ValueError('Source archive checksum mismatch')
    cache = root / '.cache'
    expected = {r['path']: r for r in manifest['inputs']}
    if not cache.exists():
        # Extract only explicitly listed regular files, never links or paths.
        with tarfile.open(archive, 'r:gz') as tar:
            members = tar.getmembers()
            if len(members) != len(expected) or {m.name for m in members} != set(expected):
                raise ValueError('Source archive contents differ from manifest')
            for member in members:
                path = Path(member.name)
                if not member.isfile() or path.is_absolute() or '..' in path.parts:
                    raise ValueError(f'Unsafe source archive member: {member.name}')
                blob = tar.extractfile(member).read()
                if hashlib.sha256(blob).hexdigest() != expected[member.name]['sha256']:
                    raise ValueError(f'Source checksum mismatch: {member.name}')
                dest = cache / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob)
    for name, row in expected.items():
        path = cache / name
        if not path.is_file():
            raise FileNotFoundError(f'Missing pinned source input: {name}; remove .cache to restore the archive')
        if digest(path) != row['sha256']:
            raise ValueError(f'Source checksum mismatch: {name}')
    return cache
