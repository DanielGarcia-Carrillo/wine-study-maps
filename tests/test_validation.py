"""Boundary failures derived from realistic catalogue, provenance and provider mistakes."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validation import (  # noqa: E402 -- standalone script modules
    ASSETS,
    COLOURS,
    INPUT_MANIFEST,
    catalogue_value,
    load_manifest,
    read_area,
    read_features,
    validate,
)


class ValidationTests(unittest.TestCase):
    def test_unknown_keys_types_references_and_finite_numbers(self) -> None:
        invalid: list[tuple[object, str]] = [
            ({"maps": [], "chapters": []}, "chapters"),
            (
                {
                    "maps": [
                        {
                            "id": "sample",
                            "regions": [{"name": "Sample", "wikidata": "Q1", "tier": False}],
                        }
                    ]
                },
                "tier",
            ),
            (
                {
                    "maps": [
                        {
                            "id": "sample",
                            "regions": [{"name": "Sample", "wikidata": "Q1", "colour": "red"}],
                        }
                    ]
                },
                "colour",
            ),
            (
                {
                    "maps": [
                        {
                            "id": "sample",
                            "regions": [
                                {"name": "Sample", "wikidata": "Q1", "region_of": "missing"}
                            ],
                        }
                    ]
                },
                "region_of",
            ),
            (
                {
                    "maps": [
                        {
                            "id": "sample",
                            "regions": [{"name": "Sample", "wikidata": "Q1", "parent": "Missing"}],
                        }
                    ]
                },
                "parent",
            ),
            (
                {
                    "maps": [
                        {
                            "id": "sample",
                            "regions": [{"name": "Sample", "wikidata": "Q1"}],
                            "pad": float("nan"),
                        }
                    ]
                },
                "non-finite",
            ),
        ]
        for value, field in invalid:
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "example.yaml:.*" + field),
            ):
                catalogue_value(value, "example.yaml")

    def test_manifests_and_palette_are_real_structural_contracts(self) -> None:
        with self.assertRaisesRegex(ValueError, "assets.json:.*"):
            validate({"../../outside.png": "not-a-hash"}, ASSETS, "assets.json")
        with self.assertRaisesRegex(ValueError, "colours.json:.*"):
            validate({"unreviewed": "#123456"}, COLOURS, "colours.json")
        with self.assertRaisesRegex(ValueError, "manifest.json:.*inputs"):
            validate(
                {"acquired_at": None, "acquisition_note": "Unknown", "inputs": "not a list"},
                INPUT_MANIFEST,
                "manifest.json",
            )
        manifest = load_manifest(ROOT)
        manifest["inputs"][0]["cache_path"] = "../../outside.json"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/input-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "cache_path.*unsafe"):
                load_manifest(root)

    def test_area_and_geojson_reject_malformed_coordinates_with_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "area.json"
            path.write_text(
                json.dumps(
                    {
                        "name": "Example",
                        "communes": 0,
                        "missing": [],
                        "rings": [[[1, 2], [3, "north"], [5, 6]]],
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "area.json:.*rings.0.1.1"):
                read_area(path)
            path.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {},
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [[[0, 0], [1, 1], [2, 0], [0, 0]]],
                                },
                            }
                        ],
                    }
                )
            )
            data = read_features(path)
            self.assertEqual(len(data["features"]), 1)
            path.write_text(path.read_text().replace("[1, 1]", "[181, 1]"))
            with self.assertRaisesRegex(ValueError, "area.json:.*coordinates.*longitude/latitude"):
                read_features(path)

    def test_upstream_foreign_members_and_empty_geometry_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider.geojson"
            path.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "provider_metadata": {"licence": "example", "revision": 2},
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {"unknown_attribute": [1, "two", None], "NAME": None},
                                "geometry": {"type": "MultiLineString", "coordinates": []},
                            }
                        ],
                    }
                )
            )
            data = read_features(path)
            # Foreign members are retained at runtime, without assigning them fixed provider schemas.
            self.assertIn("provider_metadata", data)
            self.assertIn("unknown_attribute", data["features"][0]["properties"])
            path.write_text(path.read_text().replace('"revision": 2', '"revision": NaN'))
            with self.assertRaisesRegex(ValueError, "provider_metadata.revision.*non-finite"):
                read_features(path)


if __name__ == "__main__":
    unittest.main()
