"""The control bar must speak the language the game was told to speak."""
from pathlib import Path
import shutil, subprocess, tempfile, unittest

ROOT = Path(__file__).resolve().parents[1]


class ControlBarLanguage(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_the_panel_follows_the_games_own_language_choice(self):
        source = (ROOT / 'src/host/overrides_oe.c').read_text(encoding='utf-8')
        start = source.index("/* The game's language:")
        end = source.index('    return cached;\n}\n', start) + len('    return cached;\n}\n')
        body = source[start:end]
        harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdint.h>
void runtime_fail(const char *message) { fprintf(stderr, "%s\n", message); abort(); }
'''
        main = r'''
/* runtime_language_chinese() caches for the whole run, exactly like the font atlas it feeds,
   so every case gets its own process. */
static const struct { const char *lang, *locale; int expect; } cases[] = {
    {"zh-Hans", NULL, 1}, {"zh-Hant", NULL, 1}, {"en-US", NULL, 0}, {"ja", NULL, 0},
    {NULL, "zh_CN.UTF-8", 1}, {NULL, "en_US.UTF-8", 0}, {NULL, "de_DE.UTF-8", 0},
    {"ja", "zh_CN.UTF-8", 0},   // an explicit code wins over the locale
};
int main(int argc, char **argv) {
    if (argc != 2) return 100;
    const int n = (int)(sizeof cases / sizeof cases[0]);
    int index = atoi(argv[1]);
    if (index < 0 || index >= n) return 101;
    if (cases[index].lang) setenv("TOTK_LANG", cases[index].lang, 1); else unsetenv("TOTK_LANG");
    if (cases[index].locale) setenv("TOTK_LOCALE", cases[index].locale, 1); else unsetenv("TOTK_LOCALE");
    unsetenv("LANG"); unsetenv("LC_ALL"); unsetenv("LC_MESSAGES");
    if (runtime_language_chinese() != cases[index].expect) return index + 1;
    uint64_t game = desired_language();
    char code[9] = {0};
    memcpy(code, &game, 8);
    if ((code[0] == 'z' && code[1] == 'h') != cases[index].expect) return 50;   // the game sees the same thing
    if (runtime_language_chinese() != cases[index].expect) return 51;           // cached, and stable
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='totk-lang-', dir=Path.cwd()) as folder:
            path = Path(folder) / 'lang.c'
            binary = Path(folder) / 'lang'
            path.write_text(harness + body + main, encoding='utf-8')
            compile = subprocess.run(['cc', '-std=gnu17', '-O1', '-w', str(path), '-o', str(binary)],
                                     capture_output=True, text=True, timeout=60)
            self.assertEqual(compile.returncode, 0, compile.stderr)
            for case in range(8):
                with self.subTest(case=case):
                    result = subprocess.run([str(binary), str(case)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_panel_asks_the_runtime_rather_than_its_own_copy(self):
        bar = (ROOT / 'src/host/control_bar.cpp').read_text(encoding='utf-8')
        self.assertIn('chinese=runtime_language_chinese()!=0;', bar)
        self.assertNotIn('getenv("TOTK_LANG")', bar)


if __name__ == '__main__':
    unittest.main()
