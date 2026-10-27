"""Runtime validation at file/provider boundaries with file and field-path errors."""

from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
from typing import Annotated, TypeVar

import yaml
from models import (
    Area,
    AssetManifest,
    Catalogue,
    Entity,
    Feature,
    FeatureCollection,
    Geometry,
    InputManifest,
    InputRecord,
    LabelColours,
    OSMRecord,
    SparqlResponse,
    UpstreamRecord,
)
from pydantic import Field, JsonValue, TypeAdapter, ValidationError

T = TypeVar("T")
CATALOGUE = TypeAdapter(Catalogue)
INPUT_MANIFEST = TypeAdapter(InputManifest)
ASSETS = TypeAdapter(AssetManifest)
COLOURS = TypeAdapter(LabelColours)
UPSTREAM = TypeAdapter(list[UpstreamRecord])
AREA = TypeAdapter(Area)
ENTITY = TypeAdapter(Entity)
FEATURES = TypeAdapter(FeatureCollection)
FEATURE = TypeAdapter(Feature)
GEO_DOCUMENT = TypeAdapter(Annotated[Feature | FeatureCollection, Field(discriminator="type")])
GEOMETRY = TypeAdapter(Geometry)
SPARQL = TypeAdapter(SparqlResponse)
OSM = TypeAdapter(list[OSMRecord])
JSON = TypeAdapter(JsonValue)


def fail(source: Path | str, location: str, message: str) -> None:
    raise ValueError(f"{source}:{location}: {message}")


def finite(value: object, source: Path | str, location: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        fail(source, location, "non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                fail(source, location, "object keys must be strings")
            finite(child, source, f"{location}.{key}")
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            finite(child, source, f"{location}[{index}]")


def validate(value: object, adapter: TypeAdapter[T], source: Path | str) -> T:
    finite(value, source)
    try:
        return adapter.validate_python(value)
    except ValidationError as exc:
        details = "; ".join(
            f"$.{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10]
        )
        raise ValueError(f"{source}: {details}") from None


def decode_json(text: str, adapter: TypeAdapter[T], source: Path | str) -> T:
    try:
        value: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source}:$:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    return validate(value, adapter, source)


def read_json(path: Path, adapter: TypeAdapter[T]) -> T:
    return decode_json(path.read_text(encoding="utf-8"), adapter, path)


def safe_relative(value: str, source: Path | str, location: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or any(ord(character) < 32 for character in value)
        or "\\" in value
        or ":" in value
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != value
    ):
        fail(source, location, f"unsafe relative path {value!r}")
    return Path(path)


def load_manifest(root: Path) -> InputManifest:
    path = root / "data/input-manifest.json"
    manifest = read_json(path, INPUT_MANIFEST)
    seen: set[str] = set()
    cached: set[str] = set()
    families = {
        "Natural Earth": "natural-earth",
        "Wikidata": "wikidata",
        "INAO and IGN/Etalab": "inao-ign",
        "Regione Piemonte": "piemonte",
        "Candiago et al. 2022": "eu-pdo",
        "Wine Australia": "wine-australia",
        "UC Davis Library AVA": "uc-davis-ava",
        "OpenStreetMap contributors": "openstreetmap",
    }
    for i, row in enumerate(manifest["inputs"]):
        local = safe_relative(row["path"], path, f"$.inputs[{i}].path")
        cache = safe_relative(row["cache_path"], path, f"$.inputs[{i}].cache_path")
        if (
            len(local.parts) != 3
            or local.parts[:2] != ("inputs", families[row["source"]])
            or local.suffix not in (".json", ".geojson")
        ):
            fail(
                path,
                f"$.inputs[{i}].path",
                "path must identify a JSON input in its documented source directory",
            )
        if (
            len(cache.parts) != 2
            or cache.parts[0] not in (".naturalearth-cache", ".wikidata-cache", ".inao-cache")
            or cache.name != local.name
        ):
            fail(
                path,
                f"$.inputs[{i}].cache_path",
                "cache path must preserve the source filename in a supported adapter directory",
            )
        expected_cache = (
            ".wikidata-cache"
            if row["source"] == "Wikidata"
            else ".naturalearth-cache"
            if row["source"] == "Natural Earth" and local.name.startswith("ne_")
            else ".inao-cache"
        )
        if cache.parts[0] != expected_cache:
            fail(path, f"$.inputs[{i}].cache_path", "adapter directory disagrees with input family")
        if row["source_id"] != local.stem:
            fail(path, f"$.inputs[{i}].source_id", "source identifier differs from filename")
        if row["path"] in seen or row["cache_path"] in cached:
            fail(path, f"$.inputs[{i}].path", "duplicate input/cache path")
        seen.add(row["path"])
        cached.add(row["cache_path"])
    return manifest


def load_catalogue(path: Path) -> Catalogue:
    try:
        value: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}:$: invalid YAML: {exc}") from exc
    return catalogue_value(value, path)


