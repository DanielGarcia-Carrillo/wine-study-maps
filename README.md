# WSET 2 Maps

Wine-region maps for WSET Level 2 study can be hard to access, and many available
maps are crowded or difficult to read, even though much of the underlying
geographic data is freely available. This project provides clear, focused
alternatives: 32 maps, each with labelled and blank SVG and PNG versions, plus
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
stable version. Rendering requires Python 3.11 or later, `uv`, and native Cairo
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

`data/map-inputs.tar.gz` bundles 147 map-ready inputs: about 25 MiB compressed versus
94.7 MB expanded. Compression keeps the source snapshot manageable and lets an
offline build use exact, recorded bytes. The tradeoff is poor Git diffs: reviewers
must inspect the per-file manifest and unpacked changes rather than the archive diff.

`data/input-manifest.json` records each input's source URL/id, available version,
licence, transformations, SHA-256 and affected outputs. Acquisition dates were not
recorded. `scripts/snapshots.py` verifies the archive hash and every materialised
input. Missing or modified inputs fail clearly; delete `.cache` to restore them
from the checked-in archive. Modified geometry remains identified as derived
upstream data. These checks establish snapshot integrity, not independent proof of
upstream authenticity or licence rights. [ATTRIBUTION.md](ATTRIBUTION.md) describes
the sources and their limits.

`data/upstream-archive-inventory.json` records hashes of original large downloads
without duplicating them here. Those optional transformation-audit files are not
needed for rendering. Unversioned upstream endpoints can change their contents.

For source maintenance, `scripts/source_geodata.py --refresh` permits network
fetches into a separate `.maintenance-cache`. It reuses existing maintenance
entries; remove that directory for a fresh upstream check. It does not update the
pinned `.cache`, archive or manifest. Changes need review before a new snapshot
and its hashes are committed.

## Label placement

A region's position comes from its sourced area's centroid or an explicit manual
`anchor` checked to lie inside that area. Where no area is supplied, a pinned
Wikidata coordinate locates the marker. A centroid need not fall inside a concave
or multipart region, so anchors can help place labels more meaningfully.

Labels use approximate text boxes and a greedy search for space around cities and
other labels. Catalogue hints can put labels in side columns ordered north to
south, or above/below a region. Leader lines connect displaced labels to markers;
insets enlarge crowded detail. These heuristics do not guarantee collision-free
or unambiguous placement, so visual review of individual maps and the contact
sheet remains necessary.

## Existing checks

- Seven `unittest` cases cover archive corruption, missing/changed inputs, reviewed
  label colours, projection origins and town controls, isolated maintenance fetches,
  required Cairo for PNGs, and missing contact-sheet tiles.
- `scripts/check_project.py` checks catalogue and asset counts, file hashes,
  required provenance keys and a public-content allowlist.
- `scripts/source_geodata.py` checks recorded geographic inputs, available pinned
  coordinates and descriptions, manual anchors and selected independent town controls.
  Default checks use the snapshot, rather than querying current upstream data.
- `uv.lock` fixes Python dependency versions; native Cairo and system fonts remain
  environment dependencies.

There is currently no configured linter, formatter, type checker, full catalogue or
manifest schema validator, or CI workflow. The checks above are targeted checks,
not a full schema or a guarantee of cartographic accuracy.

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
