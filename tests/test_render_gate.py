"""A previous complete render must never mask omissions in a new invocation."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_render  # noqa: E402 -- standalone script module


class RenderGateTests(unittest.TestCase):
    def test_stale_outputs_do_not_hide_no_write_or_partial_renderer(self) -> None:
        for omit_one in (False, True):
            with self.subTest(omit_one=omit_one), tempfile.TemporaryDirectory() as tmp:
                stale = Path(tmp).resolve() / "prior-output"
                shutil.copytree(ROOT / "assets", stale)
                before = (stale / "level-2-france.png").read_bytes()

                def incomplete(
                    command: list[str], *, produce_partial: bool = omit_one, **kwargs: object
                ) -> subprocess.CompletedProcess[bytes]:
                    if produce_partial:
                        fresh = Path(command[command.index("--out") + 1])
                        fresh.mkdir()
                        for image in (ROOT / "assets").iterdir():
                            if image.name != "level-2-france.png":
                                shutil.copyfile(image, fresh / image.name)
                    return subprocess.CompletedProcess(command, 0)

                with (
                    patch.object(sys, "argv", ["validate_render", "--out", str(stale)]),
                    patch.object(subprocess, "run", side_effect=incomplete),
                    self.assertRaisesRegex(
                        ValueError, "renderer did not create output|rendered inventory differs"
                    ),
                ):
                    validate_render.main()
                self.assertEqual((stale / "level-2-france.png").read_bytes(), before)
                self.assertEqual(len(list(stale.iterdir())), 129)

    def test_output_symlink_is_rejected_without_running_or_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp).resolve() / "real"
            real.mkdir()
            sentinel = real / "sentinel"
            sentinel.write_text("keep")
            alias = Path(tmp).resolve() / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with (
                patch.object(sys, "argv", ["validate_render", "--out", str(alias)]),
                patch.object(subprocess, "run") as renderer,
                self.assertRaisesRegex(ValueError, "symlink"),
            ):
                validate_render.main()
            renderer.assert_not_called()
            self.assertEqual(sentinel.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
