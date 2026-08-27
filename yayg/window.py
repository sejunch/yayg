"""메인 창과 세 개의 페이지(검색 / 설치됨 / 업데이트)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import backend, icons, news, runner
from .backend import Package
from .dialogs import (CleanupDialog, DowngradeDialog, HistoryDialog,
                      NewsDialog, RemovalDialog)
from .pkgbuild import PkgbuildDialog
from .preferences import PreferencesDialog
from .transaction import TransactionDialog
from .util import package_icon, pick_icon, run_async, update_icon
from .widgets import DetailsPane, PackageRow

CHUNK = 40  # 한 번에 붙이는 행 수 — 목록이 길어도 UI가 멈추지 않게 나눠 넣는다


# 행을 만들 때 아이콘 인덱스가 준비돼 있어야 하므로, 데이터를 읽는 같은 워커
# 스레드에서 미리 만들어 둔다. ensure() 는 여러 번 불러도 한 번만 만든다.

def _warm_up() -> None:
    """UI 스레드에서 하면 안 되는 준비 작업 — 아이콘 인덱스와 yay 플래그 확인.
    둘 다 한 번만 실제로 수행된다."""
    icons.index().ensure()
    runner.menu_flags()


def _load_search(term: str, include_aur: bool, limit: int):
    _warm_up()
    return backend.search(term, include_aur, limit)


def _load_installed():
    _warm_up()
    return backend.installed_packages()


def _load_updates(source: str, include_aur: bool, devel: bool):
    _warm_up()
    return backend.check_updates(source, include_aur, devel)


def _load_news():
    """마지막 전체 업그레이드 이후 올라온 공지만."""
    return news.since(news.fetch(), news.last_full_upgrade())


class ListPage(Gtk.Box):
    """스피너 / 빈 상태 / 목록을 전환하는 페이지 공통 뼈대."""

    mode = "search"

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self._fill_source = 0
        self._current: list[Package] = []
        self.selection_mode = False
        self.selected: dict[str, Package] = {}

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_margin_top(12)
        self.listbox.set_margin_bottom(12)
        self.listbox.set_margin_start(12)
        self.listbox.set_margin_end(12)

        clamp = Adw.Clamp(maximum_size=1000, child=self.listbox)
        self._scroller = Gtk.ScrolledWindow(child=clamp, vexpand=True)
        self._scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._stack.add_named(self._scroller, "list")

        self._empty = Adw.StatusPage()
        self._stack.add_named(self._empty, "empty")

        busy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        spinner = Adw.Spinner()
        spinner.set_size_request(32, 32)
        self._busy_label = Gtk.Label(label="불러오는 중…")
        self._busy_label.add_css_class("dim-label")
        busy.append(spinner)
        busy.append(self._busy_label)
        self._stack.add_named(busy, "busy")

        self.append(self._stack)
        self.append(self._build_action_bar())

    # -- 다중 선택 ----------------------------------------------------------

    def _build_action_bar(self) -> Gtk.Widget:
        # 사이드바가 좁을 때 버튼에 밀려 글자가 잘리지 않도록 말줄임 처리
        self._count_label = Gtk.Label(xalign=0, hexpand=True)
        self._count_label.add_css_class("dim-label")
        self._count_label.set_ellipsize(Pango.EllipsizeMode.END)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for side in ("top", "bottom"):
            getattr(box, f"set_margin_{side}")(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.append(self._count_label)

        clear = Gtk.Button(
            icon_name=pick_icon("edit-clear-all-symbolic", "edit-clear-symbolic",
                                "window-close-symbolic"),
            tooltip_text="선택 해제")
        clear.connect("clicked", lambda *_: self.clear_selection())
        box.append(clear)
        for button in self._action_buttons():
            box.append(button)

        self._action_bar = Gtk.Revealer(child=box, transition_type=
                                        Gtk.RevealerTransitionType.SLIDE_UP)
        return self._action_bar

    def _action_buttons(self) -> list[Gtk.Button]:
        """페이지별 일괄 동작. (버튼, 대상을 고르는 함수) 를 self._targets 에 담는다."""
        self._install_button = Gtk.Button()
        self._install_button.add_css_class("suggested-action")
        self._install_button.connect(
            "clicked", lambda *_: self.window.install_many(self._subset(False)))
        self._remove_button = Gtk.Button()
        self._remove_button.add_css_class("destructive-action")
        self._remove_button.connect(
            "clicked", lambda *_: self.window.remove_many(self._subset(True)))
        return [self._install_button, self._remove_button]

    def _subset(self, installed: bool) -> list[Package]:
        return [p for p in self.selected.values() if bool(p.installed) is installed]

    def set_selection_mode(self, active: bool) -> None:
        if self.selection_mode == active:
            return
        self.selection_mode = active
        if not active:
            self.selected.clear()
        self._sync_action_bar()
        self.populate(self._current, keep_scroll=True)

    def clear_selection(self) -> None:
        self.selected.clear()
        self._sync_action_bar()
        self.populate(self._current, keep_scroll=True)

    def toggle(self, pkg: Package, active: bool) -> None:
        if active:
            self.selected[pkg.name] = pkg
        else:
            self.selected.pop(pkg.name, None)
        self._sync_action_bar()

    def _sync_action_bar(self) -> None:
        self._action_bar.set_reveal_child(self.selection_mode)
        count = len(self.selected)
        self._count_label.set_label(f"{count}개 선택됨" if count else "선택된 항목 없음")
        self._update_buttons()

    def _update_buttons(self) -> None:
        to_install = len(self._subset(False))
        to_remove = len(self._subset(True))
        self._install_button.set_label(f"설치 ({to_install})")
        self._install_button.set_sensitive(to_install > 0)
        self._remove_button.set_label(f"삭제 ({to_remove})")
        self._remove_button.set_sensitive(to_remove > 0)

    # -- 상태 전환 ----------------------------------------------------------

    def show_busy(self, text: str = "불러오는 중…") -> None:
        self._busy_label.set_label(text)
        self._stack.set_visible_child_name("busy")

    def show_empty(self, title: str, description: str = "",
                   icon: str = "system-search-symbolic", action: tuple | None = None) -> None:
        self._empty.set_icon_name(icon)
        self._empty.set_title(title)
        self._empty.set_description(description)
        if action is None:
            self._empty.set_child(None)
        else:
            label, callback = action
            button = Gtk.Button(label=label, halign=Gtk.Align.CENTER)
            button.add_css_class("suggested-action")
            button.add_css_class("pill")
            button.connect("clicked", lambda *_: callback())
            self._empty.set_child(button)
        self._stack.set_visible_child_name("empty")

    def populate(self, pkgs: list[Package], keep_scroll: bool = False) -> None:
        if self._fill_source:
            GLib.source_remove(self._fill_source)
            self._fill_source = 0
        offset = self._scroller.get_vadjustment().get_value() if keep_scroll else 0
        self.listbox.remove_all()
        self._current = list(pkgs)
        if not pkgs:
            return
        self._stack.set_visible_child_name("list")
        self._scroller.get_vadjustment().set_value(offset)
        pending = list(pkgs)

        def fill():
            for pkg in pending[:CHUNK]:
                self.listbox.append(PackageRow(pkg, self.window, self.mode, self))
            del pending[:CHUNK]
            if pending:
                return GLib.SOURCE_CONTINUE
            self._fill_source = 0
            return GLib.SOURCE_REMOVE

        self._fill_source = GLib.idle_add(fill, priority=GLib.PRIORITY_DEFAULT_IDLE)


class SearchPage(ListPage):
    mode = "search"
    DEBOUNCE_MS = 350

    def __init__(self, window):
        super().__init__(window)
        self._timeout = 0
        self._token = 0

        self.entry = Gtk.SearchEntry(placeholder_text="저장소와 AUR에서 패키지 검색…")
        self.entry.set_margin_top(12)
        self.entry.set_margin_start(12)
        self.entry.set_margin_end(12)
        self.entry.connect("search-changed", self._on_changed)
        self.entry.connect("activate", lambda *_: self._start(self.entry.get_text()))
        self.prepend(Adw.Clamp(maximum_size=1000, child=self.entry))

        self.show_empty("패키지 검색", "이름이나 키워드를 입력하면 저장소와 AUR을 함께 찾습니다.")

    def _on_changed(self, entry):
        if self._timeout:
            GLib.source_remove(self._timeout)
        text = entry.get_text().strip()
        if len(text) < 2:
            self._token += 1
            self._timeout = 0
            self.show_empty("패키지 검색", "두 글자 이상 입력하세요.")
            return
        self._timeout = GLib.timeout_add(self.DEBOUNCE_MS, self._fire, text)

    def _fire(self, text):
        self._timeout = 0
        self._start(text)
        return GLib.SOURCE_REMOVE

    def _start(self, text: str) -> None:
        text = text.strip()
        if len(text) < 2:
            return
        self._token = token = self._token + 1
        self.show_busy(f"‘{text}’ 검색 중…")

        def done(pkgs, error):
            if token != self._token:  # 더 최신 검색이 이미 시작됨
                return
            if error is not None:
                self.show_empty("검색 실패", str(error), "dialog-warning-symbolic")
                return
            if not pkgs:
                self.show_empty("결과 없음", f"‘{text}’와 일치하는 패키지가 없습니다.")
                return
            self.populate(pkgs)

        settings = self.window.settings
        run_async(_load_search, done, text,
                  bool(settings["include_aur_search"]), int(settings["search_limit"]))

    def refresh(self) -> None:
        if (text := self.entry.get_text().strip()) and len(text) >= 2:
            self._start(text)


class InstalledPage(ListPage):
    mode = "installed"

    FILTERS = ["전체", "명시적 설치", "AUR / 외부", "고아 패키지"]
    SORTS = ["이름순", "크기순"]

    def __init__(self, window):
        super().__init__(window)
        self.packages: list[Package] = []
        self._token = 0

        self.entry = Gtk.SearchEntry(placeholder_text="설치된 패키지 필터…", hexpand=True)
        self.entry.connect("search-changed", lambda *_: self._apply())

        self.filter_drop = Gtk.DropDown.new_from_strings(self.FILTERS)
        self.filter_drop.connect("notify::selected", lambda *_: self._apply())
        self.sort_drop = Gtk.DropDown.new_from_strings(self.SORTS)
        self.sort_drop.connect("notify::selected", lambda *_: self._apply())

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_top(12)
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        for w in (self.entry, self.filter_drop, self.sort_drop):
            bar.append(w)

        self.summary = Gtk.Label(xalign=0)
        self.summary.add_css_class("caption")
        self.summary.add_css_class("dim-label")
        self.summary.set_margin_start(16)
        self.summary.set_margin_top(6)

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        head.append(bar)
        head.append(self.summary)
        self.prepend(Adw.Clamp(maximum_size=1000, child=head))

        self.refresh()

    def refresh(self) -> None:
        self._token = token = self._token + 1
        self.show_busy("설치된 패키지를 읽는 중…")

        def done(pkgs, error):
            if token != self._token:
                return
            if error is not None:
                self.show_empty("목록을 읽지 못했습니다", str(error), "dialog-warning-symbolic")
                return
            self.packages = pkgs or []
            self._apply()

        run_async(_load_installed, done)

    def _apply(self) -> None:
        choice = self.FILTERS[self.filter_drop.get_selected()]
        pkgs = self.packages
        if choice == "명시적 설치":
            pkgs = [p for p in pkgs if p.explicit]
        elif choice == "AUR / 외부":
            pkgs = [p for p in pkgs if p.is_aur]
        elif choice == "고아 패키지":
            pkgs = [p for p in pkgs if p.orphaned]

        if term := self.entry.get_text().strip().lower():
            pkgs = [p for p in pkgs
                    if term in p.name.lower() or term in p.description.lower()]

        if self.SORTS[self.sort_drop.get_selected()] == "크기순":
            pkgs = sorted(pkgs, key=lambda p: -p.size)

        total = sum(p.size for p in pkgs)
        self.summary.set_label(
            f"{len(pkgs)}개 패키지 · 합계 {backend.format_size(total)}"
            f"   (전체 {len(self.packages)}개)"
        )

        if not pkgs:
            self.show_empty("해당하는 패키지 없음", "필터나 검색어를 바꿔 보세요.")
            return
        self.populate(pkgs)


class UpdatesPage(ListPage):
    mode = "updates"

    def _action_buttons(self) -> list[Gtk.Button]:
        self._upgrade_button = Gtk.Button()
        self._upgrade_button.add_css_class("suggested-action")
        self._upgrade_button.connect(
            "clicked",
            lambda *_: self.window.upgrade_many(list(self.selected.values())))
        return [self._upgrade_button]

    def _update_buttons(self) -> None:
        count = len(self.selected)
        self._upgrade_button.set_label(f"업그레이드 ({count})")
        self._upgrade_button.set_sensitive(count > 0)

    def __init__(self, window):
        super().__init__(window)
        self._token = 0
        self._checked = False
        self.pkgs: list[Package] = []

        self.banner = Adw.Banner(button_label="모두 업그레이드")
        self.banner.connect("button-clicked", lambda *_: self.window.upgrade_all())
        self.prepend(self.banner)

        self.refresh()

    def refresh(self, force: bool = False) -> None:
        settings = self.window.settings
        self.banner.set_revealed(False)
        if not force and not settings["check_updates_on_start"] and not self._checked:
            self.show_empty(
                "업데이트 확인 안 함",
                "설정에서 자동 확인을 껐습니다. 지금 확인하려면 아래를 누르세요.",
                update_icon(), ("지금 확인", lambda: self.refresh(force=True)),
            )
            return

        self._checked = True
        self._token = token = self._token + 1
        self.show_busy("업데이트 확인 중… (AUR 조회에 시간이 걸릴 수 있습니다)")

        def done(pkgs, error):
            if token != self._token:
                return
            if error is not None:
                self.show_empty("업데이트를 확인하지 못했습니다", str(error), "dialog-warning-symbolic")
                return
            self.pkgs = pkgs or []
            if not self.pkgs:
                self.show_empty("최신 상태입니다", "설치된 모든 패키지가 최신 버전입니다.",
                                "emblem-ok-symbolic")
                return
            repo = sum(1 for p in self.pkgs if p.repo == "repo")
            aur = len(self.pkgs) - repo
            self.banner.set_title(f"업데이트 {len(self.pkgs)}개 — 저장소 {repo}개, AUR {aur}개")
            self.banner.set_revealed(True)
            self.populate(self.pkgs)

        run_async(_load_updates, done,
                  settings["update_source"], bool(settings["include_aur_updates"]),
                  bool(settings["devel_updates"]))


# --------------------------------------------------------------------------


class YaygWindow(Adw.ApplicationWindow):
    def __init__(self, app, settings):
        super().__init__(application=app, title="yayg",
                         default_width=1180, default_height=780)
        self.settings = settings

        self.details = DetailsPane(self)
        self.search_page = SearchPage(self)
        self.installed_page = InstalledPage(self)
        self.updates_page = UpdatesPage(self)

        self.stack = Adw.ViewStack()
        self.stack.add_titled_with_icon(self.search_page, "search", "검색", "system-search-symbolic")
        self.stack.add_titled_with_icon(self.installed_page, "installed", "설치됨", package_icon())
        self.stack.add_titled_with_icon(self.updates_page, "updates", "업데이트", update_icon())

        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header = Adw.HeaderBar(title_widget=switcher)

        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="현재 목록 새로고침 (Ctrl+R)")
        refresh.connect("clicked", lambda *_: self.refresh_current())
        header.pack_start(refresh)

        self.select_toggle = Gtk.ToggleButton(
            icon_name=pick_icon("selection-mode-symbolic", "checkbox-checked-symbolic",
                                "object-select-symbolic"),
            tooltip_text="여러 개 선택해서 한 번에 처리 (Ctrl+S)",
        )
        self.select_toggle.connect("toggled", self._on_select_toggled)
        header.pack_start(self.select_toggle)

        menu = Gio.Menu()
        actions_section = Gio.Menu()
        actions_section.append("시스템 전체 업그레이드", "win.upgrade-all")
        actions_section.append("고아 패키지 정리", "win.clean-orphans")
        actions_section.append("디스크 정리", "win.cleanup")
        actions_section.append("변경 이력", "win.history")
        actions_section.append("모두 새로고침", "win.refresh-all")
        menu.append_section(None, actions_section)
        app_section = Gio.Menu()
        app_section.append("설정", "win.preferences")
        app_section.append("yayg 정보", "win.about")
        menu.append_section(None, app_section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))

        sidebar_view = Adw.ToolbarView(content=self.stack)
        sidebar_view.add_top_bar(header)

        self.split = Adw.NavigationSplitView(
            sidebar=Adw.NavigationPage(title="yayg", child=sidebar_view),
            content=Adw.NavigationPage(title="패키지", child=self.details),
            min_sidebar_width=420, max_sidebar_width=760, sidebar_width_fraction=0.5,
        )
        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        # 페이지를 옮기면 그 페이지의 선택 상태에 맞춰 토글을 되돌린다
        self.stack.connect("notify::visible-child", self._on_page_changed)

        self._install_actions()
        self.stack.set_visible_child_name(settings["start_page"])
        settings.connect(self._on_setting_changed)

    # -- 액션 ---------------------------------------------------------------

    def _install_actions(self) -> None:
        specs = [
            ("upgrade-all", lambda *_: self.upgrade_all(), ["<Control>u"]),
            ("clean-orphans", lambda *_: self.clean_orphans(), []),
            ("cleanup", lambda *_: self.show_cleanup(), []),
            ("history", lambda *_: HistoryDialog(self, self).run(), []),
            ("refresh-all", lambda *_: self.refresh_all(), []),
            ("preferences", lambda *_: self.show_preferences(), ["<Control>comma"]),
            ("about", lambda *_: self.show_about(), []),
            ("refresh", lambda *_: self.refresh_current(), ["<Control>r"]),
            ("focus-search", lambda *_: self.focus_search(), ["<Control>f"]),
            ("select-mode", lambda *_: self.select_toggle.set_active(
                not self.select_toggle.get_active()), ["<Control>s"]),
        ]
        app = self.get_application()
        for name, callback, accels in specs:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            if accels:
                app.set_accels_for_action(f"win.{name}", accels)

    def _on_select_toggled(self, button) -> None:
        page = self.stack.get_visible_child()
        if isinstance(page, ListPage):
            page.set_selection_mode(button.get_active())

    def _on_page_changed(self, *_args) -> None:
        page = self.stack.get_visible_child()
        if isinstance(page, ListPage):
            self.select_toggle.set_active(page.selection_mode)

    def _exit_selection(self) -> None:
        for page in (self.search_page, self.installed_page, self.updates_page):
            page.set_selection_mode(False)
        self.select_toggle.set_active(False)

    # -- 일괄 작업 ----------------------------------------------------------

    def install_many(self, pkgs: list[Package]) -> None:
        if not pkgs:
            return
        aur_names = [p.name for p in pkgs if p.is_aur]
        argv = runner.install_cmd([p.qualified for p in pkgs], self.settings)
        self._exit_selection()
        self._review_then_run(aur_names, f"{len(pkgs)}개 설치", argv)

    def remove_many(self, pkgs: list[Package]) -> None:
        if not pkgs:
            return
        names = [p.name for p in pkgs]
        argv = runner.remove_cmd(names, self.settings)
        self._exit_selection()
        self._confirm_removal(names, f"{len(names)}개 삭제", argv)

    def upgrade_many(self, pkgs: list[Package]) -> None:
        if not pkgs:
            return
        aur_names = [p.name for p in pkgs if p.is_aur]
        argv = runner.upgrade_cmd([p.name for p in pkgs], self.settings)
        self._exit_selection()
        self._review_then_run(aur_names, f"{len(pkgs)}개 업그레이드", argv)

    def open_package(self, name: str) -> None:
        """의존성 칩에서 이동. 설치 여부만 확인하고 상세 패널이 나머지를 채운다."""
        def done(installed, _error):
            self.show_details(Package(name=name, installed=bool(installed)))

        run_async(backend.is_installed, done, name)

    def set_install_reason(self, pkg: Package, explicit: bool) -> None:
        label = "직접 설치" if explicit else "의존성"
        self._run(f"{pkg.name} → {label}로 표시",
                  runner.install_reason_cmd([pkg.name], explicit))

    def show_cleanup(self) -> None:
        CleanupDialog(self, self).run()

    def run_cleanup(self, key: str) -> None:
        if key == "orphans":
            self.clean_orphans()
            return
        argv = runner.cleanup_cmd(key)
        if argv is None:
            self.toast("알 수 없는 정리 항목입니다")
            return
        labels = {"pacman_cache": "pacman 캐시 정리",
                  "uninstalled": "미설치 패키지 캐시 정리",
                  "yay_cache": "yay 빌드 캐시 정리"}
        self._run(labels.get(key, "정리"), argv)

    def downgrade(self, pkg: Package) -> None:
        dialog = DowngradeDialog(self, pkg)

        def chosen():
            version = dialog.chosen
            if version is None:
                return
            self._run(f"{pkg.name} → {version.version}",
                      runner.downgrade_cmd(version.location, self.settings))

        dialog.run(chosen)

    def show_preferences(self) -> None:
        PreferencesDialog(self.settings).present(self)

    def _on_setting_changed(self, key: str, value) -> None:
        if key in ("include_aur_search", "search_limit"):
            self.search_page.refresh()
        elif key in ("update_source", "include_aur_updates", "devel_updates"):
            self.updates_page.refresh(force=True)
        elif key == "show_package_icons":
            self.search_page.refresh()
            self.installed_page.refresh()
            if self.updates_page.pkgs:
                self.updates_page.populate(self.updates_page.pkgs)

    def focus_search(self) -> None:
        page = self.stack.get_visible_child()
        if isinstance(page, (SearchPage, InstalledPage)):
            page.entry.grab_focus()
        else:
            self.stack.set_visible_child_name("search")
            self.search_page.entry.grab_focus()

    def refresh_current(self) -> None:
        page = self.stack.get_visible_child()
        if hasattr(page, "refresh"):
            page.refresh()

    def refresh_all(self) -> None:
        self.search_page.refresh()
        self.installed_page.refresh()
        self.updates_page.refresh()

    def show_details(self, pkg: Package) -> None:
        self.details.show(pkg)
        self.split.set_show_content(True)

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    # -- 트랜잭션 -----------------------------------------------------------

    def _run(self, title: str, argv: list[str]) -> None:
        dialog = TransactionDialog(self, title, argv, on_finished=self._after_transaction)
        dialog.run()

    def _after_transaction(self, ok: bool) -> bool:
        # 설치 상태가 바뀌었을 수 있으니 캐시된 목록을 모두 다시 읽는다.
        # .desktop 항목도 달라졌을 수 있으므로 아이콘 인덱스를 버린다.
        icons.index().invalidate()
        self.installed_page.refresh()
        self.updates_page.refresh()
        self.search_page.refresh()
        self._refresh_details()
        self.toast("작업 완료" if ok else "작업이 완료되지 않았습니다")
        return GLib.SOURCE_REMOVE

    def _refresh_details(self) -> None:
        """트랜잭션 뒤에는 설치 여부가 바뀌었을 수 있으므로 다시 확인하고 그린다."""
        pkg = self.details.pkg
        if pkg is None:
            return

        def done(installed, error):
            if self.details.pkg is not pkg:
                return
            if error is None:
                pkg.installed = bool(installed)
                if not installed:
                    pkg.installed_version = ""
            self.details.show(pkg)

        run_async(backend.is_installed, done, pkg.name)

    def _news_then(self, proceed) -> None:
        """전체 업그레이드 전 Arch 공지 확인.

        공지 확인은 어디까지나 참고용이므로, 피드를 못 가져와도 업그레이드를
        막지는 않는다 (알리기만 하고 그대로 진행)."""
        if not self.settings["check_news_before_upgrade"]:
            proceed()
            return

        self.toast("Arch 공지 확인 중…")

        def done(items, error):
            if error is not None:
                self.toast(f"공지를 확인하지 못했습니다 — {error}")
                proceed()
                return
            if not items:
                proceed()
                return
            NewsDialog(self, items).run(proceed)

        run_async(_load_news, done)

    def _confirm_removal(self, names: list[str], title: str, argv: list[str]) -> None:
        if not self.settings["removal_preview"]:
            self._run(title, argv)
            return
        RemovalDialog(self, names, self.settings.remove_flag()).run(
            lambda: self._run(title, argv))

    def _review_then_run(self, aur_names: list[str], title: str, argv: list[str]) -> None:
        """AUR이 끼어 있고 미리보기가 켜져 있으면 PKGBUILD를 먼저 보여준다."""
        if aur_names and self.settings["pkgbuild_preview"]:
            PkgbuildDialog(self, aur_names, lambda: self._run(title, argv)).run()
        else:
            self._run(title, argv)

    def install(self, pkg: Package, reinstall: bool = False) -> None:
        argv = runner.install_cmd([pkg.qualified], self.settings, needed=not reinstall)
        title = f"{pkg.name} {'재설치' if reinstall else '설치'}"
        self._review_then_run([pkg.name] if pkg.is_aur else [], title, argv)

    def remove(self, pkg: Package) -> None:
        self._confirm_removal([pkg.name], f"{pkg.name} 삭제",
                              runner.remove_cmd([pkg.name], self.settings))

    def upgrade(self, pkg: Package) -> None:
        argv = runner.upgrade_cmd([pkg.name], self.settings)
        self._review_then_run([pkg.name] if pkg.is_aur else [],
                              f"{pkg.name} 업그레이드", argv)

    def upgrade_all(self) -> None:
        aur_names = [p.name for p in self.updates_page.pkgs if p.is_aur]
        argv = runner.upgrade_cmd(None, self.settings)
        self._news_then(
            lambda: self._review_then_run(aur_names, "시스템 전체 업그레이드", argv))

    def clean_orphans(self) -> None:
        orphans = [p.name for p in self.installed_page.packages if p.orphaned]
        if not orphans:
            self.toast("정리할 고아 패키지가 없습니다")
            return
        self._confirm_removal(orphans, f"고아 패키지 {len(orphans)}개 제거",
                              runner.remove_cmd(orphans, self.settings))

    def show_about(self) -> None:
        about = Adw.AboutDialog(
            application_name="yayg",
            application_icon=package_icon(),
            version="0.1.0",
            comments="yay 위에 얹은 GTK4 / libadwaita 패키지 관리자.\n"
                     "설치·삭제·업그레이드는 모두 yay가 그대로 처리합니다.",
            developer_name="yayg",
            license_type=Gtk.License.MIT_X11,
        )
        about.present(self)
