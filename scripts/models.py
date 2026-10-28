"""Concrete project and consumed-provider data contracts, shared by validation and typing."""

from __future__ import annotations

from typing import Annotated, Literal, NotRequired, Required, TypeAlias

from pydantic import AfterValidator, BeforeValidator, ConfigDict, Field, JsonValue, with_config
from typing_extensions import TypedDict

Number: TypeAlias = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Nonnegative: TypeAlias = Annotated[int, Field(strict=True, ge=0)]
Text: TypeAlias = Annotated[str, Field(strict=True, min_length=1)]
SHA256: TypeAlias = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Colour: TypeAlias = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Slug: TypeAlias = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
URL: TypeAlias = Annotated[str, Field(pattern=r"^https://[^\s]+$")]
LayerName: TypeAlias = Literal[
    "land", "coastline", "rivers", "lakes", "places", "states", "counties", "borders"
]
Side: TypeAlias = Literal["e", "w", "n", "s"]
Outline: TypeAlias = bool | Literal["dashed"]
JsonObject: TypeAlias = dict[str, JsonValue]


def point_sequence(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return value


Point: TypeAlias = Annotated[tuple[Number, Number], BeforeValidator(point_sequence)]


def geographic_point(value: tuple[float, float]) -> tuple[float, float]:
    if not (-180 <= value[0] <= 180 and -90 <= value[1] <= 90):
        raise ValueError("longitude/latitude out of range")
    return value


Position: TypeAlias = Annotated[Point, AfterValidator(geographic_point)]
Ring: TypeAlias = list[Point]
Rings: TypeAlias = list[Ring]
PolygonRing: TypeAlias = Annotated[Ring, Field(min_length=3)]
BBox: TypeAlias = Annotated[list[Number], Field(min_length=4, max_length=4)]
Palette: TypeAlias = dict[Slug, Colour]
# Every map file is prefixed with the WSET level it serves, so maps for
# another level never collide with or hide among these.
LEVEL = "level-2-"
AssetName: TypeAlias = Annotated[
    str, Field(pattern=r"^(?:level-[0-9]-[a-z0-9-]+\.(?:svg|png)|_contact_sheet\.png)$")
]
AssetManifest: TypeAlias = dict[AssetName, SHA256]
LabelColours: TypeAlias = dict[
    Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}\|#[0-9a-fA-F]{6}\|[0-9]+(?:\.[0-9]+)?$")],
    Colour,
]


@with_config(ConfigDict(extra="forbid", strict=True))
class Region(TypedDict, total=False):
    name: Required[Text]
    region_of: Slug
    aoc: Text | Annotated[list[Text], Field(min_length=1)]
    ava: Text
    county: Annotated[str, Field(pattern=r"^US[0-9]{5}$|^[0-9]{5}$")]
    admin1: Text | Annotated[list[Text], Field(min_length=1)]
    osm: Text | Annotated[list[Text], Field(min_length=1)]
    doc: Text
    pdo: Text
    gi: Text
    wikidata: Annotated[str, Field(pattern=r"^Q[0-9]+$")]
    wd_desc: Text
    tier: Annotated[int, Field(strict=True, ge=0, le=2)]
    extent: Literal["small", "medium", "large", "broad"]
    colour: Colour
    group: Text
    label: Side
    role: Literal["focus", "area"]
    dot: bool
    anchor: Point
    parent: Text | Annotated[list[Text], Field(min_length=2)]
    fit: bool
    named: bool
    wrap: bool
    keep: Annotated[list[Position], Field(min_length=1)]
    exclude: Annotated[list[Text], Field(min_length=1)]


@with_config(ConfigDict(extra="forbid", strict=True))
class Inset(TypedDict, total=False):
    regions: Required[Annotated[list[Text], Field(min_length=1)]]
    at: Required[Point]
    size: NotRequired[Point]
    title: str
    base: list[LayerName]
    pad: Annotated[Number, Field(ge=0)]
    min_aspect: Annotated[Number, Field(gt=0)]
    align: Annotated[Number, Field(ge=0, le=1)]


@with_config(ConfigDict(extra="forbid", strict=True))
class MapSpec(TypedDict, total=False):
    id: Required[Slug]
    regions: Required[Annotated[list[Region], Field(min_length=1)]]
    title: Text
    bbox: BBox | Literal["auto"]
    base: list[LayerName]
    pad: Annotated[Number, Field(ge=0)]
    min_span: Annotated[Number, Field(gt=0)]
    min_aspect: Annotated[Number, Field(gt=0)]
    align: Annotated[Number, Field(ge=0, le=1)]
    inset: Inset
    distinct: bool
    thin_places: bool
    include: list[Position]
    country: Annotated[list[Annotated[str, Field(pattern=r"^[A-Z]{3}$")]], Field(min_length=1)]


@with_config(ConfigDict(extra="forbid", strict=True))
class Catalogue(TypedDict):
    maps: Annotated[list[MapSpec], Field(min_length=1)]
    palette: NotRequired[Palette]


