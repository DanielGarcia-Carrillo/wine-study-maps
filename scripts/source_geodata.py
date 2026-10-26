#!/usr/bin/env python3
"""Geographic sources, transformations and independent coordinate checks."""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / ".cache"
SPEC = ROOT / "catalogue.yaml"
NE_CACHE = MAPS / ".naturalearth-cache"
WD_CACHE = MAPS / ".wikidata-cache"
INAO_CACHE = MAPS / ".inao-cache"

UA = "WSET2-Maps/1.0 (geographic source validation)"

# Pinned release of nvkelso/natural-earth-vector. The geojson/ directory there
# serves plain JSON, so nothing here needs a shapefile reader or a geo stack.
NE_VERSION = "v5.1.2"
NE_BASE = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{NE_VERSION}/geojson"
LAYERS = {
    "land": "ne_10m_admin_0_countries.geojson",
    "coastline": "ne_10m_coastline.geojson",
    "rivers": "ne_10m_rivers_lake_centerlines.geojson",
    "lakes": "ne_10m_lakes.geojson",
    "places": "ne_10m_populated_places.geojson",
    "states": "ne_10m_admin_1_states_provinces.geojson",
    "counties": "ne_10m_admin_2_counties.geojson",
    "borders": "ne_10m_admin_0_boundary_lines_land.geojson",
}

# The two classes Wikidata uses for wine regions. Filtering on these is what
# separates the wine region from the same-named town.
WINE_CLASSES = ["wd:Q2140699", "wd:Q2556234"]  # wine-producing region, wine producing locality

SPARQL = "https://query.wikidata.org/sparql"

# French appellation areas, from the two official sources that between them
# define an AOC's geographic area exactly as the cahier des charges does.
#
# INAO itself notes that the official area is expressed "sous forme de liste
# de communes" - so the honest way to draw an AOC is to take its commune list
# and union the commune boundaries, rather than to trace an outline by eye.
# That is what these two give us, and it is why the polygons are sourced data
# rather than approximations.
INAO_CSV = ("https://static.data.gouv.fr/resources/aires-geographiques-des-aoc-aop/"
            "20251009-122320/2025-10-09-comagri-communes-aires-ao.csv")
GEO_API = "https://geo.api.gouv.fr/communes"

# OpenStreetMap, used ONLY for administrative units that Natural Earth does
# not carry - Chile's provinces and comunas, for instance. This is not a reversal of
# the decision to keep OSM out of the appellation boundaries: the objection
# there was that OSM gives you an administrative object when you asked for an
# appellation. Where the administrative object IS the thing wanted, it is the
# right source. ODbL, so it must be attributed.
NOMINATIM = "https://nominatim.openstreetmap.org/lookup"

# Piedmont publishes the boundaries of its DOC and DOCG production areas -
# the only Italian region that does, as far as a search of the EU data portal
# and the national catalogue goes. Licence: CC BY 4.0 (Regione Piemonte).
# Shapefile only, in UTM zone 32N, hence the reader and the reprojection.
# EU wine PDO areas (Candiago et al. 2022, Scientific Data), CC0, on figshare
EU_PDO = "https://ndownloader.figshare.com/files/35955185"
WINE_AUSTRALIA_GI = ("https://services6.arcgis.com/s8j6JbJJCqmhNgh7/arcgis/rest/services/"
                     "Wine_Geographical_Indications_Australia/FeatureServer")

PIEMONTE_DOC = ("https://www.datigeo-piem-download.it/direct/Geoportale/RegionePiemonte/"
                "AGRICOLTURA/Aree_vini_DOC_DOCG/aree_produzione_vini.zip")

# US appellation boundaries, digitised by the UC Davis Library AVA project
# from the TTB's legal descriptions. CC0. Pinned to a commit for the same
# reason the Natural Earth tag is pinned: a re-run should redraw the same
# boundary, not whatever the project has revised since.
AVA_SHA = "5208ac65eeb9c3250945f1fa182b4f2ebb7756a9"   # 2025-12-10
AVA_BASE = f"https://raw.githubusercontent.com/UCDavisLibrary/ava/{AVA_SHA}/avas"



REFRESH = False
def require_refresh():
    if not REFRESH:
        raise FileNotFoundError("Missing pinned source input; offline builds never fetch. Restore data/map-inputs.tar.gz or explicitly run source_geodata.py --refresh for source maintenance.")


