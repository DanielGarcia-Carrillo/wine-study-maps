"""Validate project contracts, exact assets, provenance and committed source inputs."""

from __future__ import annotations

from pathlib import Path

from snapshots import digest, prepare
from validation import (
    ASSETS,
    COLOURS,
    UPSTREAM,
    fail,
    load_catalogue,
    load_manifest,
    read_json,
    safe_relative,
    validate_input,
)

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check(root: Path = ROOT) -> None:
    spec = load_catalogue(root / "catalogue.yaml")
    ids = [m["id"] for m in spec["maps"]]
    require(
        len(ids) == 32 and "new-zealand" not in ids,
        "catalogue.yaml:$.maps: expected 32 public maps",
    )
    require(
        all(not str(r.get("gi", "")).startswith("nz/") for m in spec["maps"] for r in m["regions"]),
        "catalogue.yaml:$.maps: unsupported public GI source",
    )
    expected = {
        f"wset-map-{i}{tag}.{ext}" for i in ids for tag in ("", "-blank") for ext in ("svg", "png")
    } | {"_contact_sheet.png"}
    assets = read_json(root / "data/asset-manifest.json", ASSETS)
    require(
        set(assets) == expected == {p.name for p in (root / "assets").iterdir()},
        "assets/: inventory differs from catalogue/manifest",
    )
    for name, sha in assets.items():
        path = root / "assets" / safe_relative(name, "asset-manifest.json", name)
        require(
            not path.is_symlink() and digest(path) == sha,
            f"{path}:$.: asset checksum mismatch or unsafe path",
        )
    colours = read_json(root / "data/label-colours.json", COLOURS)
    require(bool(colours), "label-colours.json:$: empty reviewed colour table")
    upstream = read_json(root / "data/upstream-archive-inventory.json", UPSTREAM)
    for i, upstream_row in enumerate(upstream):
        path = safe_relative(
            upstream_row["filename"], "upstream-archive-inventory.json", f"$[{i}].filename"
        )
        require(
            len(path.parts) == 1,
            f"upstream-archive-inventory.json:$[{i}].filename: expected basename",
        )
    manifest = load_manifest(root)
    require(len(manifest["inputs"]) == 147, "input-manifest.json:$.inputs: expected 147 inputs")
    for i, row in enumerate(manifest["inputs"]):
        if not set(row["outputs"]) <= expected:
            fail("input-manifest.json", f"$.inputs[{i}].outputs", "unknown output reference")
        require("gi-nz-" not in row["path"], f"{row['path']}: unsupported public input")
    # Validate integrity before interpreting provider input structures.
    prepare(root)
    for row in manifest["inputs"]:
        validate_input(root / "data" / row["path"], row)
    roots = {
        ".gitignore",
        "ATTRIBUTION.md",
        "LICENSE",
        "LICENSE-ARTWORK.md",
        "README.md",
        "catalogue.yaml",
        "pyproject.toml",
        "uv.lock",
        "assets",
        "scripts",
        "tests",
        "data",
        "typings",
        ".github",
    }
    for path in root.iterdir():
        if path.name in {
            ".git",
            ".venv",
            ".cache",
            ".maintenance-cache",
            ".mypy_cache",
            ".ruff_cache",
            "work",
        }:
            continue
        require(
            path.name in roots and not path.is_symlink(),
            f"Unexpected/unsafe public root path: {path}",
        )
    allowed_data = {
        "asset-manifest.json",
        "input-manifest.json",
        "label-colours.json",
        "inputs",
        "upstream-archive-inventory.json",
    }
    require({p.name for p in (root / "data").iterdir()} == allowed_data, "Unexpected data path")
    for directory in ("scripts", "tests", "typings"):
        for path in (root / directory).rglob("*"):
            if "__pycache__" in path.parts:
                continue
            require(
                path.is_file() and path.suffix in (".py", ".pyi") and not path.is_symlink(),
                f"Unexpected public code path: {path}",
            )
            if path.name == "check_project.py":
                continue  # The checker itself defines the forbidden-token list.
            content = path.read_text()
            require(
                all(
                    token not in content
                    for token in (
                        "/Users/",
                        "@gmail.com",
                        "textbook/dist/",
                        "source/course-materials/",
                    )
                ),
                f"Unexpected private content: {path}",
            )
    workflow_files = {"workflows/quality.yml"}
    actual_workflow_files: set[str] = set()
    for path in (root / ".github").rglob("*"):
        require(not path.is_symlink(), f"Unsafe workflow path: {path}")
        if path.is_file():
            actual_workflow_files.add(str(path.relative_to(root / ".github")))
            require(
                all(
                    token not in path.read_text()
                    for token in (
                        "/Users/",
                        "@gmail.com",
                        "textbook/dist/",
                        "source/course-materials/",
                    )
                ),
                f"Unexpected private workflow content: {path}",
            )
        else:
            require(path.name == "workflows", f"Unexpected workflow directory: {path}")
    require(actual_workflow_files == workflow_files, "Unexpected workflow inventory")
    print(
        f"PASS: {len(ids)} maps, {len(expected) - 1} assets, contact sheet, {len(manifest['inputs'])} structurally validated pinned inputs"
    )


if __name__ == "__main__":
    check()
