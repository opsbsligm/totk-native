"""Production ImGui event regression: staged touch chrome and collapsed drag."""
from pathlib import Path
import shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
class SidebarEvents(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'),'C++ compiler required')
    def test_stages_bounds_drag_and_capture(self):
        host=ROOT/('src/host' if (ROOT/'src/host').is_dir() else 'runtime')
        imgui=ROOT/'third_party/imgui'
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            exe=Path(d)/'sidebar-events'
            subprocess.run(['c++','-std=c++17','-DIMGUI_ENABLE_TEST_ENGINE','-I',str(host),'-I',str(imgui),str(ROOT/'tests/native_sidebar_test.cpp'),*[str(imgui/n) for n in ('imgui.cpp','imgui_draw.cpp','imgui_tables.cpp','imgui_widgets.cpp')],'-o',str(exe)],check=True,timeout=180)
            subprocess.run([str(exe)],check=True,timeout=30)
