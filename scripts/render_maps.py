#!/usr/bin/env python3
"""Render the standalone map catalogue. See README.md for offline build commands."""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path
from typing import Protocol, cast

from models import (
    LEVEL,
    Area,
    BBox,
    Entities,
    FeatureCollection,
    Geometry,
    MapSpec,
    Mark,
    Palette,
    Point,
    Ring,
    Rings,
)
from validation import COLOURS, load_catalogue, load_manifest, read_json

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "assets"
SPEC = ROOT / "catalogue.yaml"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_geodata import area_of, fetch_entities, load_layer  # noqa: E402

W, H = 1000, 750  # px, before bbox aspect correction
PAD = 34  # px of margin inside the frame
# km radius, scaled to bbox. `broad` is for a marker standing for a whole
# part of a country - "south-west France" - where even `large` would claim a
# single appellation's worth of ground.
HALO = {"small": 3.5, "medium": 7.0, "large": 12.0, "broad": 60.0}

# Muted map colours separate land, water, borders and labels.
INK = "#2b2b33"
SEA = "#dbe7ef"
LAND = "#f6f3ec"
COAST = "#9db4c4"
RIVER = "#6f9fc0"
CITY = "#6f6f79"
BORDER = "#857e74"
# Hues for maps whose regions are peers rather than nested - a country and
# its regions. Muted hues keep neighbouring regions visually distinct.
HUES = [
    "#7a1f2b",
    "#2f7d8c",
    "#a8661f",
    "#5f8a34",
    "#7d4a86",
    "#3c6aa5",
    "#b5654f",
    "#8a7c2f",
    "#bf5f88",
    "#2f6d6a",
]

# Label sizes are canvas pixels. At about half the 1000px canvas width,
# region labels display at roughly 9-11px; heavier weights aid readability.
TIER = {
    0: ("#7a1f2b", 0.20, 21.0, 700),
    1: ("#7a1f2b", 0.17, 20.0, 700),
    2: ("#b5654f", 0.15, 18.0, 600),
}
# Cities are context rather than content, so they stay a step below the
# smallest region label. CITY_EM is the average glyph width, for the boxes
# that keep labels off each other.
CITY_PX = 14
CITY_EM = 0.59 * CITY_PX

# Sources whose licences require attribution are credited on every map they
# feed, so a single image reused on its own keeps its credit. Public-domain
# and CC0 sources are credited in ATTRIBUTION.md only. The credit is drawn
# last, on a pale panel in the bottom-right corner, so it reads over sea or
# land; labels are not placed around it, so check new maps for overlaps.
CREDITS = {
    "INAO and IGN/Etalab": "INAO, IGN/Etalab (Licence Ouverte 2.0, {version})",
    "OpenStreetMap contributors": "© OpenStreetMap contributors (ODbL)",
    "Regione Piemonte": "Regione Piemonte (CC BY 4.0)",
    "Wine Australia": "Wine Australia (CC BY 4.0)",
}
# Credit text is sized against the full canvas width, so every PNG, which is
# rendered at one fixed width, shows it at the same size however narrow the map.
CREDIT_PX = 12


def credit_lines(root: Path = ROOT) -> dict[str, str]:
    """The credit line for each output file, from the input manifest."""
    found: dict[str, set[str]] = {}
    for row in load_manifest(root)["inputs"]:
        if (text := CREDITS.get(row["source"])) is None:
            continue
        text = text.format(version=row["version"] or "undated")
        for out in row["outputs"]:
            found.setdefault(out, set()).add(text)
    return {out: "Data: " + "; ".join(sorted(texts)) for out, texts in found.items()}


# Reviewed label colours are explicit palette values.
# Extend data/label-colours.json after reviewing readability.
def readable(hex_colour: str, bg: str, target: float = 75.0) -> str:
    colours = read_json(ROOT / "data/label-colours.json", COLOURS)
    key = f"{hex_colour}|{bg}|{target:g}"
    if key not in colours:
        raise ValueError(
            f"Unreviewed label colour {key}; add an explicit reviewed colour to data/label-colours.json"
        )
    return colours[key]


def tint(hex_colour: str, amount: float) -> str:
    """Mix a colour towards white, for the lighter sub-region tier.

    A sub-region drawn in a different hue from its parent reads as unrelated;
    drawn as a tint of the same hue it reads as part of it, which is the point
    of nesting Margaux inside Haut-Medoc inside Medoc.
    """
    h = hex_colour.lstrip("#")
    rgb = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return "#" + "".join(f"{round(c + (255 - c) * amount):02x}" for c in rgb)


