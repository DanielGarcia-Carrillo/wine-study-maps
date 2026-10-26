# WSET 2 Maps

Standalone wine region maps: 32 recipes, 128 labelled/blank SVG and PNG assets,
and a contact sheet. No course text, card matching rules or Anki dependencies
are required. This extraction preserves the existing image bytes and geographic
representations; markers indicate position and rough scale, not legal boundaries.

## Offline build

Python 3.11 or later, `uv`, and native Cairo are required (`brew install cairo`
on macOS). Dependencies and transitive versions are locked in `uv.lock`.

```sh
uv sync --locked
uv run --locked python scripts/check_project.py
uv run --locked python scripts/source_geodata.py
uv run --locked python scripts/render_maps.py --out work/rendered
uv run --locked python -m unittest discover -s tests
```

After dependency installation, geography validation and rendering run without
network access. The checked-in `data/map-inputs.tar.gz` contains the exact map-ready
inputs; `scripts/snapshots.py` verifies its SHA-256 and every materialised input.
A missing or modified input fails clearly. Delete `.cache` to restore it from the
archive. Builds requiring PNG fail if Cairo is unavailable. `--svg-only` explicitly
requests SVG alone. `--only bordeaux` limits a render. `--spec` supports an external
private catalogue without embedding that catalogue here.

Ordinary consumers use the checked-in assets at an exact Git commit. They do not
fetch geography or regenerate images. Updating a consumer pin is deliberate.
Rendering uses Helvetica Neue / Helvetica / Arial fallback, Cairo and installed
fonts; PNG byte identity across operating systems is not promised. The checked-in
PNGs remain the canonical consumer bytes. Compare SVGs and decoded PNG pixels when
reviewing a rebuild, and review the contact sheet.

## Data and provenance

[ATTRIBUTION.md](ATTRIBUTION.md) describes source terms and geographic limits.
`data/input-manifest.json` records input source URL, source licence, transformations,
SHA-256, affected output filenames and unknown historical acquisition dates.
The map-ready archive is sufficient for standalone rendering. It preserves cached
processed inputs, including upstream names and original metadata, before any
refresh. Modified geometry is identified as derived upstream data.

`data/upstream-archive-inventory.json` preserves checksums of the available original
large upstream downloads without duplicating them in this repository. Those full
files are optional transformation-audit archives, not render dependencies. URLs and
versions are in the source adapters and input manifest; re-downloading an unversioned
upstream endpoint can change bytes. A future full-download mirror should be a
checksummed archive linked from that inventory, checked against the recorded hashes.
Do not invent acquisition dates. `source_geodata.py --refresh` explicitly permits
source-maintenance downloads for missing cache entries; it is never a routine build
step, and does not update the checked-in snapshot or manifest automatically.

New Zealand GI recipes, processed IPONZ inputs, images and thumbnails are excluded
pending redistribution-rights resolution. Existing private consumers may add their
own catalogue and data adapter. Natural Earth basemap geography covering New Zealand
is distinct and is still present as public-domain global geography.

## Label colours and licensing

Eligible project code is GPL-3.0-or-later; see [LICENSE](LICENSE). Original project
documentation and original artwork contributions are CC BY-SA 4.0 where the author
has the rights to grant it. Third-party source data retain the terms in the input
manifest and [ATTRIBUTION.md](ATTRIBUTION.md); this is not a blanket relicensing of
geometry or generated maps. OpenStreetMap-derived administrative geometry remains
under ODbL; generated maps are produced works with contributor attribution.

The pre-extraction renderer embedded an APCA 0.1.9 implementation. Its upstream
[licence](https://github.com/Myndex/apca-w3/blob/master/LICENSE.md) has use and
compliance restrictions. As a conservative provenance choice, this repository
contains no APCA implementation/constants. It stores the existing rendered label
colours explicitly in `data/label-colours.json`. This preserves the existing palette;
it is not a claim about a source-code licence grant or an APCA compliance claim.

To extend the palette, add an explicit reviewed text colour keyed by
`fill-hex|background-hex|target` (currently `75`). Review readability at actual output
size and the contact sheet; add the corresponding key to the table. Unknown entries
fail with an actionable error rather than silently changing appearance. Per-colour
entries can be changed independently. Do not restore third-party contrast code
without reviewing its licence. Existing region colour overrides still use the
recipe's `colour` field.

This local repository has no published remote. The intended sibling slug is
`WSET-2-Maps`; creating it or publishing this history needs separate authorization.
