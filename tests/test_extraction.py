import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_maps  # noqa: E402 -- standalone scripts are loaded after adding their directory
import source_geodata as geo  # noqa: E402 -- standalone scripts are loaded after adding their directory
from models import InputManifest  # noqa: E402 -- standalone scripts are loaded after adding their directory
from snapshots import prepare  # noqa: E402 -- standalone scripts are loaded after adding their directory
from validation import COLOURS, load_manifest, read_json  # noqa: E402 -- standalone scripts are loaded after adding their directory


class ExtractionTests(unittest.TestCase):
    def test_reviewed_palette_and_unknown_colour(self) -> None:
        colours = read_json(ROOT / "data/label-colours.json", COLOURS)
        for key, expected in colours.items():
            fill, bg, target = key.split("|")
            self.assertEqual(render_maps.readable(fill, bg, float(target)), expected)
        with self.assertRaisesRegex(ValueError, "Unreviewed label colour"):
            render_maps.readable("#abcdef", "#ffffff")

    def test_attribution_licences_are_credited_on_their_maps(self) -> None:
        credits = render_maps.credit_lines()
        self.assertIn("OpenStreetMap", credits["wset-map-chile.svg"])
        self.assertIn("OpenStreetMap", credits["wset-map-chile-blank.png"])
        self.assertIn("Regione Piemonte", credits["wset-map-piemonte.svg"])
        self.assertIn("Wine Australia", credits["wset-map-victoria.png"])
        self.assertIn("2025-10-09", credits["wset-map-bordeaux.svg"])
        # Natural Earth, Wikidata and CC0 inputs alone need no on-image credit.
        self.assertNotIn("wset-map-napa.svg", credits)
        svg = (ROOT / "assets/wset-map-chile.svg").read_text(encoding="utf-8")
        self.assertIn(f'class="credit">{credits["wset-map-chile.svg"]}<', svg)

    def fixture(self, root: Path) -> tuple[Path, InputManifest]:
        manifest = load_manifest(ROOT)
        manifest["inputs"] = manifest["inputs"][:1]
        row = manifest["inputs"][0]
        path = root / "data" / row["path"]
        path.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "data" / row["path"], path)
        (root / "data/input-manifest.json").write_text(json.dumps(manifest))
        return path, manifest

    def test_changed_committed_input_fails_despite_valid_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, manifest = self.fixture(root)
            prepare(root)
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "Source checksum mismatch"):
                prepare(root)

    def test_missing_or_unexpected_committed_input_fails_despite_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, manifest = self.fixture(root)
            prepare(root)
            original = path.read_bytes()
            path.unlink()
            with self.assertRaisesRegex(FileNotFoundError, "missing="):
                prepare(root)
            path.write_bytes(original)
            path.with_name("unexpected.json").write_text("{}")
            with self.assertRaisesRegex(FileNotFoundError, "unexpected="):
                prepare(root)

    def test_unsafe_input_path_or_symlink_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, manifest = self.fixture(root)
            path.unlink()
            path.symlink_to(ROOT / "data" / manifest["inputs"][0]["path"])
            with self.assertRaisesRegex(ValueError, "[Uu]nsafe.*path"):
                prepare(root)
            manifest["inputs"][0]["path"] = "inputs/../../outside.json"
            (root / "data/input-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "[Uu]nsafe.*path"):
                prepare(root)

    def test_stale_cache_is_only_derived_from_committed_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, manifest = self.fixture(root)
            cache = prepare(root)
            stale = cache / ".inao-cache/orphan.json"
            stale.write_text("{}")
            current = cache / manifest["inputs"][0]["cache_path"]
            current.write_text("changed cache")
            prepare(root)
            self.assertFalse(stale.exists())
            self.assertEqual(current.read_bytes(), path.read_bytes())

    def test_projection_origins_and_independent_pdo_towns(self) -> None:
        lon, lat = geo.utm_to_wgs84(500000, 0, zone=32)
        self.assertAlmostEqual(lon, 9, places=7)
        self.assertAlmostEqual(lat, 0, places=7)
        lon, lat = geo.laea_to_wgs84(4321000, 3210000)
        self.assertAlmostEqual(lon, 10, places=7)
        self.assertAlmostEqual(lat, 52, places=7)
        near_lon, near_lat = geo.laea_to_wgs84(4321000.001, 3210000.001)
        self.assertAlmostEqual(near_lon, 10, places=6)
        self.assertAlmostEqual(near_lat, 52, places=6)
        self.assertGreater(near_lon, lon)
        self.assertGreater(near_lat, lat)
        prepare()
        for pdo_id, points in geo.PDO_CONTROL.items():
            area = geo.pdo_area(pdo_id)
            for point in points:
                self.assertTrue(geo.in_rings(list(point), area["rings"]), pdo_id)

    def test_refresh_populates_separate_maintenance_cache(self) -> None:
        import yaml

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "catalogue.yaml"
            spec.write_text(
                yaml.safe_dump(
                    {
                        "maps": [
                            {
                                "id": "sample",
                                "base": ["land"],
                                "regions": [{"name": "Sample", "wikidata": "Q1"}],
                            }
                        ]
                    }
                )
            )
            (root / ".cache").mkdir()
            marker = root / ".cache" / "pinned-marker"
            marker.write_text("pinned")
            with (
                patch.multiple(
                    geo,
                    ROOT=root,
                    SPEC=spec,
                    MAPS=geo.MAPS,
                    NE_CACHE=geo.NE_CACHE,
                    WD_CACHE=geo.WD_CACHE,
                    INAO_CACHE=geo.INAO_CACHE,
                    REFRESH=False,
                ),
                patch.object(sys, "argv", ["source_geodata", "--refresh"]),
                patch.object(geo, "verify", return_value=0),
                patch.object(geo, "curl", return_value='{"features": []}') as fetch,
                patch(
                    "snapshots.prepare",
                    side_effect=AssertionError("pinned cache must be untouched"),
                ),
            ):
                self.assertEqual(geo.main(), 0)
                self.assertEqual(fetch.call_count, 1)
                self.assertTrue(
                    (root / ".maintenance-cache/.naturalearth-cache" / geo.LAYERS["land"]).is_file()
                )
                self.assertEqual(marker.read_text(), "pinned")

    def test_png_requires_cairo(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(sys, "argv", ["render_maps", "--only", "bordeaux", "--out", tmp]),
            patch.object(render_maps, "load_cairosvg", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "PNG output requires"):
                render_maps.main()

    def test_contact_sheet_requires_every_tile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FileNotFoundError, "requires every map PNG"):
                render_maps.contact_sheet(["missing"], Path(tmp))


if __name__ == "__main__":
    unittest.main()