def same_name(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Projection:
    """Equirectangular, x scaled by cos(mid-latitude).

    At the scale of one wine region this is indistinguishable from anything
    fancier, and unlike Mercator it does not stretch the map vertically.
    """

    def __init__(self, bbox: BBox, canvas: tuple[float, float] = (W, H), pad: float = PAD) -> None:
        self.w, self.s, self.e, self.n = bbox
        self.pad = pad
        self.k = math.cos(math.radians((self.s + self.n) / 2))
        span_x = (self.e - self.w) * self.k
        span_y = self.n - self.s
        # Fit the bbox into the frame without distorting it.
        scale = min((canvas[0] - 2 * pad) / span_x, (canvas[1] - 2 * pad) / span_y)
        self.width = span_x * scale + 2 * pad
        self.height = span_y * scale + 2 * pad
        self.scale = scale
        # Chosen from how much ground the frame covers, not how big it is in
        # pixels: the constraint is how many labels a reader can take in.
        span = max(span_x, span_y)
        self.place_rank = 4 if span > 18 else 5 if span > 9 else 6 if span > 3.5 else 7

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        return (
            self.pad + (lon - self.w) * self.k * self.scale,
            self.pad + (self.n - lat) * self.scale,
        )

    def km(self, km: float) -> float:
        """Convert a ground distance to pixels, for halo radii."""
        return km / 111.0 * self.scale

    def inside(self, lon: float, lat: float, slack: float = 0.0) -> bool:
        return self.w - slack <= lon <= self.e + slack and self.s - slack <= lat <= self.n + slack


def centroid(rings: Rings) -> tuple[float, float]:
    """Area-weighted centroid of a set of rings, for labelling a sourced area."""
    tx = ty = ta = 0.0
    for ring in rings:
        a = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1], strict=True):
            cross = x0 * y1 - x1 * y0
            a += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        if a:
            tx += cx / 3
            ty += cy / 3
            ta += a
    if not ta:
        pts = [pt for ring in rings for pt in ring]
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    return (tx / ta, ty / ta)


def dissolve(area_rings: Rings) -> Rings:
    """The outer boundary of a union of rings, as polylines, without a geometry library.

    An appellation is a union of communes, and filled without strokes they
    read as one shape - but a *boundary* cannot be drawn that way: stroking
    every commune draws every internal border too. The commune boundaries
    from geo.api.gouv.fr are topologically clean - two neighbouring communes
    share their common border vertex for vertex - so an edge that belongs to
    two rings is internal and cancels, and the edges left over are exactly
    the outline of the union. (Checked on the Côte de Nuits: 705 of 1,713
    edges are shared, and every one of them exactly twice.)

    A single ring - an AVA, a county - comes back as itself.
    """
    count: dict[tuple[Point, Point], int] = {}
    for ring in area_rings:
        pts = [cast(Point, tuple(pt)) for pt in ring]
        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        for a, b in zip(pts, pts[1:], strict=False):
            if a != b:
                key = (a, b) if a < b else (b, a)
                count[key] = count.get(key, 0) + 1
    adj: dict[Point, list[Point]] = {}
    for (a, b), n in count.items():
        if n % 2:  # internal edges pair off and cancel
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
    lines = []
    while adj:
        start = next(iter(adj))
        line, cur = [start], start
        while adj.get(cur):
            nxt = adj[cur].pop()
            adj[nxt].remove(cur)
            if not adj[cur]:
                del adj[cur]
            if not adj[nxt]:
                del adj[nxt]
            line.append(nxt)
            cur = nxt
        if len(line) > 1:
            lines.append(line)
    return lines


def rings(geom: Geometry | None) -> Rings:
    if geom is None:
        return []
    """Flatten any GeoJSON geometry to a list of coordinate rings."""
    if geom["type"] == "Point":
        return [[geom["coordinates"]]]
    if geom["type"] == "LineString" or geom["type"] == "MultiPoint":
        return [geom["coordinates"]]
    if geom["type"] == "Polygon" or geom["type"] == "MultiLineString":
        return geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        return [ring for poly in geom["coordinates"] for ring in poly]
    return []


def path_of(ring: Ring, p: Projection, tol: float = 0.7) -> str:
    """Project a ring, dropping vertices closer together than `tol` pixels.

    Champagne's area is 635 communes and Touraine's is 143, each carrying
    boundary detail surveyed for cadastral use. At 1000px wide that detail is
    far below one pixel, so keeping it only inflates the SVG - 22 MB across
    the set before this, and no visible difference after.
    """
    out: list[str] = []
    lx: float | None = None
    ly = 0.0
    for lon, lat in ring:
        x, y = p(lon, lat)
        if lx is None or abs(x - lx) > tol or abs(y - ly) > tol:
            out.append(f"{x:.1f},{y:.1f}")
            lx, ly = x, y
    if len(out) < 3:  # too small to be worth drawing
        return ""
    return "M" + "L".join(out)


def land_paths(p: Projection) -> list[str]:
    """The land polygons, as bare path data, for use as a clip path.

    Commune and appellation boundaries follow the middle of a river or run out
    into an estuary, so an unclipped fill bleeds over the water - most visibly
    across the Gironde, which is the one piece of geography a Bordeaux map
    must get right.
    """
    out = []
    for f in load_layer("land")["features"]:
        for ring in rings(f["geometry"]):
            if any(p.inside(lon, lat, 1.5) for lon, lat in ring):
                d = path_of(ring, p)
                if d:
                    out.append(d + "Z")
    return out


def place_box(
    lon: float, lat: float, name: str, p: Projection
) -> tuple[float, float, float, float]:
    """The label box draw_layer() gives a city - dot, name and the flip."""
    x, y = p(lon, lat)
    w = CITY_EM * len(name)
    flip = x + 6 + w > p.width - 4
    x0 = x - 6 - w if flip else x + 6
    return (min(x0, x) - 2, y - CITY_PX / 2 - 1, max(x0 + w, x) + 2, y + CITY_PX / 2 + 2)


