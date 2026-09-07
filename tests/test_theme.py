import tempfile
import time
import unittest
from pathlib import Path

from PyQt6.QtGui import QColor, QPalette
from tests import test_switch
from app.theme import C, contrast, palette_colors
from ui import AddAccountDialog

DARK = 'background = "#111c18"\nforeground = "#c1c497"\naccent = "#509475"\n'
LIGHT = 'background = "#eff1f5"\nforeground = "#4c4f69"\naccent = "#1e66f5"\ngreen = "#40a02b"\n'


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.f = test_switch.SwitchIntegrationTests()
        self.f.setUpClass(); self.f.setUp()
        self.theme = self.f.window.theme
        self.paths = self.theme.paths
        self.source = self.theme.source
        self.system_palette = QPalette(self.theme.system_palette)
        self.theme.timer.stop()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'colors.toml'
        self.path.write_text(DARK)
        self.theme.paths = [self.path]
        self.theme.refresh()

    def tearDown(self):
        self.theme.timer.stop()
        self.theme.paths = self.paths
        self.theme.source = self.source
        self.theme.system_palette = self.system_palette
        self.theme.refresh()
        self.theme.timer.setInterval(1000)
        self.theme.timer.start()
        self.f.tearDown()
        self.temp.cleanup()

    def test_atomic_theme_change_updates_existing_window_and_dialog(self):
        f = self.f
        f.window.rotation_mode.setCurrentIndex(1)
        f.window.table.selectRow(1)
        selected = f.window._selected_id
        dialog = AddAccountDialog(f.window)
        dialog.name_input.setText('Unfinished account entry')
        original_button = f.window.btn_next.styleSheet()
        replacement = self.path.with_suffix('.new')
        replacement.write_text(LIGHT)
        replacement.replace(self.path)
        self.theme.timer.setInterval(10)
        self.theme.timer.start()
        deadline = time.monotonic() + 1
        while C['bg'] != '#eff1f5' and time.monotonic() < deadline:
            f.app.processEvents(); time.sleep(.01)
        self.assertEqual(C['bg'], '#eff1f5')
        self.assertIn('#eff1f5', f.window.styleSheet())
        self.assertIn('#eff1f5', dialog.styleSheet())
        self.assertNotEqual(original_button, f.window.btn_next.styleSheet())
        self.assertEqual(dialog.name_input.text(), 'Unfinished account entry')
        self.assertEqual(f.window._selected_id, selected)
        self.assertEqual(f.window.rotation_mode.currentData(), 'semi_auto')
        self.assertEqual(f.db.get_active_account()['id'], f.old)
        for widget in f.app.allWidgets():
            if widget.property('projectMonitorStyle') is not None:
                self.assertNotIn('@', widget.styleSheet())
        dialog.deleteLater()

    def test_missing_or_partial_theme_preserves_last_good_colors(self):
        previous = dict(C)
        self.path.unlink(); self.theme.refresh()
        self.assertEqual(C, previous)
        self.path.write_text('background = "unfinished')
        self.theme.refresh()
        self.assertEqual(C, previous)
        self.path.write_text(LIGHT); self.theme.refresh()
        self.assertEqual(C['bg'], '#eff1f5')

    def test_light_and_dark_status_and_button_contrast(self):
        import tomllib
        for data in (DARK, LIGHT):
            colors = palette_colors(QPalette(), tomllib.loads(data))
            for key in ('green', 'orange', 'red', 'accent'):
                self.assertGreaterEqual(contrast(colors[key], colors[key + 'Dim']), 4.5)
            self.assertGreaterEqual(contrast(colors['accent'], colors['onAccent']), 4.5)
            self.assertGreaterEqual(contrast(colors['green'], colors['onGreen']), 4.5)
            self.assertGreaterEqual(contrast(colors['textDim'], colors['surface']), 4.5)

    def test_no_omarchy_uses_and_tracks_system_palette(self):
        self.theme.paths = []
        self.theme.source = 'System'
        palette = QPalette(self.system_palette)
        palette.setColor(QPalette.ColorRole.Window, QColor('#fafafa'))
        palette.setColor(QPalette.ColorRole.WindowText, QColor('#151515'))
        self.theme._system_changed(palette)
        self.assertEqual(C['bg'], '#fafafa')
        palette.setColor(QPalette.ColorRole.Window, QColor('#181818'))
        palette.setColor(QPalette.ColorRole.WindowText, QColor('#eeeeee'))
        self.theme._system_changed(palette)
        self.assertEqual(C['bg'], '#181818')

    def test_legacy_palette_aliases_and_invalid_colors(self):
        colors = palette_colors(QPalette(), {'bg': '#112233', 'fg': '#ffffff',
            'color1': '#ff4455', 'accent': 'red; background: url(bad)'})
        self.assertEqual(colors['bg'], '#112233')
        self.assertNotIn('url', str(colors))


if __name__ == '__main__':
    unittest.main()
