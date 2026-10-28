# Wine Study Maps

Wine-region maps for WSET Level 2 study can be hard to access, and many available
maps are crowded or difficult to read, even though much of the underlying
geographic data is freely available. This project provides clear, focused
alternatives: 35 maps, each with labelled and blank SVG and PNG versions, plus
a contact sheet for reviewing the set.

Wine annotations are deliberately limited to wine regions, geographical indications
(GIs) and protected designations of origin (PDOs) explicitly named in the WSET
Level 2 curriculum. Cities, rivers, coastlines and administrative areas provide
orientation. Coverage is not complete; New Zealand maps are not currently included.

This is an independent project, **not associated with, endorsed by, or produced by
the Wine & Spirit Education Trust (WSET)**. The maps use real geospatial inputs,
simplified into illustrative approximations for study. They are not official,
legal or surveyed boundaries; consult the relevant authorities for legal delimitations.
Dots and halos indicate position and rough scale, not boundaries.

## Use and build

Ready-to-use images are in `assets/`; use an exact Git revision when you need a
stable version. Each file is prefixed with the WSET level it covers, such as
`level-2-bordeaux.png` and `level-2-bordeaux-blank.svg`, so maps for another level
can sit alongside these without ambiguity. Rendering requires Python 3.11 or later, `uv`, and native Cairo
(`brew install cairo` on macOS). Python dependencies are locked in `uv.lock`.

```sh
uv sync --locked
uv run --locked python scripts/check_project.py
uv run --locked python scripts/source_geodata.py
uv run --locked python scripts/render_maps.py --out work/rendered
uv run --locked python -m unittest discover -s tests
```

After dependency installation, validation and rendering run offline. The renderer
writes labelled and blank SVGs and PNGs, plus a contact sheet. PNG output requires
Cairo; `--svg-only` explicitly requests SVG alone. `--only bordeaux` limits a render,
and `--spec` selects an external catalogue.

The renderer uses Helvetica Neue / Helvetica / Arial fallback and installed fonts.
PNG bytes can differ across platforms and native-library versions. Compare SVGs
and decoded PNG pixels when reviewing a rebuild, and inspect the contact sheet.

## Source snapshots

All 147 map-ready inputs are individually tracked under `data/inputs/`, grouped
by source: `natural-earth`, `wikidata`, `inao-ign`, `piemonte`, `eu-pdo`,
`wine-australia`, `uc-davis-ava` and `openstreetmap`. JSON is UTF-8 with two-space
indentation so coordinate and property changes appear directly in Git diffs.
The formatted input checkout occupies about 234.5 MB. No input archive is needed
to inspect or build the checkout.

`data/input-manifest.json` records each input's source URL/id, available version,
licence, transformations, SHA-256 and affected outputs. Acquisition dates were not
recorded. `pre_format_sha256` and `pre_format_bytes` describe the map-ready bytes
before text formatting, not necessarily raw upstream downloads. Formatting preserves
every parsed value without changing coordinate precision.

`scripts/snapshots.py` checks every committed input's path, inventory and bytes on
every build, then materialises `.cache` for the source adapters. A stale cache cannot
hide a missing, changed, unexpected or unsafe committed input. The cache is derived
and can be deleted; restore damaged committed files from Git. These checks establish
snapshot integrity, not independent proof of upstream authenticity or licence rights.
[ATTRIBUTION.md](ATTRIBUTION.md) describes the sources and their limits.

`data/upstream-archive-inventory.json` records hashes of original large downloads
without duplicating them here. Those optional transformation-audit files are not
needed for rendering. Unversioned upstream endpoints can change their contents.

For source maintenance, `scripts/source_geodata.py --refresh` permits network
fetches into a separate `.maintenance-cache`. It reuses existing maintenance
entries; remove that directory for a fresh upstream check. It does not update the
pinned `.cache`, input files or manifest. Changes need review before a new snapshot
and its hashes are committed.

## Label placement

A region's position comes from its sourced area's centroid or an explicit manual
`anchor` checked to lie inside that area. Where no area is supplied, a pinned
Wikidata coordinate locates the marker. A centroid need not fall inside a concave
or multipart region, so anchors can help place labels more meaningfully.