def curl(args: list[str]) -> str:
    require_refresh()
    r = subprocess.run(["curl", "-fsSL", "--max-time", "180", "-H", f"User-Agent: {UA}", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"fetch failed: {r.stderr[:300]}")
    return r.stdout


def layer_path(name: str) -> Path:
    """Download a Natural Earth layer on first use; reuse the cache after."""
    if name not in LAYERS:
        raise KeyError(f"unknown layer {name!r}; known: {', '.join(sorted(LAYERS))}")
    dest = NE_CACHE / LAYERS[name]
    if not dest.exists():
        NE_CACHE.mkdir(parents=True, exist_ok=True)
        print(f"  fetching {LAYERS[name]} ({NE_VERSION}) ...", flush=True)
        dest.write_text(curl([f"{NE_BASE}/{LAYERS[name]}"]), encoding="utf-8")
    return dest


def load_layer(name: str) -> dict:
    return json.loads(layer_path(name).read_text(encoding="utf-8"))


def sparql(query: str) -> list[dict]:
    out = curl(["-G", "-H", "Accept: application/sparql-results+json",
                "--data-urlencode", f"query={query}", SPARQL])
    return json.loads(out)["results"]["bindings"]


def fetch_entities(qids: list[str]) -> dict[str, dict]:
    """Coordinate + label + description for each pinned Q-id, cached per id."""
    WD_CACHE.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    missing = []
    for q in qids:
        c = WD_CACHE / f"{q}.json"
        if c.exists():
            out[q] = json.loads(c.read_text())
        else:
            missing.append(q)

    if missing:
        print(f"  fetching {len(missing)} Wikidata entities ...", flush=True)
        values = " ".join(f"wd:{q}" for q in missing)
        rows = sparql(f"""SELECT ?item ?itemLabel ?desc ?coord WHERE {{
  VALUES ?item {{ {values} }}
  ?item wdt:P625 ?coord .
  OPTIONAL {{ ?item schema:description ?desc . FILTER(lang(?desc)="en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,fr". }}
}}""")
        for b in rows:
            q = b["item"]["value"].rsplit("/", 1)[1]
            lon, lat = parse_point(b["coord"]["value"])
            rec = {"qid": q, "label": b["itemLabel"]["value"],
                   "desc": b.get("desc", {}).get("value", ""), "lon": lon, "lat": lat}
            (WD_CACHE / f"{q}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))
            out[q] = rec
    return out


def parse_point(wkt: str) -> tuple[float, float]:
    m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", wkt)
    if not m:
        raise ValueError(f"unparseable coordinate {wkt!r}")
    return float(m.group(1)), float(m.group(2))


def inao_table() -> dict[str, list[str]]:
    """Appellation name -> INSEE codes of the communes in its geographic area.

    The CSV is cp1252, not UTF-8, and semicolon-delimited.
    """
    INAO_CACHE.mkdir(parents=True, exist_ok=True)
    raw = INAO_CACHE / "communes-aires-ao.csv"
    if not raw.exists():
        print("  fetching INAO appellation/commune table ...", flush=True)
        require_refresh()
        subprocess.run(["curl", "-fsSL", "--max-time", "180", "-H", f"User-Agent: {UA}",
                        "-o", str(raw), INAO_CSV], check=True)
    import csv, io
    table: dict[str, list[str]] = {}
    with io.open(raw, encoding="cp1252") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            table.setdefault(row["Aire géographique"], []).append(row["CI"])
    return table


def departement(insee: str) -> str:
    """INSEE code -> departement code (97x overseas are three digits)."""
    return insee[:3] if insee.startswith("97") else insee[:2]


def communes(dep: str) -> dict[str, dict]:
    """Every commune of one departement, with its boundary, from geo.api.gouv.fr."""
    INAO_CACHE.mkdir(parents=True, exist_ok=True)
    path = INAO_CACHE / f"communes-{dep}.geojson"
    if not path.exists():
        print(f"  fetching commune boundaries for departement {dep} ...", flush=True)
        path.write_text(curl([f"{GEO_API}?codeDepartement={dep}&format=geojson"
                              "&geometry=contour&fields=code,nom"]), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {f["properties"]["code"]: f for f in data["features"]}


def ava_area(ava_id: str) -> dict:
    """One US AVA's boundary, by its UC Davis ava_id (e.g. "napa_valley")."""
    INAO_CACHE.mkdir(parents=True, exist_ok=True)
    path = INAO_CACHE / f"ava-{ava_id}.json"
    if not path.exists():
        print(f"  fetching AVA boundary {ava_id} ...", flush=True)
        path.write_text(curl([f"{AVA_BASE}/{ava_id}.geojson"]), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    feats = data["features"] if data.get("type") == "FeatureCollection" else [data]

    # These files carry the AVA's SUPERSEDED boundaries alongside its current
    # one - Los Carneros has three, Central Coast four - distinguished only by
    # a date suffix on ava_id. Drawing them all stacks a 1983 outline under
    # the modern one, which looks like a rendering bug and is actually a
    # factual error. The undated ava_id is the boundary in force.
    current = [f for f in feats if f["properties"].get("ava_id") == ava_id]
    if not current:
        raise KeyError(f"{ava_id}: no current boundary among "
                       f"{[f['properties'].get('ava_id') for f in feats]}")
    superseded = len(feats) - len(current)

    rings = [r for f in current for r in rings_of(f["geometry"])]
    return {"name": current[0]["properties"].get("name", ava_id),
            "communes": 0, "missing": [], "superseded": superseded, "rings": rings}


def admin1_area(spec: str) -> dict:
    """A first-level administrative region, as "Country/Name".

    Many of the regions the syllabus teaches outside France and the USA are
    administrative units rather than appellations - Italy's Piemonte and
    Veneto, Spain's Rioja and Navarra, Australia's states, Argentina's
    Mendoza, South Africa's Western Cape. Natural Earth carries those, so they
    can be drawn as real boundaries instead of a marker.

    Natural Earth splits Italy and Spain into provinces, with a `region` field
    grouping them, so matching on either `name` or `region` and unioning what
    matches gives the region itself.
    """
    country, _, name = spec.partition("/")
    if not name:
        raise ValueError(f'admin1 must be "Country/Name", got {spec!r}')
    slug = re.sub(r"[^a-z0-9]+", "-", spec.lower()).strip("-")
    path = INAO_CACHE / f"admin1-{slug}.json"
    if not path.exists():
        feats = [f for f in load_layer("states")["features"]
                 if f["properties"].get("admin") == country
                 and name in (f["properties"].get("name"), f["properties"].get("region"))]
        if not feats:
            near = sorted({f["properties"].get("region") or f["properties"].get("name")
                           for f in load_layer("states")["features"]
                           if f["properties"].get("admin") == country})
            raise KeyError(f"no admin-1 unit {name!r} in {country}; known: {near[:14]}")
        rec = {"name": name, "communes": len(feats), "missing": [],
               "rings": [r for f in feats for r in rings_of(f["geometry"])]}
        INAO_CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def utm_to_wgs84(easting: float, northing: float, zone: int = 32) -> tuple[float, float]:
    """Inverse UTM (northern hemisphere) on the WGS84 ellipsoid -> (lon, lat).

    Snyder's series, good to millimetres, which is far beyond what a map at
    this scale needs. Done here rather than with pyproj because this is the
    only reprojection in the project and pyproj would pull in a native stack.
    A silently wrong transform would put polygons in the wrong country, so
    `check_projection()` verifies it against known control points.
    """
    a, f = 6378137.0, 1 / 298.257223563
    k0 = 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))

    x = easting - 500000.0
    m = northing / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    phi1 = (mu
            + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
            + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
            + (151 * e1**3 / 96) * math.sin(6 * mu)
            + (1097 * e1**4 / 512) * math.sin(8 * mu))

    sin1, cos1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    c1 = ep2 * cos1**2
    t1 = tan1**2
    n1 = a / math.sqrt(1 - e2 * sin1**2)
    r1 = a * (1 - e2) / (1 - e2 * sin1**2) ** 1.5
    d = x / (n1 * k0)

    lat = phi1 - (n1 * tan1 / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720)
    lon = (d
           - (1 + 2 * t1 + c1) * d**3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120) / cos1
    lon0 = math.radians(zone * 6 - 183)
    return (math.degrees(lon0 + lon), math.degrees(lat))


def doc_area(name: str) -> dict:
    """A Piedmont DOC/DOCG production area, by its `denominazi` value.

    The only Italian appellation boundaries published as open data that a
    search of the EU portal and the national catalogue turns up. Shapefile in
    UTM 32N, so it is read with pyshp and reprojected point by point.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    cached = INAO_CACHE / f"doc-{slug}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))

    INAO_CACHE.mkdir(parents=True, exist_ok=True)
    base = INAO_CACHE / "piemonte-doc"
    if not base.with_suffix(".shp").exists():
        zp = INAO_CACHE / "piemonte-doc.zip"
        if not zp.exists():
            print("  fetching Piemonte DOC/DOCG areas ...", flush=True)
            require_refresh()
            subprocess.run(["curl", "-fsSL", "--max-time", "600", "-H", f"User-Agent: {UA}",
                            "-o", str(zp), PIEMONTE_DOC], check=True)
        import zipfile
        with zipfile.ZipFile(zp) as z:
            for member in z.namelist():
                ext = Path(member).suffix
                if ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                    base.with_suffix(ext).write_bytes(z.read(member))

    import shapefile
    reader = shapefile.Reader(str(base))
    rings, kind = [], ""
    for sr in reader.shapeRecords():
        if sr.record["denominazi"] != name:
            continue
        kind = sr.record["tipo"]
        shp = sr.shape
        parts = list(shp.parts) + [len(shp.points)]
        for i in range(len(shp.parts)):
            ring = [utm_to_wgs84(x, y) for x, y in shp.points[parts[i]:parts[i + 1]]]
            if len(ring) >= 3:
                rings.append(ring)
    if not rings:
        near = sorted({r["denominazi"] for r in reader.records()
                       if name.lower()[:5] in r["denominazi"].lower()})
        raise KeyError(f"no Piemonte DOC/DOCG named {name!r}"
                       + (f"; did you mean {near}?" if near else ""))
    rec = {"name": name, "kind": kind, "communes": 0, "missing": [], "rings": rings}
    cached.write_text(json.dumps(rec), encoding="utf-8")
    return rec


def laea_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """EPSG:3035 (ETRS89 / LAEA Europe) to lon/lat, by the inverse formulas
    of IOGP Guidance Note 7-2 on the GRS80 ellipsoid. Checked in pdo_area()
    against independent control points, as utm_to_wgs84() is."""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = 2 * f - f * f
    e = math.sqrt(e2)
    lat0, lon0 = math.radians(52.0), math.radians(10.0)
    fe, fn = 4321000.0, 3210000.0

    def q(phi: float) -> float:
        s = math.sin(phi)
        return (1 - e2) * (s / (1 - e2 * s * s)
                           - (1 / (2 * e)) * math.log((1 - e * s) / (1 + e * s)))

    qp, q0 = q(math.pi / 2), q(lat0)
    rq = a * math.sqrt(qp / 2)
    beta0 = math.asin(q0 / qp)
    d = a * (math.cos(lat0) / math.sqrt(1 - e2 * math.sin(lat0) ** 2)) / (rq * math.cos(beta0))
    dx, dy = x - fe, y - fn
    rho = math.hypot(dx / d, d * dy)
    if rho == 0:
        return (math.degrees(lon0), math.degrees(lat0))
    c = 2 * math.asin(rho / (2 * rq))
    beta = math.asin(math.cos(c) * math.sin(beta0)
                     + d * dy * math.sin(c) * math.cos(beta0) / rho)
    lon = lon0 + math.atan2(dx * math.sin(c),
                            d * rho * math.cos(beta0) * math.cos(c)
                            - d * d * dy * math.sin(beta0) * math.sin(c))
    lat = (beta + (e2 / 3 + 31 * e2 ** 2 / 180 + 517 * e2 ** 3 / 5040) * math.sin(2 * beta)
           + (23 * e2 ** 2 / 360 + 251 * e2 ** 3 / 3780) * math.sin(4 * beta)
           + (761 * e2 ** 3 / 45360) * math.sin(6 * beta))
    return (math.degrees(lon), math.degrees(lat))


def _wkb_polygons(b: bytes) -> list[list[list[tuple[float, float]]]]:
    """Polygons (lists of rings of (x, y)) from (Multi)Polygon WKB."""
    import struct
    out, i = [], 0

    def geom(i: int) -> int:
        bo = "<" if b[i] == 1 else ">"
        kind = struct.unpack_from(bo + "I", b, i + 1)[0] % 1000
        i += 5
        if kind == 6:                                   # MultiPolygon
            n = struct.unpack_from(bo + "I", b, i)[0]
            i += 4
            for _ in range(n):
                i = geom(i)
            return i
        if kind != 3:
            raise ValueError(f"unexpected WKB geometry type {kind}")
        nrings = struct.unpack_from(bo + "I", b, i)[0]
        i += 4
        poly = []
        for _ in range(nrings):
            npts = struct.unpack_from(bo + "I", b, i)[0]
            i += 4
            pts = struct.unpack_from(bo + f"{2 * npts}d", b, i)
            i += 16 * npts
            poly.append(list(zip(pts[0::2], pts[1::2])))
        out.append(poly)
        return i

    geom(i)
    return out


def pdo_area(pdo_id: str) -> dict:
    """An EU wine PDO's area, by its eAmbrosia id (PDO-ES-A0117 is Rioja).

    From Candiago et al. 2022, "A geospatial inventory of regulatory
    information for wine protected designations of origin in Europe"
    (Scientific Data, doi 10.1038/s41597-022-01513-0), CC0, built from the EU
    register's own delimitations. The Spanish ministry publishes the same
    zones, but only behind a download form. GeoPackage in EPSG:3035.
    """
    cached = INAO_CACHE / f"pdo-{pdo_id}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    INAO_CACHE.mkdir(parents=True, exist_ok=True)
    gpkg = INAO_CACHE / "EU_PDO.gpkg"
    if not gpkg.exists():
        print("  fetching EU wine PDO areas (45 MB) ...", flush=True)
        require_refresh()
        subprocess.run(["curl", "-fsSL", "--max-time", "900", "-H", f"User-Agent: {UA}",
                        "-o", str(gpkg), EU_PDO], check=True)
    import sqlite3
    con = sqlite3.connect(gpkg)
    rows = con.execute('select Shape from EU_PDO where PDOid = ?', (pdo_id,)).fetchall()
    if not rows:
        raise KeyError(f"no PDO with id {pdo_id!r} in EU_PDO.gpkg")
    rings = []
    for (blob,) in rows:
        # GeoPackage binary: 'GP', version, flags, srs_id, then an envelope
        # whose size the flags give, then plain WKB
        env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(blob[3] >> 1) & 7]
        for poly in _wkb_polygons(blob[8 + env:]):
            for ring in poly[:1]:                    # outer rings only
                if len(ring) >= 3:
                    rings.append([laea_to_wgs84(x, y) for x, y in ring])
    rec = {"name": pdo_id, "kind": "PDO", "communes": 0, "missing": [], "rings": rings}
    cached.write_text(json.dumps(rec), encoding="utf-8")
    return rec


# Places whose coordinates come from somewhere other than the PDO file, each
# inside the PDO it is listed under: a wrong reprojection puts the polygons in
# another country and still draws something plausible.
PDO_CONTROL = {
    "PDO-ES-A0117": [(-2.847, 42.578)],     # Haro, Rioja Alta
    "PDO-ES-A0626": [(-3.689, 41.670)],     # Aranda de Duero
    "PDO-ES-A1560": [(0.776, 41.205)],      # Gratallops
    "PDO-DE-A1270": [(7.073, 49.917)],      # Bernkastel-Kues, Mittelmosel
    "PDO-DE-A1272": [(8.140, 49.350)],      # Neustadt an der Weinstrasse
    "PDO-IT-A1199": [(11.489, 43.058)],     # Montalcino
    "PDO-HU-A1254": [(21.409, 48.124)],     # Tokaj
}


def gi_area(spec: str) -> dict:
    """Wine Australia registered GI; source legal text prevails over geometry."""
    kind, _, rest = spec.partition("/")
    slug = re.sub(r"[^a-z0-9]+", "-", spec.lower()).strip("-")
    cached = INAO_CACHE / f"gi-{slug}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    INAO_CACHE.mkdir(parents=True, exist_ok=True)
    if kind == "au":
        feats = []
        for layer in (1, 0):                        # regions, then subregions
            where = f"UPPER(GI_NAME) = '{rest.upper()}'"
            out = curl(["-G", f"{WINE_AUSTRALIA_GI}/{layer}/query",
                        "--data-urlencode", f"where={where}",
                        "--data-urlencode", "outFields=GI_NAME,GI_TYPE",
                        "--data-urlencode", "outSR=4326",
                        "--data-urlencode", "f=geojson"])
            feats = json.loads(out).get("features", [])
            if feats:
                break
        if not feats:
            raise KeyError(f"no Wine Australia GI named {rest!r}")
        rings = [r for f in feats for r in rings_of(f["geometry"])]
        name = feats[0]["properties"]["GI_NAME"]
    else:
        raise KeyError(f'public gi must be "au/<name>", got {spec!r}')
    rec = {"name": name, "communes": 0, "missing": [], "rings": rings}
    cached.write_text(json.dumps(rec), encoding="utf-8")
    return rec


GI_CONTROL = {
    "au/Barossa Valley": [(138.960, -34.524)],     # Tanunda
    "au/Coonawarra": [(140.835, -37.380)],         # Penola's vineyards strip
    "au/Margaret River": [(115.075, -33.955)],     # Margaret River town
    "au/Hunter": [(151.290, -32.780)],             # Pokolbin
}


def area_of(r: dict) -> dict | None:
    """The sourced area for one maps.yaml region, or None for a marker.

    admin1 and osm take a list where a region is legally a union of
    administrative units - Chile's DOs are defined by provinces and comunas.
    """
    for key, fn in (("aoc", aoc_area), ("ava", ava_area), ("county", county_area),
                    ("admin1", admin1_area), ("osm", osm_area), ("doc", doc_area),
                    ("pdo", pdo_area), ("gi", gi_area)):
        v = r.get(key)
        if not v:
            continue
        if isinstance(v, list) and key != "aoc":
            parts = [fn(x) for x in v]
            return {"name": parts[0]["name"], "communes": sum(p["communes"] for p in parts),
                    "missing": [m for p in parts for m in p["missing"]],
                    "rings": [ring for p in parts for ring in p["rings"]]}
        return fn(v)
    return None


def osm_area(osm_id: str) -> dict:
    """One OSM administrative relation, e.g. "R112129" (Casablanca comuna)."""
    path = INAO_CACHE / f"osm-{osm_id}.json"
    if not path.exists():
        print(f"  fetching OSM boundary {osm_id} ...", flush=True)
        out = curl(["-G", NOMINATIM, "--data-urlencode", f"osm_ids={osm_id}",
                    "--data-urlencode", "format=json",
                    "--data-urlencode", "polygon_geojson=1"])
        data = json.loads(out)
        if not data:
            raise KeyError(f"OSM lookup returned nothing for {osm_id}")
        d = data[0]
        if d.get("class") != "boundary":
            raise KeyError(f"{osm_id} is a {d.get('class')}/{d.get('type')}, "
                           f"not an administrative boundary")
        rec = {"name": d.get("display_name", osm_id).split(",")[0], "communes": 0,
               "missing": [], "rings": rings_of(d["geojson"])}
        INAO_CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def county_area(fips: str) -> dict:
    """One US county, by FIPS code.

    For the two Californian regions in this catalogue that are counties
    rather than AVAs - Sonoma, and Santa Barbara County. Pinned by FIPS
    rather than by name because county names repeat across states.
    """
    path = INAO_CACHE / f"county-{fips}.json"
    if not path.exists():
        feats = [f for f in load_layer("counties")["features"]
                 if f["properties"].get("FIPS") == fips]
        if not feats:
            raise KeyError(f"no US county with FIPS {fips!r}")
        rec = {"name": feats[0]["properties"].get("NAME", fips), "communes": 0,
               "missing": [], "rings": [r for f in feats for r in rings_of(f["geometry"])]}
        INAO_CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def aoc_area(name: str | list[str]) -> dict:
    """The polygons making up one appellation's geographic area.

    Returned as the raw commune polygons rather than a dissolved outline: drawn
    filled and without strokes they read as one shape, so there is no need to
    take on a geometry library to union them.
    """
    names = [name] if isinstance(name, str) else list(name)
    slug = re.sub(r"[^a-z0-9]+", "-", "+".join(names).lower()).strip("-")[:80]
    cached = INAO_CACHE / f"aoc-{slug}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))

    table = inao_table()
    codes: list[str] = []
    for n in names:
        if n not in table:
            near = [k for k in table if n.lower()[:8] in k.lower()][:6]
            raise KeyError(f"no INAO appellation named {n!r}"
                           + (f"; did you mean {near}?" if near else ""))
        codes.extend(table[n])
    codes = sorted(set(codes))
    rings: list[list] = []
    missing: list[str] = []
    for dep in sorted({departement(c) for c in codes}):
        idx = communes(dep)
        for c in codes:
            if departement(c) != dep:
                continue
            f = idx.get(c)
            if f is None:
                missing.append(c)
                continue
            rings.extend(rings_of(f["geometry"]))
    rec = {"name": names[0], "communes": len(codes), "missing": missing, "rings": rings}
    cached.write_text(json.dumps(rec), encoding="utf-8")
    return rec


def rings_of(geom: dict) -> list[list]:
    t, c = geom["type"], geom["coordinates"]
    if t == "Polygon":
        return c[:1]              # outer ring only; holes are not meaningful here
    if t == "MultiPolygon":
        return [poly[0] for poly in c]
    return []


def in_rings(pt: list[float], area_rings: list[list]) -> bool:
    """Whether a (lon, lat) point falls inside any of the rings (ray casting)."""
    x, y = pt
    for ring in area_rings:
        inside = False
        for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
        if inside:
            return True
    return False


def candidates(name: str, country: str | None) -> None:
    """Print class-filtered options for a region, for pinning by hand."""
    country_clause = f"?item wdt:P17 wd:{country} ." if country else ""
    rows = sparql(f"""SELECT ?item ?itemLabel ?desc ?coord ?classLabel WHERE {{
  ?item rdfs:label|skos:altLabel "{name}"@en .
  ?item wdt:P625 ?coord .
  OPTIONAL {{ ?item wdt:P31 ?class . }}
  OPTIONAL {{ ?item schema:description ?desc . FILTER(lang(?desc)="en") }}
  {country_clause}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 60""")
    if not rows:
        print(f"no coordinate-bearing item found for {name!r}"
              + (f" in {country}" if country else ""))
        return
    seen = set()
    print(f"\ncandidates for {name!r}:\n")
    for b in rows:
        q = b["item"]["value"].rsplit("/", 1)[1]
        cls = b.get("classLabel", {}).get("value", "")
        if (q, cls) in seen:
            continue
        seen.add((q, cls))
        lon, lat = parse_point(b["coord"]["value"])
        wine = "  <- wine-typed" if "wine" in cls.lower() else ""
        print(f"  {q:12} {cls[:30]:32} {b.get('desc', {}).get('value', '')[:44]:46} "
              f"{lat:8.3f},{lon:9.3f}{wine}")
    print("\nPin the wine-typed row if there is one; otherwise the commune is the "
          "honest anchor.\nRecord its description verbatim as wd_desc in maps.yaml.")


def verify(spec: dict) -> int:
    """Check every region resolves, and that independent sources agree."""
    qids = [r["wikidata"] for m in spec["maps"] for r in m["regions"] if r.get("wikidata")]
    ents = fetch_entities(sorted(set(qids)))

    problems = 0
    for m in spec["maps"]:
        print(f"\n{m['id']}:")
        for r in m["regions"]:
            try:
                area = area_of(r)
            except KeyError as exc:
                print(f"  X  {r['name']:24} {exc}")
                problems += 1
                continue

            if area is None and not r.get("wikidata"):
                print(f"  X  {r['name']:24} nothing to place it by "
                      f"(aoc/ava/county/admin1/wikidata)")
                problems += 1
                continue

            note = ""
            if area:
                src = ("INAO" if r.get("aoc") else "AVA " if r.get("ava")
                       else "FIPS" if r.get("county")
                       else "OSM " if r.get("osm")
                       else "DOC " if r.get("doc")
                       else "PDO " if r.get("pdo")
                       else "GI  " if r.get("gi") else "NE  ")
                note = f"{src} {area['communes'] or len(area['rings']):4d} "
                note += "communes" if r.get("aoc") else "rings   "
                if r.get("county"):
                    note = f"FIPS {r['county']:10} county  "
                if r.get("admin1"):
                    note = f"NE   admin-1, {area['communes']:2d} unit(s)  "
                if r.get("osm"):
                    osm = r["osm"] if isinstance(r["osm"], str) else "+".join(r["osm"])
                    note = f"OSM  {osm:10} district "
                if r.get("gi"):
                    note = f"GI   {r['gi']:24} {len(area['rings']):3d} rings "
                    bad = [pt for pt in GI_CONTROL.get(r["gi"], [])
                           if not in_rings(list(pt), area["rings"])]
                    if bad:
                        print(f"  X  {r['name']:24} control point(s) {bad} outside the GI")
                        problems += 1
                if r.get("doc"):
                    note = f"DOC  {area.get('kind', ''):<5} {len(area['rings']):3d} rings   "
                if r.get("pdo"):
                    note = f"PDO  {r['pdo']:12} {len(area['rings']):3d} rings "
                    bad = [pt for pt in PDO_CONTROL.get(r["pdo"], [])
                           if not in_rings(list(pt), area["rings"])]
                    if bad:
                        print(f"  X  {r['name']:24} control point(s) {bad} outside the "
                              f"reprojected PDO - check laea_to_wgs84()")
                        problems += 1
                if area.get("superseded"):
                    note += f"  (skipped {area['superseded']} superseded boundary revision(s))"
                if area["missing"]:
                    # Usually a commune that has since merged; its successor is
                    # normally in the list too, so coverage survives. Say so
                    # rather than dropping it silently.
                    note += f"  ({len(area['missing'])} INSEE codes no longer exist)"

            q = r.get("wikidata")
            cross = ""
            if r.get("anchor"):
                # A hand-placed label anchor is the one coordinate in this file
                # that no source supplied, so it must at least sit inside the
                # region it labels. It is only ever needed where a centroid
                # lands in a different region - Crozes-Hermitage's is inside
                # Hermitage - so an anchor outside its own area is the exact
                # mistake it exists to prevent.
                if not area:
                    cross = "  ! anchor: needs a sourced area to sit inside"
                elif not in_rings(r["anchor"], area["rings"]):
                    cross = f"  ! anchor {r['anchor']} lies outside its own area"
                else:
                    note += "  (anchor inside area)"
            if q and area:
                ent = ents.get(q)
                if ent:
                    pts = [pt for ring in area["rings"] for pt in ring]
                    aw, ae = min(p[0] for p in pts), max(p[0] for p in pts)
                    a_s, an = min(p[1] for p in pts), max(p[1] for p in pts)
                    if not (aw <= ent["lon"] <= ae and a_s <= ent["lat"] <= an):
                        cross = "  ! pinned point lies outside its own sourced area"
                    elif ent["desc"] and r.get("wd_desc"):
                        pin, live = r["wd_desc"].lower(), ent["desc"].lower()
                        if not (pin in live or live in pin):
                            cross = f"  ! description drifted: {ent['desc']!r}"
            elif q and not area:
                ent = ents.get(q)
                if ent is None:
                    cross = f"  ! {q} returned no coordinate"

            flag = "X " if cross else "ok"
            if cross:
                problems += 1
            print(f"  {flag} {r['name']:24} {note}{cross}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="fetch/verify upstream inputs in a separate, unpinned maintenance cache")
    ap.add_argument("--candidates", metavar="NAME", help="list Q-id options for a region")
    ap.add_argument("--country", metavar="QID", help="narrow --candidates to a country, e.g. Q142")
    ap.add_argument("--layers", action="store_true", help="pre-fetch all Natural Earth layers")
    args = ap.parse_args()

    global REFRESH, MAPS, NE_CACHE, WD_CACHE, INAO_CACHE
    REFRESH = args.refresh
    MAPS = ROOT / (".maintenance-cache" if REFRESH else ".cache")
    NE_CACHE, WD_CACHE, INAO_CACHE = (MAPS / ".naturalearth-cache", MAPS / ".wikidata-cache", MAPS / ".inao-cache")
    if args.candidates:
        candidates(args.candidates, args.country)
        return 0

    if not REFRESH:
        from snapshots import prepare
        prepare()
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    wanted = sorted({l for m in spec["maps"] for l in m.get("base", [])})
    for name in (sorted(LAYERS) if args.layers else wanted):
        layer_path(name)

    problems = verify(spec)
    if problems:
        print(f"\n{problems} problem(s) - fix catalogue.yaml before rendering")
        return 1
    print("\nall pinned entities verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
