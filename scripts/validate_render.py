"""Portable full offline render check; optional exact PNG comparison in a fixed environment."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops
from validation import load_catalogue

ROOT = Path(__file__).resolve().parents[1]


def compare(out: Path, exact_pixels: bool = False) -> None:
    ids = [m["id"] for m in load_catalogue(ROOT / "catalogue.yaml")["maps"]]
    expected = {
        f"wset-map-{i}{tag}.{ext}" for i in ids for tag in ("", "-blank") for ext in ("png", "svg")
    } | {"_contact_sheet.png"}
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
    if not args.compare_only:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/render_maps.py"), "--out", str(args.out)],
            cwd=ROOT,
            check=True,
        )
    compare(args.out, args.exact_pixels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
