from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import render_maps
import source_geodata as geo
from snapshots import prepare

class ExtractionTests(unittest.TestCase):
    def test_reviewed_palette_and_unknown_colour(self):
        colours = json.loads((ROOT / 'data/label-colours.json').read_text())
        for key, expected in colours.items():
            fill, bg, target = key.split('|')
            self.assertEqual(render_maps.readable(fill, bg, float(target)), expected)
        with self.assertRaisesRegex(ValueError, 'Unreviewed label colour'):
            render_maps.readable('#abcdef', '#ffffff')

    def test_corrupt_archive_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            shutil.copy(ROOT / 'data/input-manifest.json', root / 'data')
            (root / 'data/map-inputs.tar.gz').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'archive checksum mismatch'):
                prepare(root)

    def test_missing_and_modified_input_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            for name in ('input-manifest.json', 'map-inputs.tar.gz'):
                (root / 'data' / name).symlink_to(ROOT / 'data' / name)
            prepare(root)
            row = json.loads((root / 'data/input-manifest.json').read_text())['inputs'][0]
            path = root / '.cache' / row['path']
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'Source checksum mismatch'):
                prepare(root)
            path.unlink()
            with self.assertRaisesRegex(FileNotFoundError, 'Missing pinned source input'):
                prepare(root)

    def test_projection_origins_and_independent_pdo_towns(self):
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
                self.assertTrue(geo.in_rings(list(point), area['rings']), pdo_id)

    def test_refresh_populates_separate_maintenance_cache(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / 'catalogue.yaml'
            spec.write_text(yaml.safe_dump({'maps': [{'id': 'sample', 'base': ['land'], 'regions': []}]}))
            (root / '.cache').mkdir()
            marker = root / '.cache' / 'pinned-marker'
            marker.write_text('pinned')
            with patch.multiple(geo, ROOT=root, SPEC=spec, MAPS=geo.MAPS, NE_CACHE=geo.NE_CACHE, WD_CACHE=geo.WD_CACHE, INAO_CACHE=geo.INAO_CACHE, REFRESH=False), patch.object(sys, 'argv', ['source_geodata', '--refresh']), patch.object(geo, 'curl', return_value='{"features": []}') as fetch, patch('snapshots.prepare', side_effect=AssertionError('pinned cache must be untouched')):
                self.assertEqual(geo.main(), 0)
                self.assertEqual(fetch.call_count, 1)
                self.assertTrue((root / '.maintenance-cache/.naturalearth-cache' / geo.LAYERS['land']).is_file())
                self.assertEqual(marker.read_text(), 'pinned')

    def test_png_requires_cairo(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sys, 'argv', ['render_maps', '--only', 'bordeaux', '--out', tmp]), patch.object(render_maps, 'load_cairosvg', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'PNG output requires'):
                render_maps.main()

    def test_contact_sheet_requires_every_tile(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FileNotFoundError, 'requires every map PNG'):
                render_maps.contact_sheet(['missing'], Path(tmp))

if __name__ == '__main__':
    unittest.main()
