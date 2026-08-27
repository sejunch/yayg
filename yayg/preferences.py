"""설정 창."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk

from . import runner
from .settings import DEFAULTS, Settings


def _switch(settings: Settings, key: str, title: str, subtitle: str = "") -> Adw.SwitchRow:
    row = Adw.SwitchRow(title=title, subtitle=subtitle, active=bool(settings[key]))
    row.connect("notify::active", lambda r, _p: settings.set(key, r.get_active()))
    return row


def _combo(settings: Settings, key: str, title: str,
           options: list[tuple], subtitle: str = "") -> Adw.ComboRow:
    """options: [(저장값, 표시 문구), ...]"""
    values = [value for value, _ in options]
    row = Adw.ComboRow(
        title=title, subtitle=subtitle,
        model=Gtk.StringList.new([label for _, label in options]),
    )
    try:
        row.set_selected(values.index(settings[key]))
    except ValueError:
        row.set_selected(0)
    row.connect("notify::selected",
                lambda r, _p: settings.set(key, values[r.get_selected()]))
    return row


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, settings: Settings):
        super().__init__(title="설정")
        self.settings = settings

        self.add(self._general_page())
        self.add(self._install_page())
        self.add(self._sources_page())
        self.add(self._advanced_page())

        # 창은 열 때마다 새로 만들어지므로, 닫힐 때 청취를 반드시 해제한다.
        settings.connect(self._on_setting_changed)
        self.connect("closed", lambda *_: settings.disconnect(self._on_setting_changed))

    # -- 일반 ---------------------------------------------------------------

    def _general_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(name="general", title="일반",
                                   icon_name="preferences-system-symbolic")

        look = Adw.PreferencesGroup(title="모양")
        look.add(_combo(self.settings, "color_scheme", "색 구성", [
            ("system", "시스템 설정 따르기"),
            ("light", "밝게"),
            ("dark", "어둡게"),
        ]))
        look.add(_switch(
            self.settings, "show_package_icons", "패키지 아이콘 표시",
            "설치된 패키지는 .desktop 항목에서, 저장소 패키지는 "
            "archlinux-appstream-data 에서 아이콘을 찾습니다. "
            "못 찾으면 저장소 이름을 대신 보여줍니다.",
        ))
        look.add(_switch(
            self.settings, "show_screenshots", "상세 패널에 스크린샷 표시",
            "AppStream 은 스크린샷을 로컬에 캐시해 두지 않고 원본 주소만 담고 있어서, "
            "켜면 각 프로젝트 웹사이트에 직접 접속하게 됩니다. "
            "받은 이미지는 ~/.cache/yayg 에 보관합니다.",
        ))
        page.add(look)

        start = Adw.PreferencesGroup(title="시작할 때")
        start.add(_combo(self.settings, "start_page", "처음 보여줄 페이지", [
            ("search", "검색"),
            ("installed", "설치됨"),
            ("updates", "업데이트"),
        ]))
        start.add(_switch(
            self.settings, "check_updates_on_start", "업데이트 자동 확인",
            "끄면 업데이트 페이지에서 직접 확인 버튼을 눌러야 합니다. AUR 조회는 시간이 걸립니다.",
        ))
        page.add(start)
        return page

    # -- 설치 ---------------------------------------------------------------

    def _install_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(name="install", title="설치",
                                   icon_name="folder-download-symbolic")

        review = Adw.PreferencesGroup(
            title="AUR 검토",
            description="AUR 패키지는 미리 빌드된 바이너리가 아니라, 내 컴퓨터에서 "
                        "실행되는 빌드 스크립트입니다. 심사 절차가 없으므로 PKGBUILD가 "
                        "유일한 신뢰 경계입니다.",
        )
        review.add(_switch(
            self.settings, "pkgbuild_preview", "PKGBUILD 미리보기",
            "AUR 패키지를 설치하거나 업그레이드하기 전에 PKGBUILD와 딸린 "
            ".install 스크립트를 먼저 보여줍니다.",
        ))
        review.add(_switch(
            self.settings, "check_news_before_upgrade", "업그레이드 전 Arch 뉴스 확인",
            "마지막 전체 업그레이드 이후 올라온 공지를 먼저 보여줍니다. "
            "수동 개입이 필요한 공지를 놓치는 것이 Arch 에서 가장 흔한 사고입니다.",
        ))
        page.add(review)

        build = Adw.PreferencesGroup(title="빌드")
        build.add(_switch(
            self.settings, "remove_make_deps", "빌드 후 빌드 의존성 제거",
            "yay --removemake — 빌드에만 쓰인 패키지를 끝나고 지웁니다.",
        ))
        build.add(_switch(
            self.settings, "clean_after_build", "빌드 후 작업 디렉터리 정리",
            "yay --cleanafter — ~/.cache/yay 를 비웁니다. 다음 빌드가 느려집니다.",
        ))
        build.add(_switch(
            self.settings, "devel_updates", "devel 패키지를 커밋 기준으로 확인",
            "yay --devel — -git 등 VCS 패키지를 버전이 아니라 최신 커밋과 비교합니다. 느립니다.",
        ))
        page.add(build)

        remove = Adw.PreferencesGroup(title="삭제")
        remove.add(_switch(
            self.settings, "removal_preview", "삭제 전 영향 미리보기",
            "의존성 연쇄까지 포함해 실제로 무엇이 지워지는지 먼저 보여줍니다.",
        ))
        remove.add(_combo(self.settings, "remove_mode", "삭제 방식", [
            ("Rns", "의존성과 설정 파일까지  (-Rns)"),
            ("Rs", "필요 없어진 의존성까지  (-Rs)"),
            ("R", "패키지만  (-R)"),
        ]))
        page.add(remove)
        return page

    # -- 검색 및 업데이트 -----------------------------------------------------

    def _sources_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(name="sources", title="검색·업데이트",
                                   icon_name="system-search-symbolic")

        search = Adw.PreferencesGroup(title="검색")
        search.add(_switch(
            self.settings, "include_aur_search", "AUR 결과 포함",
            "끄면 공식 저장소만 검색합니다. 훨씬 빠릅니다.",
        ))
        search.add(_combo(self.settings, "search_limit", "결과 개수 제한", [
            (50, "50개"), (100, "100개"), (300, "300개"), (0, "제한 없음"),
        ], "AUR 검색은 결과가 수백 개씩 나오기도 합니다."))
        page.add(search)

        updates = Adw.PreferencesGroup(title="업데이트 확인")
        updates.add(_combo(self.settings, "update_source", "저장소 확인 방법", [
            ("checkupdates", "checkupdates  (임시 DB — 권장)"),
            ("yay", "yay -Qu --repo  (마지막 동기화 기준)"),
        ], "checkupdates 는 임시 DB 복사본을 써서 부분 업그레이드 위험이 없습니다."))
        updates.add(_switch(
            self.settings, "include_aur_updates", "AUR 업데이트 포함",
            "yay -Qua — AUR에 일일이 조회하므로 시간이 걸립니다.",
        ))
        page.add(updates)
        return page

    # -- 고급 ---------------------------------------------------------------

    def _advanced_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(name="advanced", title="고급",
                                   icon_name="preferences-other-symbolic")

        group = Adw.PreferencesGroup(
            title="yay 추가 인자",
            description="설치와 업그레이드 명령 끝에 그대로 붙습니다. 셸 규칙으로 나뉩니다.",
        )
        entry = Adw.EntryRow(title="추가 인자")
        entry.set_text(self.settings["extra_args"])
        entry.connect("changed", lambda r: self.settings.set("extra_args", r.get_text()))
        group.add(entry)

        self._preview_rows = {}
        for key, title in (("install", "설치"), ("upgrade", "전체 업그레이드"), ("remove", "삭제")):
            row = Adw.ActionRow(title=title)
            row.set_subtitle_lines(0)
            row.set_subtitle_selectable(True)
            row.add_css_class("monospace")
            self._preview_rows[key] = row
            group.add(row)
        page.add(group)

        reset_group = Adw.PreferencesGroup()
        reset = Adw.ButtonRow(title="모든 설정을 기본값으로")
        reset.add_css_class("destructive-action")
        reset.connect("activated", lambda *_: self._confirm_reset())
        reset_group.add(reset)
        page.add(reset_group)

        self._update_preview()
        return page

    def _update_preview(self) -> None:
        commands = {
            "install": runner.install_cmd(["패키지"], self.settings),
            "upgrade": runner.upgrade_cmd(None, self.settings),
            "remove": runner.remove_cmd(["패키지"], self.settings),
        }
        for key, argv in commands.items():
            # ActionRow 부제는 Pango 마크업으로 해석되므로 반드시 이스케이프한다.
            self._preview_rows[key].set_subtitle(GLib.markup_escape_text(" ".join(argv)))

    def _on_setting_changed(self, key: str, _value) -> None:
        if hasattr(self, "_preview_rows"):
            self._update_preview()

    def _confirm_reset(self) -> None:
        alert = Adw.AlertDialog(
            heading="설정을 되돌릴까요?",
            body="모든 항목이 기본값으로 돌아갑니다.",
        )
        alert.add_response("cancel", "취소")
        alert.add_response("reset", "되돌리기")
        alert.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        alert.set_default_response("cancel")
        alert.set_close_response("cancel")

        def answered(_dialog, response):
            if response == "reset":
                self.settings.reset()
                # 위젯 상태를 새로 그리기 위해 창을 다시 연다.
                parent = self.get_parent()
                self.close()
                if parent is not None:
                    PreferencesDialog(self.settings).present(parent)

        alert.connect("response", answered)
        alert.present(self)
