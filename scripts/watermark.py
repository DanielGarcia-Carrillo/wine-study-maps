#!/usr/bin/env python3
"""Embed or find a keyed, invisible watermark in the rendered map PNGs.

The mark is a faint tile of band-pass noise, at most a couple of brightness
levels, repeated across the image. It is generated from a secret key, so the
method can be public: without the key the pattern cannot be found or removed.
Detection folds the image onto one tile and correlates it with the keyed
pattern, which survives JPEG, resizing and cropping.

The key is read from WSM_WATERMARK_KEY, or else from the macOS keychain item
named by KEYCHAIN_SERVICE. It is never stored in the repository.

    uv run --locked --group watermark python scripts/watermark.py embed assets/level-2-bordeaux.png
    uv run --locked --group watermark python scripts/watermark.py detect suspect.jpg
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

KEYCHAIN_SERVICE = "wine-study-maps-watermark"
TILE = 128  # pattern period in pixels
STRENGTH = 1.5  # peak-ish amplitude, in 0-255 brightness levels
THRESHOLD = 9.0  # detection score that counts as found; unmarked images score 4-5
SCALES = np.geomspace(0.4, 2.5, 200)  # resize factors searched when the size is unknown
REFINE = 4  # coarse candidates refined on the whole image


def find_key() -> str | None:
    if key := os.environ.get("WSM_WATERMARK_KEY"):
        return key
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def read_key() -> str:
    if key := find_key():
        return key
    sys.exit(f"no watermark key: set WSM_WATERMARK_KEY or add keychain item {KEYCHAIN_SERVICE}")


def blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur by FFT, wrapping at the edges."""
    fy = np.fft.fftfreq(a.shape[0])[:, None]
    fx = np.fft.fftfreq(a.shape[1])[None, :]
    g = np.exp(-2 * (np.pi * sigma) ** 2 * (fx**2 + fy**2))
    out: np.ndarray = np.real(np.fft.ifft2(np.fft.fft2(a) * g))
    return out


def band(a: np.ndarray) -> np.ndarray:
    # Mid frequencies: they outlast JPEG and resizing, and show less than fine grain.
    out: np.ndarray = blur(a, 1.0) - blur(a, 4.0)
    return out


def pattern(key: str) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
    t = band(np.random.default_rng(seed).standard_normal((TILE, TILE)))
    out: np.ndarray = t / t.std()
    return out


def embed(img: Image.Image, key: str) -> Image.Image:
    a = np.asarray(img.convert("RGB"), dtype=np.float64)
    h, w, _ = a.shape
    p = np.tile(pattern(key), (h // TILE + 1, w // TILE + 1))[:h, :w]
    out = np.clip(a + STRENGTH * p[..., None], 0, 255).round().astype(np.uint8)
    return Image.fromarray(out)


def mark_file(src: Path, key: str, dest: Path | None = None) -> None:
    with Image.open(src) as img:
        marked = embed(img, key)
    marked.save(dest or src, optimize=True)


def score(img: Image.Image, tile_fft: np.ndarray) -> float:
    g = np.asarray(img.convert("L"), dtype=np.float64)
    g = g - blur(g, 4.0)
    h, w = g.shape[0] // TILE * TILE, g.shape[1] // TILE * TILE
    if not h or not w:
        return 0.0
    folded = g[:h, :w].reshape(h // TILE, TILE, w // TILE, TILE).sum(axis=(0, 2))
    c = np.real(np.fft.ifft2(np.fft.fft2(folded) * np.conj(tile_fft)))
    return float((c.max() - c.mean()) / c.std())


def at_scale(img: Image.Image, s: float, tiles: int | None = None) -> Image.Image:
    """Undo a resize by factor s, optionally keeping only a central tiles x tiles block."""
    if tiles:
        side = min(round(tiles * TILE * s), img.width, img.height)
        x, y = (img.width - side) // 2, (img.height - side) // 2
        img = img.crop((x, y, x + side, y + side))
    size = (max(1, round(img.width / s)), max(1, round(img.height / s)))
    return img.resize(size, Image.Resampling.BICUBIC)


def detect(img: Image.Image, key: str, search: bool) -> tuple[float, float]:
    """Best score and the resize factor it was found at.

    Folding many tiles needs the scale almost exact, so the search runs coarse
    on a small central block, which tolerates a scale error, then refines the
    likeliest scales on the whole image.
    """
    tile_fft = np.fft.fft2(pattern(key))
    best = (score(img, tile_fft), 1.0)
    if search:
        img = img.convert("L")
        coarse = sorted(((score(at_scale(img, s, 3), tile_fft), s) for s in SCALES), reverse=True)
        for _, s0 in coarse[:REFINE]:
            for s in s0 * np.linspace(0.99, 1.01, 21):
                best = max(best, (score(at_scale(img, s), tile_fft), float(s)))
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("embed", help="watermark PNGs in place, or into --out")
    e.add_argument("images", nargs="+", type=Path)
    e.add_argument("--out", type=Path, help="directory for marked copies")
    d = sub.add_parser("detect", help="report whether each image carries the mark")
    d.add_argument("images", nargs="+", type=Path)
    d.add_argument("--no-search", action="store_true", help="assume the original size")
    args = ap.parse_args()
    key = read_key()

    for path in args.images:
        img = Image.open(path)
        if args.cmd == "embed":
            dest = args.out / path.name if args.out else path
            dest.parent.mkdir(parents=True, exist_ok=True)
            mark_file(path, key, dest)
            print(f"marked {dest}")
        else:
            s, scale = detect(img, key, search=not args.no_search)
            verdict = "found" if s >= THRESHOLD else "not found"
            print(f"{path}: {verdict} (score {s:.1f}, scale {scale:.2f})")


if __name__ == "__main__":
    main()
