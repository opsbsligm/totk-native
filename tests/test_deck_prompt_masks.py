"""Actual authored HUD masks preserve gameplay and menu face-button semantics."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
class PromptMasks(unittest.TestCase):
    def test_context_labels_shape_bounds_and_coverage(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            exe=Path(d)/'prompt-masks'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'src/gfx'),str(ROOT/'tests/deck_prompt_masks_test.c'),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=15)