def crowded_places(data: FeatureCollection, p: Projection) -> set[int]:
    """Cities whose labels would collide with a more prominent city's.

    Twin cities print on top of each other - Vancouver WA over Portland,
    Tijuana over San Diego - so the less prominent of a colliding pair (by
    Natural Earth's SCALERANK) is left out. Decided in rank order but applied
    in file order, so a map with no collisions draws exactly as it did.

    Opt-in per map (`thin_places: true`): removing contextual city labels
    can improve readability, but each map needs visual review.
    """
    cand = []
    for f in data["features"]:
        props, geom = f.get("properties", {}), f.get("geometry")
        if not geom or geom["type"] != "Point":
            continue
        if (props.get("SCALERANK") or 99) > p.place_rank:
            continue
        lon, lat = geom["coordinates"][:2]
        if p.inside(lon, lat):
            cand.append(
                (
                    props.get("SCALERANK") or 99,
                    f,
                    place_box(lon, lat, esc(props.get("NAME") or ""), p),
                )
            )
    kept: list[tuple[float, float, float, float]] = []
    hidden: set[int] = set()
    for _, f, b in sorted(cand, key=lambda c: c[0]):
        if any(not (b[2] < t[0] or b[0] > t[2] or b[3] < t[1] or b[1] > t[3]) for t in kept):
            hidden.add(id(f))
        else:
            kept.append(b)
    return hidden


def draw_layer(
    name: str,
    p: Projection,
    boxes: list[tuple[float, float, float, float]] | None = None,
    thin: bool = False,
) -> str:
    """Clip a Natural Earth layer to the bbox, then project what survives."""
    data = load_layer("land" if name == "land" else name)
    out: list[str] = []
    hidden = crowded_places(data, p) if name == "places" and thin else set()
    for f in data["features"]:
        props, geom = f.get("properties", {}), f.get("geometry")
        if not geom:
            continue
        for ring in rings(geom):
            # Cheap clip: keep any ring with a vertex near the frame.
            if not any(p.inside(lon, lat, 1.5) for lon, lat in ring):
                continue
            # Places are single points, so they must be handled before
            # path_of() - which discards rings of fewer than three vertices.
            if name == "places":
                # Natural Earth ranks places by prominence. A tight frame can
                # afford small towns; a continent cannot - Australia drew every
                # town in the country and the labels became a grey smear.
                if (props.get("SCALERANK") or 99) > p.place_rank:
                    continue
                lon, lat = ring[0]
                if not p.inside(lon, lat) or id(f) in hidden:
                    continue  # the 1.5 deg slack above is for polygons
                x, y = p(lon, lat)
                nm = esc(props.get("NAME") or "")
                # Flip the label to the left of its dot when it would other-
                # wise run off the edge and be rendered as "Saarbruec".
                flip = x + 6 + CITY_EM * len(nm) > p.width - 4
                tx, anchor = (x - 6, "end") if flip else (x + 6, "start")
                common = (
                    f'x="{tx:.1f}" y="{y + CITY_PX / 3:.1f}" class="city" text-anchor="{anchor}"'
                )
                # Grouped and keyed by its index in `boxes`, so render() can
                # drop a city whose name a region label ends up sitting on.
                k = len(boxes) if boxes is not None else -1
                out.append(
                    f'<g data-city="{k}">'
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4" fill="{CITY}"/>'
                    f'<text {common} fill="none" stroke="{LAND}" stroke-width="3.6" '
                    f'stroke-linejoin="round">{nm}</text>'
                    f"<text {common}>{nm}</text></g>"
                )
                if boxes is not None:
                    w = CITY_EM * len(nm)
                    x0 = tx - w if flip else tx
                    boxes.append((x0 - 2, y - CITY_PX / 2 - 1, x0 + w + 2, y + CITY_PX / 2 + 2))
                continue

            d = path_of(ring, p)
            if not d:
                continue
            if name == "land":
                out.append(f'<path d="{d}Z" fill="{LAND}"/>')
            elif name == "coastline":
                out.append(f'<path d="{d}" fill="none" stroke="{COAST}" stroke-width="1.1"/>')
            elif name == "lakes":
                out.append(f'<path d="{d}Z" fill="{SEA}" stroke="{COAST}" stroke-width="0.7"/>')
            elif name == "borders":
                out.append(
                    f'<path d="{d}" fill="none" stroke="{BORDER}" '
                    f'stroke-width="1.2" stroke-dasharray="5 3" opacity="0.9"/>'
                )
            elif name == "rivers":
                out.append(
                    f'<path d="{d}" fill="none" stroke="{RIVER}" '
                    f'stroke-width="1.5" stroke-linecap="round" opacity="0.85"/>'
                )
    return "\n".join(out)