Region styling follows one scheme. The map's own region (by default, the one it
is titled after, or any region given `role: focus`) is a grey border over a light
grey wash. Every other region is a wine area, shaded and bordered in its colour.
An area whose `parent:` is another wine area on the map is drawn in a darker
shade, in its own colour if it has one or else its parent's. Nesting is declared,
never inferred from boundaries. An area with two parents, such as Los Carneros,
takes each parent's shade on its side of their border. Where two areas overlap
without either containing the other, the overlap is striped in both areas' own
tones. `exclude:` drops the communes another region on the map also lists, and
`keep:` limits an appellation to the communes containing given points.

Each recipe names its focus `country` (ISO 3166 alpha-3, as Natural Earth's
`ADM0_A3`). Only that country's cities are drawn; each neighbouring country in
frame is named once instead, at Natural Earth's label point or the middle of its
visible area, when that spot is clear.

Labels use approximate text boxes and a greedy search for space around cities and
other labels. Catalogue hints can put labels in side columns ordered north to
south, or above/below a region. Leader lines connect displaced labels to markers;
insets enlarge crowded detail. These heuristics do not guarantee collision-free
or unambiguous placement, so visual review of individual maps and the contact
sheet remains necessary.

## Quality gate

Install the pinned development tools, then run the same fail-fast command used by CI:

```sh
uv sync --locked --group dev
uv run --locked --group dev python scripts/quality.py
```

The gate runs Ruff lint and formatter checks, strict mypy checking of every
maintained script/test/stub, Pydantic structural validation, committed-input and
asset integrity checks, geographic checks, the regression tests and a full offline
35-map render. Catalogue/region, provenance/asset/upstream manifest, palette and
geometry contracts are concrete typed models. Validation reports the input file
and field path, rejects malformed/unknown configuration fields, bad references,
unsafe paths and non-finite numbers. Upstream foreign members and variable
attributes are retained; the models specify the fields and geometry actually
consumed rather than inventing a fixed schema for every provider property.

The checked-in Actions workflow uses read-only permissions, pinned action commits,
Python 3.11 and 3.14, locked Python tools, native Cairo and Liberation fonts. It
runs the command above unchanged. A configured workflow and a local gate result
are separate from an observed hosted CI result.

Render validation requires exact SVGs, the expected file inventory, valid decoded
PNGs and canonical image dimensions. Native Cairo/fonts can change PNG pixels
across systems. In an environment matching the canonical images, additionally run:

```sh
uv run --locked --group dev python scripts/validate_render.py --compare-only --exact-pixels
```

This compares the gate's `work/quality-render` PNG bytes and pixels exactly. The
portable gate does not waive SVG or PNG decoding/dimension checks on other platforms.

Source inputs are structurally validated at file/provider boundaries; the full
corpus is validated by the gate. During a render, a bounded in-memory cache reuses
read-only basemap layers keyed by path and file stat, avoiding repeated validation
of the same large layer. `prepare()` still verifies committed bytes before every
build; this cache does not replace source-integrity checks. Native dependencies,
visual clarity and upstream authenticity/licence rights remain outside the guarantees
of static types and structural models. Narrow local CairoSVG/pyshp interface stubs
cover only the APIs consumed; pyshp attributes are checked before use as text.

## Colours and licensing

Label text colours are explicit reviewed values in `data/label-colours.json`.
To extend the palette, add a reviewed entry keyed by
`fill-hex|background-hex|target` (currently `75`). Unknown entries fail clearly.
The target is a lookup-key component, not a live contrast calculation or a
compliance guarantee. Review readability at the actual display size and on the
contact sheet. Region fill overrides use the recipe's `colour` field.

Eligible project code is GPL-3.0-or-later; see [LICENSE](LICENSE). Original project
documentation and original artwork contributions are CC BY-SA 4.0 where the author
has the rights to grant it; see [LICENSE-ARTWORK.md](LICENSE-ARTWORK.md). Third-party
source data retain their own terms in the input manifest and
[ATTRIBUTION.md](ATTRIBUTION.md). This does not relicense upstream geometry or all
rights in generated maps. OpenStreetMap-derived administrative geometry remains
under ODbL; generated maps are produced works with contributor attribution.

Maps built from sources whose licences require attribution (CC BY 4.0, ODbL and
Licence Ouverte 2.0) carry a credit in the bottom-right corner of the map, derived from the
input manifest, so a single image reused on its own keeps its credit. Retain that credit
when reusing those images. Public-domain and CC0 sources are credited here and in
ATTRIBUTION.md only.