def catalogue_value(value: object, source: Path | str) -> Catalogue:
    spec = validate(value, CATALOGUE, source)
    ids = [m["id"] for m in spec["maps"]]
    if len(ids) != len(set(ids)):
        fail(source, "$.maps", "duplicate map id")
    for key in spec.get("palette", {}):
        if key not in ids:
            fail(source, f"$.palette.{key}", "unknown map id")
    for i, mp in enumerate(spec["maps"]):
        names = {r["name"] for r in mp["regions"]}
        if len(names) != len(mp["regions"]):
            fail(source, f"$.maps[{i}].regions", "duplicate region name")
        bbox = mp.get("bbox")
        if isinstance(bbox, list) and not (
            -180 <= bbox[0] < bbox[2] <= 180 and -90 <= bbox[1] < bbox[3] <= 90
        ):
            fail(source, f"$.maps[{i}].bbox", "invalid west/south/east/north bounds")
        if inset := mp.get("inset"):
            for name in inset["regions"]:
                if name not in names:
                    fail(source, f"$.maps[{i}].inset.regions", f"unknown region {name!r}")
            if any(not 0 <= n <= 1 for n in inset["at"]) or any(
                n <= 0 for n in inset.get("size", (1.0, 1.0))
            ):
                fail(source, f"$.maps[{i}].inset", "at must be fractions and size must be positive")
        for j, region in enumerate(mp["regions"]):
            loc = f"$.maps[{i}].regions[{j}]"
            if (parent := region.get("parent")) and parent not in names:
                fail(source, loc + ".parent", f"unknown region {parent!r}")
            if (other := region.get("region_of")) and other not in ids:
                fail(source, loc + ".region_of", f"unknown map {other!r}")
            if (anchor := region.get("anchor")) and not (
                -180 <= anchor[0] <= 180 and -90 <= anchor[1] <= 90
            ):
                fail(source, loc + ".anchor", "longitude/latitude out of range")
            areas = [
                k
                for k in ("aoc", "ava", "county", "admin1", "osm", "doc", "pdo", "gi")
                if k in region
            ]
            if len(areas) > 1 or (not areas and not region.get("wikidata")):
                fail(source, loc, "exactly one area source or a Wikidata locator is required")
    return spec


def validate_input(path: Path, row: InputRecord) -> None:
    if row["source"] == "Wikidata":
        entity = read_json(path, ENTITY)
        if entity["qid"] != path.stem:
            fail(path, "$.qid", "entity id differs from filename")
    elif row["source"] in ("Natural Earth", "UC Davis Library AVA") and row[
        "cache_path"
    ].startswith((".naturalearth-cache/", ".inao-cache/ava-")):
        read_features(path)
    else:
        read_area(path)


def read_area(path: Path) -> Area:
    area = read_json(path, AREA)
    for i, ring in enumerate(area["rings"]):
        for j, (lon, lat) in enumerate(ring):
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                fail(path, f"$.rings[{i}][{j}]", "longitude/latitude out of range")
    return area


def read_features(path: Path) -> FeatureCollection:
    value = read_json(path, GEO_DOCUMENT)
    data: FeatureCollection = (
        {"type": "FeatureCollection", "features": [value]} if value["type"] == "Feature" else value
    )
    for i, feature in enumerate(data["features"]):
        geometry = feature["geometry"]
        if geometry is None:
            continue  # GeoJSON explicitly permits null geometry.
        location = f"$.features[{i}].geometry.coordinates"
        if geometry["type"] == "Point":
            if not isinstance(feature["properties"].get("NAME", ""), str):
                fail(path, f"$.features[{i}].properties.NAME", "point label must be text")
        elif geometry["type"] == "LineString" or geometry["type"] == "MultiPoint":
            minimum = 2 if geometry["type"] == "LineString" else 1
            if len(geometry["coordinates"]) < minimum:
                fail(path, location, f"expected at least {minimum} positions")
        else:
            if not geometry["coordinates"]:
                continue  # Empty source geometry has no drawable rings.
            polygons = (
                geometry["coordinates"]
                if geometry["type"] == "MultiPolygon"
                else [geometry["coordinates"]]
            )
            if not polygons or any(not polygon for polygon in polygons):
                fail(path, location, "empty geometry")
            for polygon in polygons:
                for ring in polygon:
                    minimum = 2 if geometry["type"] == "MultiLineString" else 4
                    if len(ring) < minimum:
                        fail(path, location, f"expected at least {minimum} positions per ring/line")
                    if geometry["type"] != "MultiLineString" and ring[0] != ring[-1]:
                        fail(path, location, "polygon ring must be closed")
    return data