def column_labels(
    marks: list[Mark], outlines: list[list[tuple[float, float]]], width: float
) -> list[tuple[float, float, float, float]]:
    """Labels given a side by `label: e|w` in catalogue.yaml, stacked in order.

    The free search in place_labels() sends a crowded label wherever there is
    room, which on the Côte d'Or was 150px west of Puligny-Montrachet with a
    leader line across the map - and, worse, it does not keep order, so the
    names of four villages 10px apart came out shuffled against their dots.
    Here each side's labels are sorted north to south and relaxed apart just
    enough not to overlap, so the column reads in the same order as the
    villages and every leader stays short.

    Each label is also kept clear of every drawn outline at its own height
    (`outlines` is their projected points), so a village's name sits outside
    the Côte de Beaune rather than over its border, and Hermitage's outside
    the Crozes-Hermitage that surrounds it. A region drawn without a dot is
    labelled the same way - beside the outline it names.
    """
    boxes = []
    for side in (1, -1):
        col = sorted(
            (m for m in marks if {"e": 1, "w": -1}[cast(str, m["side"])] == side),
            key=lambda m: m["y"],
        )
        if not col:
            continue
        hs = [m["size"] + 6 for m in col]
        ys = [m["y"] for m in col]
        for _ in range(200):
            moved = False
            for i in range(1, len(col)):
                need = (hs[i - 1] + hs[i]) / 2 + 1
                if ys[i] - ys[i - 1] < need - 1e-6:
                    d = (need - (ys[i] - ys[i - 1])) / 2
                    ys[i - 1] -= d
                    ys[i] += d
                    moved = True
            if not moved:
                break
        for m, y, h in zip(col, ys, hs, strict=True):
            w = 0.55 * m["size"] * len(m["name"]) + 10
            xs = [m["x"] + side * (m["r"] + 9)] if m["dot"] else []
            xs += [px + side * 8 for pts in outlines for px, py in pts if abs(py - y) <= h / 2 + 4]
            x0 = (max(xs) if side > 0 else min(xs)) if xs else m["x"]
            # Never off the canvas: better over the map than cut in half.
            cx = min(max(x0 + side * w / 2, w / 2 + 2), width - w / 2 - 2)
            m["lx"], m["ly"] = cx, y
            boxes.append((cx - w / 2, y - h / 2, cx + w / 2, y + h / 2))
    return boxes


def place_labels(
    marks: list[Mark],
    p: Projection,
    taken: list[tuple[float, float, float, float]] | None = None,
    obstacles: list[list[tuple[float, float]]] | None = None,
) -> None:
    """Greedy label placement: try eight offsets, take the first that is clear.

    The Cote d'Or is the stress case - a dozen villages strung down 40km of
    escarpment, all wanting the same patch of canvas.
    """
    taken = list(taken or [])
    ncity = len(taken)  # the boxes passed in are city labels
    outlines = [
        [p(*pt) for line in dissolve(cast(Area, m["area"])["rings"]) for pt in line]
        for m in marks
        if m.get("outline") and m.get("area")
    ]
    taken += column_labels(
        [m for m in marks if m.get("side") in ("e", "w")], outlines + (obstacles or []), p.width
    )
    offsets = [(1, 0), (-1, 0), (1, -1), (-1, -1), (1, 1), (-1, 1), (0, -1), (0, 1)]
    for m in sorted(
        (m for m in marks if m.get("side") not in ("e", "w")), key=lambda m: -m["size"]
    ):
        w = 0.55 * m["size"] * len(m["name"]) + 10
        h = m["size"] + 6
        # A region drawn without a dot is an area label: try its own centre
        # first, so the name sits inside the shape it names.
        cands = [] if m.get("dot", True) else [(m["x"], m["y"])]
        if m.get("side") in ("s", "n"):
            # `label: s|n` - straight below or above the region's own shape,
            # into open ground (Montalcino's label had gone east across
            # Chianti).
            ys = (
                [p(*pt)[1] for ring in cast(Area, m["area"])["rings"] for pt in ring]
                if m.get("area")
                else [m["y"]]
            )
            if m["side"] == "s":
                cands += [(m["x"], max(ys) + h / 2 + gap) for gap in (6, 20, 40)]
            else:
                cands += [(m["x"], min(ys) - h / 2 - gap) for gap in (6, 20, 40)]
        for ox, oy in offsets:
            # Widely spaced rings of candidate positions: a tight cluster of
            # appellations - Barolo, Barbaresco and Asti sit within a few km
            # of each other - needs somewhere further out to put its labels.
            for dist in (
                m["r"] + 9,
                m["r"] + 26,
                m["r"] + 46,
                m["r"] + 72,
                m["r"] + 104,
                m["r"] + 140,
            ):
                cands.append(
                    (
                        m["x"] + ox * dist + (w / 2 if ox > 0 else -w / 2 if ox < 0 else 0),
                        m["y"] + oy * dist,
                    )
                )
        best = None
        for i, (cx, cy) in enumerate(cands):
            box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if box[0] < 2 or box[2] > p.width - 2 or box[1] < 2 or box[3] > p.height - 2:
                continue
            # A hand-placed, dotless label is where it was put: only other
            # region labels move it, and cities under it give way afterwards
            # (New South Wales had been pushed off its own state by Dubbo).
            fixed = i == 0 and not m.get("dot", True) and m.get("anchored")
            if any(
                not (box[2] < t[0] or box[0] > t[2] or box[3] < t[1] or box[1] > t[3])
                for t in (taken[ncity:] if fixed else taken)
            ):
                continue
            best = (cx, cy, box)
            break
        if best is None:  # nowhere clear; stack it anyway
            best = (
                m["x"],
                m["y"] - m["r"] - 12,
                (m["x"] - w / 2, m["y"] - m["r"] - 20, m["x"] + w / 2, m["y"] - m["r"] - 4),
            )
        m["lx"], m["ly"], _ = best
        taken.append(best[2])


