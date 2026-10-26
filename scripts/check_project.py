"""Check catalogue, exact asset set, provenance and public-content boundaries."""
from pathlib import Path
import hashlib
import json
import tarfile
import yaml
from snapshots import prepare
ROOT = Path(__file__).resolve().parents[1]

def check(root=ROOT):
    spec = yaml.safe_load((root / "catalogue.yaml").read_text())
    ids = [m["id"] for m in spec["maps"]]
    assert len(ids) == len(set(ids)) == 32
    assert "new-zealand" not in ids
    assert all(not {"match", "match_in_chapters", "chapters"} & set(m) for m in spec["maps"])
    assert all(not str(r.get("gi", "")).startswith("nz/") for m in spec["maps"] for r in m["regions"])
    expected = {f"wset-map-{i}{tag}.{ext}" for i in ids for tag in ("", "-blank") for ext in ("svg", "png")} | {"_contact_sheet.png"}
    assets = json.loads((root / "data/asset-manifest.json").read_text())
    assert set(assets) == expected == {p.name for p in (root / "assets").iterdir()}
    for name, sha in assets.items():
        assert hashlib.sha256((root / "assets" / name).read_bytes()).hexdigest() == sha, name
    inputs = json.loads((root / "data/input-manifest.json").read_text())["inputs"]
    assert all(set(r["outputs"]) <= expected for r in inputs)
    for row in inputs:
        assert all(k in row for k in ("source_url", "source", "licence", "transformations", "sha256", "acquired_at"))
        assert "gi-nz-" not in row["path"]
    with tarfile.open(root / "data/map-inputs.tar.gz") as tar:
        assert all("gi-nz-" not in m.name and m.isfile() for m in tar.getmembers())
    # A curated allowlist also checks untracked files before publication reviews.
    roots = {".gitignore", "ATTRIBUTION.md", "LICENSE", "LICENSE-ARTWORK.md", "README.md", "catalogue.yaml", "pyproject.toml", "uv.lock"}
    for path in root.iterdir():
        if path.name in {".git", ".venv", ".cache", "work"}:
            continue
        assert path.name in roots | {"assets", "scripts", "tests", "data"}, path
        assert not path.is_symlink(), path
    allowed_data = {"asset-manifest.json", "input-manifest.json", "label-colours.json", "map-inputs.tar.gz", "upstream-archive-inventory.json"}
    assert {p.name for p in (root / "data").iterdir()} == allowed_data
    for directory in ("scripts", "tests"):
        for path in (root / directory).rglob("*"):
            if "__pycache__" in path.parts:
                continue
            assert path.suffix == ".py" and not path.is_symlink(), path
            if path.name == "check_project.py":
                continue  # This checker contains the forbidden-token definitions.
            content = path.read_text()
            assert all(token not in content for token in ("/Users/", "@gmail.com", "textbook/dist/", "source/course-materials/")), path
    prepare(root)
    print(f"PASS: {len(ids)} maps, {len(expected)-1} assets, contact sheet, {len(inputs)} licensed pinned inputs")

if __name__ == "__main__":
    check()
