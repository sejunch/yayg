"""워커 스레드 헬퍼."""

from __future__ import annotations

import threading
from itertools import count

from gi.repository import GLib

_tokens = count(1)


def new_token() -> int:
    """진행 중인 비동기 작업을 무효화하기 위한 세대 번호."""
    return next(_tokens)


def run_async(fn, on_done, *args):
    """fn(*args)를 백그라운드에서 실행하고 on_done(result, error)을 UI 스레드에서 호출한다."""

    def worker():
        try:
            result, error = fn(*args), None
        except Exception as exc:  # 백엔드 오류는 UI에서 토스트로 보여준다
            result, error = None, exc
        GLib.idle_add(on_done, result, error, priority=GLib.PRIORITY_DEFAULT_IDLE)

    threading.Thread(target=worker, daemon=True).start()


# -- 아이콘 이름 --------------------------------------------------------------
# Adwaita와 Breeze 등 아이콘 테마마다 가진 이름이 달라서, 실제로 존재하는
# 첫 번째 후보를 골라 쓴다. (표시는 GDK 디스플레이가 열린 뒤에만 조회 가능)

_icon_cache: dict[tuple, str] = {}


def pick_icon(*names: str, default: str = "dialog-information-symbolic") -> str:
    if names in _icon_cache:
        return _icon_cache[names]

    from gi.repository import Gdk, Gtk

    chosen = default
    display = Gdk.Display.get_default()
    if display is not None:
        theme = Gtk.IconTheme.get_for_display(display)
        for name in names:
            if theme.has_icon(name):
                chosen = name
                break
    _icon_cache[names] = chosen
    return chosen


def package_icon() -> str:
    return pick_icon("package-x-generic-symbolic", "package-symbolic",
                     "application-x-executable-symbolic")


def update_icon() -> str:
    return pick_icon("software-update-available-symbolic", "system-upgrade-symbolic",
                     "emblem-synchronizing-symbolic", "view-refresh-symbolic")
