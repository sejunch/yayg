"""설정 저장. ~/.config/yayg/settings.json 에 담는다.

GSettings 를 쓰면 스키마를 컴파일해 설치해야 해서, 소스에서 바로 실행한다는
전제와 맞지 않는다. 그래서 평범한 JSON 파일을 쓴다. GTK 의존성 없음.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

DEFAULTS: dict = {
    # 일반
    "color_scheme": "system",           # system | light | dark
    "show_package_icons": True,         # 목록에 앱 아이콘 표시
    "show_screenshots": False,          # 상세 패널 스크린샷 (외부 사이트 접속)
    "start_page": "search",             # search | installed | updates
    "check_updates_on_start": True,

    # 설치 및 빌드
    "pkgbuild_preview": True,           # AUR 설치 전에 PKGBUILD 를 보여준다
    "removal_preview": True,            # 삭제 전에 연쇄 제거 대상을 보여준다
    "check_news_before_upgrade": True,  # 전체 업그레이드 전에 Arch 공지 확인
    "remove_make_deps": False,          # --removemake
    "clean_after_build": False,         # --cleanafter
    "devel_updates": False,             # --devel (-git 등 커밋 기준 확인)

    # 삭제
    "remove_mode": "Rns",               # Rns | Rs | R

    # 업데이트 확인
    "update_source": "checkupdates",    # checkupdates | yay
    "include_aur_updates": True,

    # 검색
    "include_aur_search": True,
    "search_limit": 100,                # 0 = 제한 없음

    # 고급
    "extra_args": "",
}

_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "yayg" / "settings.json"


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or _PATH
        self._data = dict(DEFAULTS)
        self._listeners: list = []
        self.load()

    # -- 접근 ---------------------------------------------------------------

    def __getitem__(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self.save()
        for callback in list(self._listeners):
            callback(key, value)

    def connect(self, callback) -> None:
        """callback(key, value) — 값이 바뀔 때마다 호출된다."""
        self._listeners.append(callback)

    def disconnect(self, callback) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def reset(self) -> None:
        for key, value in DEFAULTS.items():
            self.set(key, value)

    # -- 파일 ---------------------------------------------------------------

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        # 모르는 키는 버리고, 타입이 다른 값도 기본값으로 되돌린다.
        for key, default in DEFAULTS.items():
            value = raw.get(key, default)
            if isinstance(default, bool) and not isinstance(value, bool):
                value = default
            elif isinstance(default, int) and not isinstance(default, bool) \
                    and not isinstance(value, int):
                value = default
            elif isinstance(default, str) and not isinstance(value, str):
                value = default
            self._data[key] = value

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False) + "\n")
            tmp.replace(self.path)
        except OSError:
            pass  # 설정을 저장하지 못해도 앱은 계속 동작한다

    # -- yay 인자로 변환 ------------------------------------------------------

    def extra_argv(self) -> list[str]:
        try:
            return shlex.split(self._data.get("extra_args") or "")
        except ValueError:
            return []

    def build_flags(self) -> list[str]:
        """사용자가 켠 빌드 옵션만. diff/편집 메뉴를 끄는 플래그는 yay 버전마다
        이름이 달라서 runner 가 붙인다."""
        flags = []
        if self["remove_make_deps"]:
            flags.append("--removemake")
        if self["clean_after_build"]:
            flags.append("--cleanafter")
        return flags

    def remove_flag(self) -> str:
        mode = self["remove_mode"]
        return mode if mode in ("Rns", "Rs", "R") else "Rns"
