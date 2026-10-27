"""Portable full offline render check; optional exact PNG comparison in a fixed environment."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops
from validation import load_catalogue

ROOT = Path(__file__).resolve().parents[1]


def compare(out: Path, exact_pixels: bool = False) -> None:
    ids = [m["id"] for m in load_catalogue(ROOT / "catalogue.yaml")["maps"]]
    expected = {
        f"wset-map-{i}{tag}.{ext}" for i in ids for tag in ("", "-blank") for ext in ("png", "svg")
    } | {"_contact_sheet.png"}
    for generated in out.iterdir():
        if generated.is_symlink() or not generated.is_file():
            raise ValueError(f"{generated}: unsafe rendered output")
    actual = {p.name for p in out.iterdir()}
    if actual != expected:
        raise ValueError(
            f"{out}: rendered inventory differs: missing={expected - actual}, unexpected={actual - expected}"
        )
    for name in sorted(expected):
        canonical = ROOT / "assets" / name
        rendered = out / name
        if name.endswith(".svg"):
            if canonical.read_bytes() != rendered.read_bytes():
                raise ValueError(f"{rendered}: SVG differs from canonical image")
            continue
        with Image.open(canonical) as reference, Image.open(rendered) as image:
            image.load()
            if image.size != reference.size:
                raise ValueError(f"{rendered}: PNG dimensions differ")
            rgb = image.convert("RGB")
            if rgb.getcolors(maxcolors=1) is not None:
                raise ValueError(f"{rendered}: PNG contains a single flat colour")
            if exact_pixels:
                a, b = reference.convert("RGBA"), image.convert("RGBA")
                if ImageChops.difference(a, b).getbbox(alpha_only=False) is not None:
                    raise ValueError(f"{rendered}: PNG pixels differ in this environment")
                if canonical.read_bytes() != rendered.read_bytes():
                    raise ValueError(f"{rendered}: PNG bytes differ in this environment")
    print(
        f"PASS: {len(ids)} offline maps, exact SVGs, decoded PNGs and dimensions"
        + (", exact PNG bytes/pixels" if exact_pixels else "")
    )


class Arguments(argparse.Namespace):
    out: Path
    compare_only: bool
    exact_pixels: bool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "work/quality-render")
    parser.add_argument("--compare-only", action="store_true")
    parser.add_argument("--exact-pixels", action="store_true")
    args = parser.parse_args(namespace=Arguments())
    if args.compare_only:
        compare(args.out, args.exact_pixels)
        return 0
    # Never trust previous output as evidence that this invocation wrote a file.
    # No output directory is deleted, and no output symlink is followed.
    for ancestor in (args.out, *args.out.parents):
        if ancestor.is_symlink():
            raise ValueError(f"{ancestor}: output path must not contain a symlink")
    with tempfile.TemporaryDirectory(prefix="wine-study-maps-render-") as temporary:
        fresh = Path(temporary) / "rendered"
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/render_maps.py"), "--out", str(fresh)],
            cwd=ROOT,
            check=True,
        )
        if not fresh.is_dir() or fresh.is_symlink():
            raise ValueError(f"{fresh}: renderer did not create output")
        compare(fresh, args.exact_pixels)
        args.out.mkdir(parents=True, exist_ok=True)
        for image in fresh.iterdir():
            destination = args.out / image.name
            if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                raise ValueError(f"{destination}: unsafe existing output path")
        for image in fresh.iterdir():
            shutil.copyfile(image, args.out / image.name)
    compare(args.out, args.exact_pixels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
