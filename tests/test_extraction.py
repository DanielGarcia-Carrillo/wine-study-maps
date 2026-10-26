from pathlib import Path
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import render_maps
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