@with_config(ConfigDict(extra="forbid", strict=True))
class InputRecord(TypedDict):
    path: Text
    cache_path: Text
    sha256: SHA256
    bytes: Nonnegative
    outputs: Annotated[list[AssetName], Field(min_length=1)]
    source: Literal[
        "Natural Earth",
        "Wikidata",
        "INAO and IGN/Etalab",
        "Regione Piemonte",
        "Candiago et al. 2022",
        "Wine Australia",
        "IPONZ",
        "UC Davis Library AVA",
        "OpenStreetMap contributors",
    ]
    licence: Text
    source_url: URL
    transformations: Text
    acquired_at: str | None
    source_id: Text
    version: str | None
    pre_format_sha256: SHA256
    pre_format_bytes: Nonnegative
    text_format: Text


@with_config(ConfigDict(extra="forbid", strict=True))
class InputManifest(TypedDict):
    acquired_at: str | None
    acquisition_note: Text
    inputs: Annotated[list[InputRecord], Field(min_length=1)]


@with_config(ConfigDict(extra="forbid", strict=True))
class UpstreamRecord(TypedDict):
    filename: Text
    sha256: SHA256
    bytes: Nonnegative
    acquired_at: str | None
    stored_in_map_ready_archive: bool
    source_url: URL
    licence: Text
    version: str | None
    transformations: Text


@with_config(ConfigDict(extra="forbid", strict=True))
class Entity(TypedDict):
    qid: Annotated[str, Field(pattern=r"^Q[0-9]+$")]
    label: Text
    desc: str
    lon: Annotated[Number, Field(ge=-180, le=180)]
    lat: Annotated[Number, Field(ge=-90, le=90)]


Entities: TypeAlias = dict[str, Entity]


@with_config(ConfigDict(extra="forbid", strict=True))
class Area(TypedDict):
    name: Text
    communes: Nonnegative
    missing: list[str]
    rings: Annotated[list[PolygonRing], Field(min_length=1)]
    kind: NotRequired[str]
    superseded: NotRequired[Nonnegative]


# Only consumed properties are fixed. Other upstream attributes/foreign members
# remain permitted and retained, including provider-specific metadata.
@with_config(ConfigDict(extra="allow", strict=True))
class Properties(TypedDict, total=False):
    NAME: str | None
    SCALERANK: Number | None
    ADM0_A3: str | None
    LABEL_X: Number | None
    LABEL_Y: Number | None
    admin: str | None
    name: str | None
    region: str | None
    FIPS: str
    code: str
    ava_id: str
    GI_NAME: str


@with_config(ConfigDict(extra="allow", strict=True))
class GeoPoint(TypedDict):
    type: Literal["Point"]
    coordinates: Position


@with_config(ConfigDict(extra="allow", strict=True))
class GeoLine(TypedDict):
    type: Literal["LineString", "MultiPoint"]
    coordinates: list[Position]


@with_config(ConfigDict(extra="allow", strict=True))
class GeoPolygon(TypedDict):
    type: Literal["Polygon", "MultiLineString"]
    coordinates: list[list[Position]]


@with_config(ConfigDict(extra="allow", strict=True))
class GeoMultiPolygon(TypedDict):
    type: Literal["MultiPolygon"]
    coordinates: list[list[list[Position]]]


Geometry: TypeAlias = Annotated[
    GeoPoint | GeoLine | GeoPolygon | GeoMultiPolygon, Field(discriminator="type")
]


@with_config(ConfigDict(extra="allow", strict=True))
class Feature(TypedDict):
    type: Literal["Feature"]
    geometry: Geometry | None
    properties: Properties


@with_config(ConfigDict(extra="allow", strict=True))
class FeatureCollection(TypedDict):
    type: Literal["FeatureCollection"]
    features: list[Feature]


@with_config(ConfigDict(extra="allow", strict=True))
class Binding(TypedDict):
    value: str


Bindings: TypeAlias = dict[str, Binding]


@with_config(ConfigDict(extra="allow", strict=True))
class SparqlResults(TypedDict):
    bindings: list[Bindings]


@with_config(ConfigDict(extra="allow", strict=True))
class SparqlResponse(TypedDict):
    results: SparqlResults


@with_config(ConfigDict(extra="allow", strict=True))
class OSMRecord(TypedDict):
    display_name: str
    geojson: Geometry
    # `class` is a reserved Python word; this raw field is checked by an adapter.


class Mark(TypedDict):
    name: str
    x: float
    y: float
    r: float
    colour: str
    ink: str
    alpha: float
    size: float
    weight: int
    area: Area | None
    fill: bool
    dot: bool
    outline: Outline
    side: Side | None
    tier: int
    anchored: bool
    named: bool
    lines: list[str]
    role: Literal["focus", "area"]
    parents: list[str]
    own_colour: bool
    nested: bool
    lx: NotRequired[float]
    ly: NotRequired[float]
