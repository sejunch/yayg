"""애플리케이션 진입점."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio

from .settings import Settings
from .window import YaygWindow

APP_ID = "io.github.sejunch.yayg"

_SCHEMES = {
    "system": Adw.ColorScheme.DEFAULT,
    "light": Adw.ColorScheme.FORCE_LIGHT,
    "dark": Adw.ColorScheme.FORCE_DARK,
}


class YaygApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.settings = Settings()
        self.settings.connect(self._on_setting_changed)
        self.window = None

    def do_activate(self):
        self._apply_color_scheme()
        if self.window is None:
            self.window = YaygWindow(self, self.settings)
        self.window.present()

    def _apply_color_scheme(self):
        scheme = _SCHEMES.get(self.settings["color_scheme"], Adw.ColorScheme.DEFAULT)
        Adw.StyleManager.get_default().set_color_scheme(scheme)

    def _on_setting_changed(self, key, _value):
        if key == "color_scheme":
            self._apply_color_scheme()


def main(argv=None) -> int:
    return YaygApp().run(argv if argv is not None else sys.argv)