def main_rings(rings: Rings, share: float = 0.05, far: float = 5.0) -> Rings:
    """Rings that should decide a map's frame, dropping distant minor ones.

    An administrative region can own territory thousands of kilometres from
    the part anyone means by the name. Natural Earth's Western Cape includes
    the Prince Edward Islands, 1,500km out in the Southern Ocean, which
    stretched the South Africa map to 24 degrees across and pushed the wine
    lands into a corner. Such outliers are both tiny and remote, so requiring
    a ring to be one or the other keeps genuine multi-part regions - like
    Champagne's detached Cote des Bar - intact.

    Only the frame is affected; every ring is still drawn.
    """
    if len(rings) < 2:
        return rings
    total = sum(len(r) for r in rings)
    main = max(rings, key=len)
    cx = sum(p[0] for p in main) / len(main)
    cy = sum(p[1] for p in main) / len(main)
    keep = []
    for r in rings:
        rx = sum(p[0] for p in r) / len(r)
        ry = sum(p[1] for p in r) / len(r)
        remote = abs(rx - cx) > far or abs(ry - cy) > far
        minor = len(r) / total < share
        if not (remote and minor):
            keep.append(r)
    return keep or rings


def auto_bbox(spec_map: MapSpec, ents: Entities) -> BBox:
    """Fit the frame to the regions actually drawn.

    Every hand-typed bbox is a number that can be wrong, and a wrong one
    silently crops a region out of its own map. Deriving it from the sourced
    geometry means the frame cannot disagree with the content.
    """
    # A single-region map fitted tightly to that one region shows the region
    # and nothing else, which is useless for placing it: Champagne looked the
    # same as Provence. `pad:` buys back the surrounding coastline, borders
    # and cities that make a region locatable.
    pad = float(spec_map.get("pad", 0.12))
    pts: list[tuple[float, float]] = []
    halo = 0.0
    # `fit: false` marks a context region - California on the Oregon map -
    # that is drawn where the frame reaches but does not decide the frame.
    for r in (r for r in spec_map["regions"] if r.get("fit", True)):
        area = area_of(r)
        if area:
            pts += [cast(Point, tuple(pt)) for ring in main_rings(area["rings"]) for pt in ring]
        elif ent := ents.get(r.get("wikidata", "")):
            # A marked region has no extent of its own, but its halo does, so
            # the halo has to be inside the frame we fit. Without this a map
            # whose regions are ALL marks - Portugal, Hungary - fits a frame
            # smaller than the halo and renders as a solid block of colour.
            d = HALO.get(r.get("extent", "small"), 5.0) / 111.0
            halo = max(halo, d)
            pts += [(ent["lon"] - d, ent["lat"] - d), (ent["lon"] + d, ent["lat"] + d)]
    if not pts:
        raise ValueError(f"{spec_map['id']}: nothing to fit a bbox to")
    w, e = min(p[0] for p in pts), max(p[0] for p in pts)
    s_, n = min(p[1] for p in pts), max(p[1] for p in pts)
    mx, my = max((e - w) * pad, 0.05), max((n - s_) * pad, 0.05)
    w, s_, e, n = w - mx, s_ - my, e + mx, n + my

    # Keep the largest halo to a fraction of the frame, so a marked region
    # reads as a location on a map rather than as the map itself. This is also
    # what gives a one-region country its surrounding context for free.
    # `min_span:` widens the frame to a stated number of degrees, for maps
    # where fitting the regions says nothing useful - a lone mark on the Douro
    # is not a map of Portugal until you can see Portugal.
    floor = max(halo * 10, float(spec_map.get("min_span", 0)))
    if floor and (e - w) < floor:
        cx = (w + e) / 2
        w, e = cx - floor / 2, cx + floor / 2
    if floor and (n - s_) < floor:
        cy = (s_ + n) / 2
        s_, n = cy - floor / 2, cy + floor / 2

    # `min_aspect:` widens a tall, thin frame to at least this width/height
    # ratio. A region strung along a river - the Rhône, the Côte d'Or - fits
    # a frame a third as wide as it is tall, which leaves no room beside the
    # vineyards for their names. Up to the canvas's own 4:3 the extra width
    # costs nothing: the frame is height-bound, so the scale does not change.
    aspect = float(spec_map.get("min_aspect", 0))
    k = math.cos(math.radians((s_ + n) / 2))
    if aspect and (e - w) * k < aspect * (n - s_):
        # `align:` is the share of the added width that goes to the west, for
        # a frame that wants its spare room on one side - the Hermitage panel
        # stacks its names to the west of the hill. 0.5 centres.
        extra = aspect * (n - s_) / k - (e - w)
        west = float(spec_map.get("align", 0.5))
        w, e = w - extra * west, e + extra * (1 - west)
    return [w, s_, e, n]


