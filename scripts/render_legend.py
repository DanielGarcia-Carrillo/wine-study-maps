#!/usr/bin/env python3
"""Render the one shared map legend to docs/legend.svg and docs/legend.png.

The maps carry no legend of their own; README.md links this one. It is drawn
from the renderer's own constants, so it cannot drift from the maps.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_maps import (  # noqa: E402
    CITY,
    CITY_PX,
    COUNTRY,
    COUNTRY_PX,
    FOCUS,
    FOCUS_WASH,
    HUES,
    INK,
    LAND,
    NESTED,
    TIER,
    esc,
    load_cairosvg,
    readable,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs"
W, ROW, SW = 640, 64, 92  # canvas width, row height, swatch width


def border(colour: str) -> str:
    return f'stroke="{readable(colour, LAND)}" stroke-width="2" stroke-opacity="0.85"'


def swatches() -> list[tuple[str, str]]:
    a, b = HUES[0], HUES[1]
    area = TIER[1][1]
    return [
        (
            f'<rect x="4" y="8" width="84" height="44" fill="{FOCUS}" '
            f'fill-opacity="{FOCUS_WASH}" {border(FOCUS)}/>',
            "The region the map is about: a grey border over a light grey wash",
        ),
        (
            f'<rect x="4" y="8" width="84" height="44" fill="{a}" fill-opacity="{area}" {border(a)}/>',
            "A wine region, each in its own colour",
        ),
        (
            f'<rect x="4" y="8" width="84" height="44" fill="{a}" fill-opacity="{area}" {border(a)}/>'
            f'<rect x="18" y="16" width="56" height="28" fill="{a}" '
            f'fill-opacity="{NESTED[0]}" {border(a)}/>'
            f'<rect x="34" y="23" width="24" height="14" fill="{a}" '
            f'fill-opacity="{NESTED[1]}" {border(a)}/>',
            "An area inside another: a darker tone of its parent, darker again a level deeper",
        ),
        (
            f'<defs><pattern id="legend-stripes" patternUnits="userSpaceOnUse" width="8" '
            f'height="8" patternTransform="rotate(45)">'
            f'<rect width="4" height="8" fill="{a}" fill-opacity="{area}"/>'
            f'<rect x="4" width="4" height="8" fill="{b}" fill-opacity="{area}"/>'
            f"</pattern></defs>"
            f'<rect x="4" y="8" width="54" height="44" fill="{a}" fill-opacity="{area}"/>'
            f'<rect x="34" y="8" width="54" height="44" fill="{b}" fill-opacity="{area}"/>'
            f'<rect x="34" y="8" width="24" height="44" fill="{LAND}"/>'
            f'<rect x="34" y="8" width="24" height="44" fill="url(#legend-stripes)"/>'
            f'<rect x="4" y="8" width="54" height="44" fill="none" {border(a)}/>'
            f'<rect x="34" y="8" width="54" height="44" fill="none" {border(b)}/>',
            "Two areas that overlap without either containing the other: stripes of both",
        ),
        (
            f'<rect x="4" y="8" width="42" height="44" fill="{a}" fill-opacity="{area}" {border(a)}/>'
            f'<rect x="46" y="8" width="42" height="44" fill="{b}" fill-opacity="{area}" {border(b)}/>'
            f'<rect x="26" y="18" width="20" height="24" fill="{a}" fill-opacity="{NESTED[0]}"/>'
            f'<rect x="46" y="18" width="20" height="24" fill="{b}" fill-opacity="{NESTED[0]}"/>'
            f'<rect x="26" y="18" width="40" height="24" fill="none" {border(FOCUS)}/>',
            "An area across two others (Los Carneros): each side in that parent's tone",
        ),
        (
            f'<circle cx="46" cy="30" r="20" fill="{a}" fill-opacity="{area}" '
            f'stroke="{a}" stroke-width="1" stroke-opacity="0.5"/>'
            f'<circle cx="46" cy="30" r="3.4" fill="{readable(a, LAND)}" stroke="#fff" '
            f'stroke-width="1.4"/>',
            "A region with no mapped boundary: its position and rough size only",
        ),
        (
            f'<circle cx="16" cy="30" r="2.4" fill="{CITY}"/>'
            f'<text x="24" y="{30 + CITY_PX / 3:.1f}" class="city">City</text>',
            "A city in the map's own country, for orientation",
        ),
        (
            f'<text x="46" y="{30 + COUNTRY_PX / 3:.1f}" class="country" '
            f'text-anchor="middle">SPAIN</text>',
            "A neighbouring country, named in place of its cities",
        ),
    ]


def legend() -> str:
    rows = swatches()
    height = 56 + ROW * len(rows) + 8
    body = "\n".join(
        f'<g transform="translate(24 {56 + i * ROW})">{swatch}'
        f'<text x="{SW + 16}" y="{30 + 5}" class="label">{esc(text)}</text></g>'
        for i, (swatch, text) in enumerate(rows)
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}">
<style>
  text {{ font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }}
  .ti {{ font-size: 22px; font-weight: 700; fill: {INK}; }}
  .label {{ font-size: 14px; fill: {INK}; }}
  .city {{ font-size: {CITY_PX}px; fill: {CITY}; }}
  .country {{ font-size: {COUNTRY_PX}px; font-weight: 600; letter-spacing: 2px; fill: {COUNTRY}; }}
</style>
<rect width="100%" height="100%" fill="{LAND}"/>
<text x="24" y="36" class="ti">Map legend</text>
{body}
</svg>
'''


def main() -> int:
    OUT.mkdir(exist_ok=True)
    svg = legend()
    (OUT / "legend.svg").write_text(svg, encoding="utf-8")
    cairosvg = load_cairosvg()
    if cairosvg is None:
        raise RuntimeError("PNG output requires CairoSVG and native Cairo")
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(OUT / "legend.png"), output_width=W * 2)
    print(f"  {OUT.name}/legend.svg, {OUT.name}/legend.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
