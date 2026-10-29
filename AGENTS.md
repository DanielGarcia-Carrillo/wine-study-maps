# Agent notes

Guidance for coding agents working on Wine Study Maps. `CLAUDE.md` is a symlink
to this file. Read [README.md](README.md) for the project itself; this file adds
the working rules and the map style an agent must keep to.

## Commands

```sh
uv sync --locked --group dev
uv run --locked python scripts/render_maps.py                  # all maps into assets/
uv run --locked python scripts/render_maps.py --only bordeaux --out work/try
uv run --locked python scripts/render_legend.py                # docs/legend.{svg,png}
uv run --locked --group dev python scripts/quality.py          # the full gate, ~1 min
```

Run the quality gate before every commit. It fails if `assets/` or `docs/legend.svg`
differ from a fresh render, so after changing the catalogue or renderer: render,
update the SHA-256 values in `data/asset-manifest.json` for every changed asset
(PNGs in `assets/`, SVGs in `work/svg/`), then run the gate. Render with the
dev group installed, or the PNGs come out without the watermark. Adding or removing a map also changes the expected counts in
`scripts/check_project.py` and the README. Delete `work/quality-render` if stale
files from a renamed map make the gate complain.

Everything runs offline from the committed inputs in `data/inputs/`. Never edit
those files by hand; source changes go through
`scripts/source_geodata.py --refresh` and a reviewed new snapshot.

## Layout

- `catalogue.yaml`: one recipe per map, the only place map content is decided.
- `scripts/render_maps.py`: the renderer. Style constants live at its top.
- `scripts/models.py`, `scripts/validation.py`: strict schemas for every file;
  unknown catalogue keys are rejected, so a new key needs a model field too.
- `scripts/source_geodata.py`: turns pinned inputs into region outlines.
- `assets/level-2-<id>.png` and `-blank` variants: committed outputs. Their SVGs
  are not committed (a render into `assets/` writes them to `work/svg/`); the
  manifest pins them by digest. The
  `level-2-` prefix is the WSET level; maps for another level get their own prefix.
- `docs/legend.*`: the one shared legend, generated, never hand-edited.

## Catalogue keys

Per map: `id`, `title`, `country` (ISO3 list; only these countries get cities,
neighbours get a capitalised name), `bbox`, `pad`, `include` (points to keep in
frame), `inset`, `base`.

Per region: one source key (`aoc`, `pdo`, `gi`, `ava`, `county`, `admin1`, `osm`,
`doc`, `wikidata`), then optional:

- `role: focus | area`: focus is the region the map is about.
- `parent`: a name, or a list of two, of another region on the map it sits inside.
- `colour`: its own fill instead of the palette or parent colour.
- `keep`: points; only the communes containing them are kept (drops exclaves).
- `exclude`: names of regions whose communes are removed from this one.
- `label: n | s | e | w`, `wrap`, `anchor`, `fit`, `dot`, `named`: label placement.

## Map style

Keep to this scheme; the legend and README describe the same thing.

- The map's own region (`role: focus`, or the one named by the title) is a grey
  border over a light grey wash. It is not labelled again when it shares the title.
- Every other region is a wine area: solid light shading plus a border in its colour.
- Nesting is declared with `parent`, never inferred from geometry. A nested area is
  a darker tone of its parent's colour (or of its own `colour`), darker again a
  level deeper.
- An area with two parents, such as Los Carneros, takes each parent's tone on its
  side of their shared border.
- Two areas that overlap without either containing the other are striped in both
  areas' own tones, on the overlap only.
- A region with no mapped boundary is a dot with a soft halo.
- Only the focus country's cities are drawn. A neighbouring country is named once,
  in capitals, and only if the whole name fits inside it.
- Credits go in the bottom-right panel only for maps using attribution-licensed
  data (CC BY, ODbL, Licence Ouverte); they are derived from the input manifest.
- Only regions named in the WSET Level 2 curriculum are annotated.

Check every changed map visually, not just the gate: open the PNG and look at the
labels, leader lines and overlaps.

## Conventions

- Commit each agreed change on its own, with a subject saying what changed on the map.
- This repository is public. Commit messages, docs and comments must not reference
  private trackers, issue keys or other private projects.
- Never push or open a pull request without the maintainer's go; pull requests are
  drafts until they say otherwise.
