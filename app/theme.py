"""Follow the desktop palette without modifying desktop configuration."""
import os
import re
import tomllib
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


def mix(first, second, amount):
    a, b = QColor(first), QColor(second)
    return QColor(*(round(x * (1 - amount) + y * amount)
                    for x, y in zip(a.getRgb()[:3], b.getRgb()[:3]))).name()


def luminance(color):
    values = [v / 255 for v in QColor(color).getRgb()[:3]]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))


def contrast(first, second):
    a, b = sorted((luminance(first), luminance(second)))
    return (b + .05) / (a + .05)


def readable(color, background, minimum=4.5):
    if contrast(color, background) >= minimum:
        return color
    target = '#ffffff' if contrast('#ffffff', background) > contrast('#000000', background) else '#000000'
    for step in range(1, 21):
        adjusted = mix(color, target, step / 20)
        if contrast(adjusted, background) >= minimum:
            return adjusted
    return target


def color_value(data, *keys, default):
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            return value.lower()
    return default


def palette_colors(palette, data=None):
    data = data or {}
    role = QPalette.ColorRole
    bg = color_value(data, 'background', 'bg', 'color0', default=palette.color(role.Window).name())
    fg = color_value(data, 'foreground', 'fg', 'color7', default=palette.color(role.WindowText).name())
    fg = readable(fg, bg)
    surface = color_value(data, 'lighter_background', 'lighter_bg', default=mix(bg, fg, .07))
    card = color_value(data, 'dark_background', 'dark_bg', default=mix(bg, fg, .025))
    accent = color_value(data, 'accent', 'blue', 'color4', default=palette.color(role.Highlight).name())
    colors = {
        'bg': bg, 'bg_light': mix(bg, fg, .035), 'bg_card': card,
        'surface': surface, 'surfaceHover': color_value(data, 'selection', 'selection_background', default=mix(surface, fg, .07)),
        'border': mix(bg, fg, .25), 'text': readable(fg, surface),
        'textDim': readable(color_value(data, 'dark_foreground', 'dark_fg', default=mix(bg, fg, .65)), surface),
        'textMuted': readable(mix(bg, fg, .5), surface, 3),
        'accent': readable(accent, surface),
        'green': readable(color_value(data, 'green', 'color2', default='#438a53'), surface),
        'greenBright': readable(color_value(data, 'bright_green', 'color10', 'green', default='#4eaa70'), surface),
        'orange': readable(color_value(data, 'orange', 'yellow', 'color3', default='#b37719'), surface),
        'red': readable(color_value(data, 'red', 'color1', default='#cb3a48'), surface),
        'purple': readable(color_value(data, 'magenta', 'purple', 'color5', default='#965aa6'), surface),
        'cyan': readable(color_value(data, 'cyan', 'color6', default='#248c9a'), surface),
    }
    colors['pink'] = colors['purple']
    for key in ('green', 'orange', 'red', 'accent'):
        colors[key + 'Dim'] = mix(card, colors[key], .1)
        colors[key] = readable(colors[key], colors[key + 'Dim'])
    colors['greenBright'] = readable(colors['greenBright'], colors['greenDim'])
    colors['accentHover'] = mix(colors['accent'], fg, .18)
    colors['activeRow'] = mix(card, colors['green'], .05)
    colors['activeBorder'] = colors['green']
    colors['onAccent'] = '#ffffff' if contrast('#ffffff', colors['accent']) > contrast('#000000', colors['accent']) else '#000000'
    colors['onGreen'] = '#ffffff' if contrast('#ffffff', colors['green']) > contrast('#000000', colors['green']) else '#000000'
    return colors


C = palette_colors(QPalette())
T = {key: '@' + key + '@' for key in C}


def render_style(template):
    for key, value in C.items():
        template = template.replace('@' + key + '@', value)
    return template


def theme_style(widget, template):
    widget.setProperty('projectMonitorStyle', template)
    widget.setStyleSheet(render_style(template))


def theme_paths():
    home = Path.home()
    state = Path(os.environ.get('XDG_STATE_HOME') or home / '.local/state')
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    return [state / 'omarchy/current/theme/colors.toml',
            config / 'omarchy/current/theme/colors.toml']


class DesktopTheme(QObject):
    changed = pyqtSignal()

    def __init__(self, app, paths=None):
        super().__init__(app)
        self.app = app
        self.paths = theme_paths() if paths is None else paths
        self.system_palette = QPalette(app.palette())
        self.applying = False
        self.source = 'System'
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        app.paletteChanged.connect(self._system_changed)
        self.refresh()
        self.timer.start()

    def _system_changed(self, palette):
        if not self.applying:
            self.system_palette = QPalette(palette)
            self.refresh()

    def refresh(self):
        data = None
        for path in self.paths:
            try:
                raw = Path(path).read_bytes()
                if len(raw) > 65536:
                    continue
                candidate = tomllib.loads(raw.decode())
                if not color_value(candidate, 'background', 'bg', 'color0', default=''):
                    continue
                data = candidate
                self.source = 'Omarchy'
                break
            except (OSError, ValueError, UnicodeError):
                continue
        # Omarchy replaces the entire theme directory. Keep the last valid
        # palette while the new directory is being staged, including bad edits.
        if data is None and self.source == 'Omarchy':
            return
        colors = palette_colors(self.system_palette, data)
        if colors == C:
            return
        C.update(colors)
        self.applying = True
        try:
            palette = QPalette(self.system_palette)
            for role, key in ((QPalette.ColorRole.Window, 'bg'), (QPalette.ColorRole.Base, 'bg_card'),
                              (QPalette.ColorRole.WindowText, 'text'), (QPalette.ColorRole.Text, 'text'),
                              (QPalette.ColorRole.Button, 'surface'), (QPalette.ColorRole.ButtonText, 'text'),
                              (QPalette.ColorRole.Highlight, 'accent'), (QPalette.ColorRole.HighlightedText, 'onAccent'),
                              (QPalette.ColorRole.ToolTipBase, 'bg_light'), (QPalette.ColorRole.ToolTipText, 'text')):
                palette.setColor(role, QColor(C[key]))
            self.app.setPalette(palette)
            for widget in self.app.allWidgets():
                template = widget.property('projectMonitorStyle')
                if template is not None:
                    widget.setStyleSheet(render_style(template))
                    widget.update()
            self.changed.emit()
        finally:
            self.applying = False


def desktop_theme():
    app = QApplication.instance()
    if not hasattr(app, '_project_monitor_theme'):
        app._project_monitor_theme = DesktopTheme(app)
    return app._project_monitor_theme