def render(
    spec_map: MapSpec,
    ents: Entities,
    treatment: str,
    blank: bool = False,
    palette: Palette | None = None,
    canvas: tuple[float, float] | None = None,
    clip_id: str = "land",
    credit: str = "",
) -> str:
    palette = palette or {}
    bbox = spec_map.get("bbox")
    bbox = auto_bbox(spec_map, ents) if bbox in (None, "auto") else cast(BBox, bbox)
    p = Projection(bbox, canvas, pad=10) if canvas else Projection(bbox)
    # City labels are drawn first, so region labels must be placed around
    # them - otherwise "Bordeaux" the region lands on top of Bordeaux the city.
    city_boxes: list[tuple[float, float, float, float]] = []
    layers = "\n".join(
        draw_layer(n, p, city_boxes, bool(spec_map.get("thin_places")))
        for n in spec_map.get("base", [])
    )

    # `inset:` - a zoomed panel of a few of this map's regions, for nesting
    # too small to see at the scale of the whole map. Crozes-Hermitage wraps
    # round Hermitage over about 15km, a few pixels on a map of the whole
    # Rhône. The panel is the same renderer on a smaller canvas, fitted to
    # just those regions; on the main map they keep their shapes and dots,
    # a box marks the panel's extent, and their names move into the panel.
    inset_svg, inset_names = "", set()
    obstacles: list[list[tuple[float, float]]] = []
    if (ins := spec_map.get("inset")) and not canvas:
        inset_names = set(ins["regions"])
        sub: MapSpec = {
            "id": spec_map["id"],
            "title": ins.get("title", ""),
            "base": ins.get("base", spec_map.get("base", [])),
            "pad": ins.get("pad", 0.12),
            "min_aspect": ins.get("min_aspect", 0),
            "align": ins.get("align", 0.5),
            "regions": [r for r in spec_map["regions"] if r["name"] in inset_names],
        }
        ip_bbox = auto_bbox(sub, ents)
        sub["bbox"] = ip_bbox
        cw, ch = ins.get("size", [240, 220])
        ip = Projection(ip_bbox, (cw, ch), pad=10)
        ix = min(ins["at"][0] * p.width, p.width - ip.width - 6)
        iy = min(ins["at"][1] * p.height, p.height - ip.height - 6)
        inner = render(
            sub,
            ents,
            treatment,
            blank=blank,
            palette=palette,
            canvas=(cw, ch),
            clip_id="inset-land",
        )
        inner = inner.split(">", 1)[1].rsplit("</svg>", 1)[0]
        # The extent box on the main map, and a connector to the panel.
        (x0, y0), (x1, y1) = p(ip_bbox[0], ip_bbox[3]), p(ip_bbox[2], ip_bbox[1])
        px, py = ix + ip.width / 2, iy + ip.height / 2
        ex = min(max(px, x0), x1)
        ey = min(max(py, y0), y1)
        cx = min(max(ex, ix), ix + ip.width)
        cy = min(max(ey, iy), iy + ip.height)
        inset_svg = "\n" + (
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" '
            f'fill="none" stroke="{INK}" stroke-width="1" stroke-opacity="0.7"/>\n'
            f'<line x1="{ex:.1f}" y1="{ey:.1f}" x2="{cx:.1f}" y2="{cy:.1f}" '
            f'stroke="{INK}" stroke-width="0.9" stroke-opacity="0.55"/>\n'
            f'<svg x="{ix:.1f}" y="{iy:.1f}" width="{ip.width:.0f}" height="{ip.height:.0f}" '
            f'viewBox="0 0 {ip.width:.0f} {ip.height:.0f}">{inner}</svg>\n'
            f'<rect x="{ix:.1f}" y="{iy:.1f}" width="{ip.width:.1f}" height="{ip.height:.1f}" '
            f'fill="none" stroke="{INK}" stroke-width="1.2"/>'
        )
        city_boxes.append((ix - 4, iy - 4, ix + ip.width + 4, iy + ip.height + 4))
        # Labels stay off the extent box as they do off an outline.
        steps = range(0, 101, 4)
        obstacles.append(
            [(x0 + (x1 - x0) * t / 100, yy) for t in steps for yy in (y0, y1)]
            + [(xx, y0 + (y1 - y0) * t / 100) for t in steps for xx in (x0, x1)]
        )

    # On a map of peers, give each region its own hue; a sub-region takes a
    # tint of whichever region it names as its parent, so Barossa still reads
    # as part of South Australia.
    hues: dict[str, str] = {}
    if spec_map.get("distinct"):
        peers = [r for r in spec_map["regions"] if r.get("tier", 1) <= 1]
        for i, r in enumerate(peers):
            hues[r["name"]] = r.get("colour", HUES[i % len(HUES)])

    marks: list[Mark] = []
    for r in spec_map["regions"]:
        area = area_of(r)
        ent = ents.get(r.get("wikidata", ""))
        if area and r.get("anchor"):
            # A hand-chosen anchor, for an area whose centroid falls inside a
            # different region - Crozes-Hermitage's lands in Hermitage, which
            # it surrounds. source_geodata.py checks it lies in its own area.
            lon, lat = r["anchor"]
        elif area:
            # Anchor on the centroid of the shape actually drawn, so the label
            # and its leader line point at the region rather than at a village
            # somewhere near its edge. Wikidata's point, where there is one,
            # is kept as an independent cross-check in source_geodata.py.
            lon, lat = centroid(area["rings"])
        elif ent:
            lon, lat = ent["lon"], ent["lat"]
        else:
            continue
        x, y = p(lon, lat)
        colour, alpha, size, weight = TIER[r.get("tier", 1)]
        # Resolve the hue from the shared palette so the France overview and
        # this region's own map always agree. Explicit colour: wins; then the
        # palette entry for the map this region summarises; then the palette
        # entry for the map being drawn; then the default claret ramp.
        base = (
            (palette.get(r["region_of"]) if r.get("region_of") else None)
            or hues.get(r["name"])
            or (hues.get(r["parent"]) if r.get("parent") else None)
            or palette.get(spec_map["id"])
        )
        if base:
            colour = tint(base, 0.30) if r.get("tier", 1) >= 2 else base
        colour = r.get("colour", colour)
        radius = p.km(HALO.get(r.get("extent", "small"), 5.0))
        # A region the map is titled after is already named by the title, so
        # it keeps its fill but loses its dot and label. Blank maps have no
        # title, so they keep the dot.
        titled = not blank and same_name(r["name"], spec_map.get("title", ""))
        labelled = r.get("named", True) and not titled
        marks.append(
            {
                "name": r["name"],
                "x": x,
                "y": y,
                "r": max(radius, 4.0),
                "colour": colour,
                "ink": readable(colour, LAND),
                "alpha": alpha,
                "size": size,
                "weight": weight,
                "area": area,
                "fill": r.get("fill", True),
                "dot": r.get("dot", True) and labelled,
                "outline": r.get("outline", False),
                "side": r.get("label"),
                "tier": r.get("tier", 1),
                "anchored": bool(r.get("anchor")),
                "named": labelled and r["name"] not in inset_names,
            }
        )

    fills: list[str] = []
    lines: list[str] = []
    body: list[str] = []
    for m in marks:
        if treatment == "c" and m["area"]:
            # Every commune in the appellation, drawn filled and unstroked so
            # they read as one shape - no geometry library needed to dissolve
            # them, and no invented outline either.
            if m["fill"]:
                d = "".join(path_of(ring, p) + "Z" for ring in m["area"]["rings"])
                fills.append(
                    f'<path d="{d}" fill="{m["colour"]}" fill-opacity="{m["alpha"]}" '
                    f'fill-rule="nonzero" stroke="none"/>'
                )
            if m["outline"]:
                # The union's own boundary (see dissolve()), for a region whose
                # extent matters as much as its position: the Côte de Nuits
                # around its villages, Crozes-Hermitage around Hermitage. A
                # fill alone cannot show that - two overlapping tints of one
                # hue read as one shape.
                d = "".join(path_of(line, p, tol=0.5) for line in dissolve(m["area"]["rings"]))
                width = 2.0 if m["tier"] <= 1 else 1.3
                dash = ' stroke-dasharray="6 3"' if m["outline"] == "dashed" else ""
                lines.append(
                    f'<path d="{d}" fill="none" stroke="{m["ink"]}" '
                    f'stroke-width="{width}" stroke-opacity="0.85"{dash} '
                    f'stroke-linejoin="round" stroke-linecap="round"/>'
                )
        elif treatment == "b" or (treatment == "c" and not m["area"]):
            fills.append(
                f'<circle cx="{m["x"]:.1f}" cy="{m["y"]:.1f}" r="{m["r"]:.1f}" '
                f'fill="{m["colour"]}" fill-opacity="{m["alpha"]}" '
                f'stroke="{m["colour"]}" stroke-width="1" stroke-opacity="0.5"/>'
            )
        if m["dot"]:
            body.append(
                f'<circle cx="{m["x"]:.1f}" cy="{m["y"]:.1f}" r="3.4" fill="{m["ink"]}" '
                f'stroke="#fff" stroke-width="1.4"/>'
            )

    if not blank:
        named = [m for m in marks if m["named"]]
        place_labels(named, p, city_boxes, obstacles)
        # Column labels and fallback positions can still overlap city names.
        # Wine-region labels take priority over contextual city labels.
        label_boxes = [
            (
                m["lx"] - (0.55 * m["size"] * len(m["name"]) + 10) / 2,
                m["ly"] - (m["size"] + 6) / 2,
                m["lx"] + (0.55 * m["size"] * len(m["name"]) + 10) / 2,
                m["ly"] + (m["size"] + 6) / 2,
            )
            for m in named
        ]
        covered = {
            k
            for k, b in enumerate(city_boxes)
            if any(
                not (b[2] < t[0] or b[0] > t[2] or b[3] < t[1] or b[1] > t[3]) for t in label_boxes
            )
        }
        layers = re.sub(
            r'<g data-city="(\d+)">.*?</g>\n?',
            lambda g: "" if int(g.group(1)) in covered else g.group(0),
            layers,
        )
        for m in named:
            # Leader line only when the label had to be pushed away - and
            # never from a region drawn without a dot, whose outline is what
            # the label names; a line would end on nothing.
            if m["dot"] and math.hypot(m["lx"] - m["x"], m["ly"] - m["y"]) > m["r"] + 14:
                body.append(
                    f'<line x1="{m["x"]:.1f}" y1="{m["y"]:.1f}" x2="{m["lx"]:.1f}" '
                    f'y2="{m["ly"]:.1f}" stroke="{m["ink"]}" stroke-width="0.9" '
                    f'stroke-opacity="0.6"/>'
                )
            # Two passes, not paint-order="stroke": that is SVG2, and cairosvg
            # silently ignores it, painting the white halo over the letters.
            common = (
                f'x="{m["lx"]:.1f}" y="{m["ly"] + m["size"] / 3:.1f}" '
                f'text-anchor="middle" font-size="{m["size"]}" '
                f'font-weight="{m["weight"]}"'
            )
            body.append(
                f'<text {common} fill="none" stroke="{LAND}" stroke-width="5.5" '
                f'stroke-linejoin="round" stroke-opacity="0.9">{esc(m["name"])}</text>'
            )
            body.append(f'<text {common} fill="{m["ink"]}">{esc(m["name"])}</text>')

    title = (
        ""
        if blank or not spec_map.get("title")
        else (f'<text x="{PAD}" y="{PAD + 4}" class="ti">{esc(spec_map["title"])}</text>')
    )

    clip = ""
    if fills or lines:
        paths = "".join(f'<path d="{d}"/>' for d in land_paths(p))
        clip = (
            f'<defs><clipPath id="{clip_id}">{paths}</clipPath></defs>'
            f'<g clip-path="url(#{clip_id})">' + "\n".join(fills + lines) + "</g>"
        )

    foot = credit_style = ""
    if credit and not canvas:
        px = CREDIT_PX * p.width / W
        credit_style = f"\n  .credit {{ font-size: {px:.2f}px; fill: {INK}; }}"
        gap = px / 2
        bw, bh = len(credit) * 0.56 * px + 2 * gap, px * 1.7
        bx, by = p.width - bw - gap, p.height - bh - gap
        foot = (
            f'\n<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
            f'rx="{gap / 2:.1f}" fill="#ffffff" fill-opacity="0.85"/>\n'
            f'<text x="{bx + bw - gap:.1f}" y="{by + bh / 2 + px / 3:.1f}" '
            f'text-anchor="end" class="credit">{esc(credit)}</text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {p.width:.0f} {p.height:.0f}" width="{p.width:.0f}" height="{p.height:.0f}">
<style>
  text {{ font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }}
  .ti {{ font-size: 30px; font-weight: 700; fill: {INK}; }}
  .city {{ font-size: {CITY_PX}px; fill: {CITY}; }}{credit_style}
</style>
<rect width="100%" height="100%" fill="{SEA}"/>
{layers}
{clip}
{chr(10).join(body)}{inset_svg}
{title}{foot}
</svg>
'''


def contact_sheet(ids: list[str], out_dir: Path, cols: int = 4) -> None:
    """One sheet of every map, for reviewing the set rather than one at a time.

    Geographic checks cannot establish visual clarity; inspect this sheet
    and individual maps for ambiguous labels and layout problems.
    """
    from PIL import Image

    tiles = [out_dir / f"{LEVEL}{i}.png" for i in ids]
    missing = [str(t) for t in tiles if not t.is_file()]
    if missing:
        raise FileNotFoundError("Contact sheet requires every map PNG: " + ", ".join(missing))
    if not tiles:
        return
    cell = 460
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), "#ffffff")
    for n, t in enumerate(tiles):
        im = Image.open(t)
        im.thumbnail((cell - 12, cell - 12))
        x = (n % cols) * cell + (cell - im.width) // 2
        y = (n // cols) * cell + (cell - im.height) // 2
        sheet.paste(im, (x, y))
    dest = out_dir / "_contact_sheet.png"
    sheet.save(dest)
    print(f"  {dest.name}  ({len(tiles)} maps)")


class Rasterizer(Protocol):
    def svg2png(self, *, bytestring: bytes, write_to: str, output_width: int) -> None: ...


def load_cairosvg() -> Rasterizer | None:
    """Import cairosvg, or return None and say why.

    cairosvg needs the native libcairo, which Homebrew installs somewhere the
    dynamic loader does not search by default - so the failure is an OSError
    from dlopen rather than an ImportError, and the naive `except ImportError`
    misses it entirely. Try the Homebrew library prefixes before importing.
    The caller decides whether missing Cairo is allowed for SVG-only output.
    """
    import os

    if sys.platform == "darwin":
        for prefix in ("/opt/homebrew/lib", "/usr/local/lib"):
            if Path(prefix).is_dir():
                os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                    prefix + ":" + os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
                )
    try:
        import cairosvg

        return cairosvg
    except ImportError:
        print("! cairosvg not installed (run uv sync --locked)")
    except OSError:
        print("! libcairo not found (try `brew install cairo`)")
    return None


class Arguments(argparse.Namespace):
    spec: Path
    svg_only: bool
    only: str | None
    treatment: str
    suffix: str
    out: str | None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", type=Path, default=SPEC, help="catalogue or external catalogue")
    ap.add_argument("--svg-only", action="store_true", help="explicitly omit PNG output")
    ap.add_argument("--only", help="render just this map id")
    ap.add_argument("--treatment", default="c", choices=["a", "b", "c"])
    ap.add_argument("--suffix", default="", help="append to output filename (for samples)")
    ap.add_argument("--out", default=None, help="output directory (default assets)")
    args = ap.parse_args(namespace=Arguments())

    out_dir = Path(args.out) if args.out else MAPS
    out_dir.mkdir(parents=True, exist_ok=True)

    from snapshots import prepare

    prepare()
    spec = load_catalogue(args.spec)
    todo = [m for m in spec["maps"] if not args.only or m["id"] == args.only]
    if not todo:
        print(f"no map with id {args.only!r}")
        return 1

    qids = [r["wikidata"] for m in todo for r in m["regions"] if r.get("wikidata")]
    ents = fetch_entities(sorted(set(qids)))

    credits = credit_lines()
    cairosvg = None if args.svg_only else load_cairosvg()
    if not args.svg_only and cairosvg is None:
        raise RuntimeError(
            "PNG output requires CairoSVG and native Cairo; use --svg-only only when PNG is not required"
        )

    for m in todo:
        for blank in (False, True):
            tag = "-blank" if blank else ""
            stem = f"{LEVEL}{m['id']}{args.suffix}{tag}"
            svg = render(
                m,
                ents,
                args.treatment,
                blank=blank,
                palette=spec.get("palette", {}),
                credit=credits.get(f"{LEVEL}{m['id']}{tag}.svg", ""),
            )
            (out_dir / f"{stem}.svg").write_text(svg, encoding="utf-8")
            if cairosvg:
                cairosvg.svg2png(
                    bytestring=svg.encode(),
                    write_to=str(out_dir / f"{stem}.png"),
                    output_width=int(W * 1.4),
                )
            print(f"  {stem}  ({len(m['regions'])} regions)")

    if cairosvg and not args.suffix:
        contact_sheet([m["id"] for m in todo], out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
