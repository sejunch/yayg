"""패키지 아이콘 찾기.

두 갈래로 찾는다.

1. **설치된 패키지** — `pacman -Ql` 로 그 패키지가 소유한
   `/usr/share/applications/*.desktop` 을 찾고 그 안의 `Icon=` 을 읽는다.
   AUR 패키지도 그대로 걸린다.
2. **설치 안 된 저장소 패키지** — `archlinux-appstream-data` 가 깔아 두는
   `/usr/share/swcatalog/icons/<repo>/<크기>/<패키지>_<아이콘>.png` 를 쓴다.
   파일 이름에 패키지명이 들어 있어서 XML 을 파싱할 필요가 없다.

아이콘이 없으면 None 을 돌려주고, 호출한 쪽이 저장소 배지를 대신 보여준다.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

SWCATALOG_ICONS = Path("/usr/share/swcatalog/icons")
LEGACY_ICONS = Path("/usr/share/app-info/icons")
APPLICATIONS = "/usr/share/applications/"
# 큰 것부터 — 먼저 찾은 크기를 쓴다
ICON_SIZES = ("128x128", "64x64", "48x48")


def _desktop_icon_name(path: str) -> str | None:
    """[Desktop Entry] 의 Icon= 값. NoDisplay 항목은 건너뛴다."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            in_entry = False
            icon = None
            for line in handle:
                line = line.strip()
                if line.startswith("["):
                    if in_entry:
                        break               # 다음 섹션 — 여기까지가 [Desktop Entry]
                    in_entry = line == "[Desktop Entry]"
                    continue
                if not in_entry:
                    continue
                if line.startswith("NoDisplay=") and line[10:].lower() == "true":
                    return None
                if line.startswith("Icon=") and icon is None:
                    icon = line[5:].strip()
            return icon or None
    except OSError:
        return None


class IconIndex:
    """패키지 이름 -> 아이콘 이름 또는 파일 경로.

    ensure() 는 여러 번 불러도 한 번만 만든다. 워커 스레드에서 부를 것.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._ready = False
        self._themed: dict[str, str] = {}    # 패키지 -> 아이콘 테마 이름
        self._files: dict[str, str] = {}     # 패키지 -> 아이콘 파일 절대 경로

    @property
    def ready(self) -> bool:
        return self._ready

    def ensure(self) -> None:
        with self._lock:
            if self._ready:
                return
            self._build_appstream()
            self._build_desktop()
            self._ready = True

    # -- 설치 안 된 저장소 패키지 ---------------------------------------------

    def _build_appstream(self) -> None:
        root = SWCATALOG_ICONS if SWCATALOG_ICONS.is_dir() else LEGACY_ICONS
        if not root.is_dir():
            return
        try:
            repos = list(root.iterdir())
        except OSError:
            return
        for repo in repos:
            for size in ICON_SIZES:
                directory = repo / size
                try:
                    entries = os.scandir(directory)
                except OSError:
                    continue
                with entries:
                    for entry in entries:
                        # <패키지>_<아이콘이름>.png
                        pkg, sep, _ = entry.name.partition("_")
                        if sep and pkg not in self._files:
                            self._files[pkg] = entry.path

    # -- 설치된 패키지 --------------------------------------------------------

    def _build_desktop(self) -> None:
        try:
            proc = subprocess.run(
                ["pacman", "-Ql"], capture_output=True, text=True,
                errors="replace", timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        if proc.returncode != 0:
            return

        owners: dict[str, list[str]] = {}
        for line in proc.stdout.splitlines():
            pkg, sep, path = line.partition(" ")
            if not sep or not path.startswith(APPLICATIONS) or not path.endswith(".desktop"):
                continue
            owners.setdefault(pkg, []).append(path)

        for pkg, paths in owners.items():
            # 이름이 패키지명과 가장 비슷한 .desktop 을 먼저 본다
            # (한 패키지가 여러 개를 깔면 보통 주 항목이 그렇다)
            paths.sort(key=lambda p: (pkg not in Path(p).stem, len(p)))
            for path in paths:
                if icon := _desktop_icon_name(path):
                    if icon.startswith("/"):
                        if os.path.exists(icon):
                            self._files.setdefault(pkg, icon)
                            break
                    else:
                        self._themed[pkg] = icon
                        break

    # -- 조회 ---------------------------------------------------------------

    def invalidate(self) -> None:
        """설치/삭제 뒤에는 .desktop 목록이 달라지므로 다시 만들게 한다."""
        with self._lock:
            self._ready = False
            self._themed.clear()
            self._files.clear()

    def file_icon(self, name: str) -> str | None:
        """테마 아이콘을 못 찾았을 때 쓸 appstream 파일 경로."""
        return self._files.get(name)

    def lookup(self, name: str) -> tuple[str, str] | None:
        """('themed', 아이콘이름) 또는 ('file', 경로). 없으면 None."""
        if not self._ready:
            return None
        if icon := self._themed.get(name):
            return ("themed", icon)
        if path := self._files.get(name):
            return ("file", path)
        return None


_index = IconIndex()


def index() -> IconIndex:
    return _index
