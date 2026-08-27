"""실행 전에 한 번 더 보여주는 확인 창들."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk

from . import backend, maintenance
from .news import NewsItem
from .util import run_async


class ActionDialog(Adw.Dialog):
    """헤더 + 본문 + [취소][계속]. 계속을 누를 때만 on_continue 가 불린다."""

    def __init__(self, parent, title: str, subtitle: str = "",
                 continue_label: str = "계속", destructive: bool = False,
                 width: int = 760, height: int = 580):
        super().__init__(title=title, content_width=width, content_height=height)
        self._parent = parent
        self._on_continue = None

        self._title_widget = Adw.WindowTitle(title=title, subtitle=subtitle)
        header = Adw.HeaderBar(title_widget=self._title_widget)
        header.set_show_end_title_buttons(False)

        self._stack = Gtk.Stack(vexpand=True,
                                transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._stack.add_named(Adw.Bin(), "content")
        self._stack.add_named(self._busy_page(), "busy")
        self._error_page = Adw.StatusPage(icon_name="dialog-warning-symbolic")
        self._stack.add_named(self._error_page, "error")

        cancel = Gtk.Button(label="취소")
        cancel.connect("clicked", lambda *_: self.close())
        self.go = Gtk.Button(label=continue_label, sensitive=False)
        self.go.add_css_class("destructive-action" if destructive else "suggested-action")
        self.go.connect("clicked", self._activate)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          halign=Gtk.Align.END)
        for margin in ("top", "bottom"):
            getattr(actions, f"set_margin_{margin}")(8)
        actions.set_margin_start(12)
        actions.set_margin_end(12)
        actions.append(cancel)
        actions.append(self.go)

        toolbar = Adw.ToolbarView(content=self._stack)
        toolbar.add_top_bar(header)
        toolbar.add_bottom_bar(actions)
        self.set_child(toolbar)

    @staticmethod
    def _busy_page() -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        spinner = Adw.Spinner()
        spinner.set_size_request(32, 32)
        label = Gtk.Label(label="확인하는 중…")
        label.add_css_class("dim-label")
        box.append(spinner)
        box.append(label)
        return box

    # -- 상태 --------------------------------------------------------------

    def set_body(self, widget: Gtk.Widget) -> None:
        self._stack.get_child_by_name("content").set_child(widget)
        self._stack.set_visible_child_name("content")
        self.go.set_sensitive(True)

    def show_busy(self) -> None:
        self._stack.set_visible_child_name("busy")
        self.go.set_sensitive(False)

    def show_error(self, title: str, description: str = "") -> None:
        self._error_page.set_title(title)
        self._error_page.set_description(description)
        self._stack.set_visible_child_name("error")
        self.go.set_sensitive(False)

    def set_subtitle(self, text: str) -> None:
        self._title_widget.set_subtitle(text)

    def run(self, on_continue) -> None:
        self._on_continue = on_continue
        self.present(self._parent)

    def _activate(self, _button) -> None:
        self.close()
        if self._on_continue:
            GLib.idle_add(self._on_continue)


class RemovalDialog(ActionDialog):
    """`-Rns` 가 실제로 무엇을 지우는지 먼저 보여준다.

    의존성 연쇄 때문에 직접 고른 것보다 훨씬 많이 지워지는 일이 흔하다."""

    def __init__(self, parent, names: list[str], mode: str = "Rns"):
        count = f"{len(names)}개 패키지" if len(names) > 1 else names[0]
        super().__init__(parent, "삭제 확인", count,
                         continue_label="삭제", destructive=True)
        self._names = names
        self._mode = mode
        self.show_busy()

        def done(targets, error):
            if error is not None:
                self.show_error("제거 대상을 계산하지 못했습니다", str(error))
                return
            self._render(targets or [])

        run_async(backend.removal_preview, done, names, mode)

    def _render(self, targets: list[backend.Package]) -> None:
        if not targets:
            self.show_error("지울 것이 없습니다", "제거 대상이 확인되지 않았습니다.")
            return

        extra = [p for p in targets if not p.explicit]
        total = sum(p.size for p in targets)
        self.set_subtitle(
            f"{len(targets)}개 제거 · {backend.format_size(total)} 회수"
            + (f" · 의존성 {len(extra)}개 포함" if extra else "")
        )

        page = Adw.PreferencesPage()
        requested = [p for p in targets if p.explicit]

        group = Adw.PreferencesGroup(
            title="직접 고른 패키지" if extra else "제거될 패키지")
        for pkg in requested:
            group.add(self._row(pkg))
        page.add(group)

        if extra:
            cascade = Adw.PreferencesGroup(
                title=f"함께 제거될 의존성 {len(extra)}개",
                description="더 이상 아무도 쓰지 않게 되어 같이 지워집니다.",
            )
            for pkg in extra:
                cascade.add(self._row(pkg))
            page.add(cascade)

        self.set_body(page)

    @staticmethod
    def _row(pkg: backend.Package) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(pkg.name),
                            subtitle=GLib.markup_escape_text(pkg.version))
        size = Gtk.Label(label=backend.format_size(pkg.size), valign=Gtk.Align.CENTER)
        size.add_css_class("caption")
        size.add_css_class("dim-label")
        row.add_suffix(size)
        return row


class NewsDialog(ActionDialog):
    """마지막 전체 업그레이드 이후 올라온 Arch 공지."""

    def __init__(self, parent, items: list[NewsItem]):
        urgent = [i for i in items if i.needs_intervention]
        super().__init__(parent, "Arch 뉴스",
                         f"마지막 업그레이드 이후 공지 {len(items)}개"
                         + (f" · 수동 개입 필요 {len(urgent)}개" if urgent else ""),
                         continue_label="그래도 업그레이드",
                         destructive=bool(urgent))
        self.set_body(self._build(items))

    @staticmethod
    def _build(items: list[NewsItem]) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            description="업그레이드 전에 확인이 필요한 공지입니다. "
                        "제목을 누르면 내용이 펼쳐집니다.",
        )
        for item in items:
            row = Adw.ExpanderRow(
                title=GLib.markup_escape_text(item.title),
                subtitle=item.date.strftime("%Y-%m-%d") if item.date else "",
            )
            if item.needs_intervention:
                badge = Gtk.Label(label="수동 개입", valign=Gtk.Align.CENTER)
                badge.add_css_class("caption")
                badge.add_css_class("error")
                row.add_prefix(badge)

            body = Adw.ActionRow(subtitle=GLib.markup_escape_text(item.summary))
            body.set_subtitle_lines(0)
            body.set_subtitle_selectable(True)
            row.add_row(body)

            if item.url:
                link = Adw.ActionRow(title="원문 보기", subtitle=item.url,
                                     activatable=True)
                link.add_suffix(Gtk.Image(icon_name="adw-external-link-symbolic"))
                link.connect("activated",
                             lambda _r, u=item.url: Gtk.UriLauncher(uri=u)
                             .launch(None, None, None, None))
                row.add_row(link)
            group.add(row)
        page.add(group)
        return page


class CleanupDialog(Adw.Dialog):
    """디스크 사용 현황과 정리. 각 줄의 버튼이 해당 정리 명령을 실행한다."""

    def __init__(self, parent, window):
        super().__init__(title="디스크 정리", content_width=720, content_height=560)
        self._parent = parent
        self.window = window

        self._title_widget = Adw.WindowTitle(title="디스크 정리", subtitle="")
        header = Adw.HeaderBar(title_widget=self._title_widget)

        self._body = Adw.Bin(vexpand=True)
        toolbar = Adw.ToolbarView(content=self._body)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)

        self._body.set_child(ActionDialog._busy_page())

    def run(self) -> None:
        self.present(self._parent)
        self._load()

    def _load(self) -> None:
        def done(rows, error):
            if error is not None:
                self._body.set_child(Adw.StatusPage(
                    icon_name="dialog-warning-symbolic",
                    title="사용량을 확인하지 못했습니다", description=str(error)))
                return
            self._render(rows or [])

        run_async(maintenance.cache_usage, done)

    def _render(self, rows: list) -> None:
        total = sum(r.size for r in rows)
        reclaimable = sum(r.reclaimable for r in rows)
        self._title_widget.set_subtitle(
            f"합계 {backend.format_size(total)} · 회수 가능 "
            + (backend.format_size(reclaimable) if reclaimable else "없음"))

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            description="정리 명령은 트랜잭션 창에서 실행되며, 진행 상황을 그대로 볼 수 있습니다.")
        for usage in rows:
            group.add(self._row(usage))
        page.add(group)
        self._body.set_child(page)

    def _row(self, usage) -> Adw.ActionRow:
        detail = usage.detail
        if usage.count:
            detail = f"{usage.count}개 · {detail}" if detail else f"{usage.count}개"
        row = Adw.ActionRow(title=usage.label,
                            subtitle=GLib.markup_escape_text(detail))

        size = Gtk.Label(label=backend.format_size(usage.size), valign=Gtk.Align.CENTER)
        size.add_css_class("heading")
        row.add_suffix(size)

        if usage.reclaimable:
            button = Gtk.Button(label=f"{backend.format_size(usage.reclaimable)} 회수",
                                valign=Gtk.Align.CENTER)
            button.add_css_class("destructive-action")
            button.connect("clicked", lambda *_: self._clean(usage.key))
        else:
            button = Gtk.Label(label="정리할 것 없음", valign=Gtk.Align.CENTER)
            button.add_css_class("caption")
            button.add_css_class("dim-label")
        row.add_suffix(button)
        return row

    def _clean(self, key: str) -> None:
        self.close()
        self.window.run_cleanup(key)


class DowngradeDialog(ActionDialog):
    """캐시와 Arch 아카이브에서 예전 버전을 골라 설치한다."""

    LIMIT = 50

    def __init__(self, parent, pkg):
        super().__init__(parent, "버전 선택", pkg.name,
                         continue_label="이 버전 설치", destructive=True)
        self.pkg = pkg
        self.chosen = None
        self.listbox = None
        self.show_busy()

        def done(versions, error):
            if error is not None:
                self.show_error("버전 목록을 가져오지 못했습니다", str(error))
                return
            self._render(versions or [])

        run_async(maintenance.downgrade_candidates, done,
                  pkg.name, pkg.installed_version or pkg.version)

    def _render(self, versions: list) -> None:
        if not versions:
            self.show_error("고를 수 있는 버전이 없습니다",
                            "로컬 캐시에도, Arch 아카이브에도 이 패키지가 없습니다.")
            return

        shown = versions[:self.LIMIT]
        self.set_subtitle(
            f"{self.pkg.name} · 현재 {self.pkg.installed_version or self.pkg.version}"
            f" · {len(versions)}개 중 {len(shown)}개 표시")

        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        listbox.add_css_class("boxed-list")
        for margin in ("top", "bottom", "start", "end"):
            getattr(listbox, f"set_margin_{margin}")(12)

        for version in shown:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(version.version),
                subtitle="로컬 캐시" if version.source == "cache" else "Arch 아카이브",
            )
            if version.current:
                badge = Gtk.Label(label="현재", valign=Gtk.Align.CENTER)
                badge.add_css_class("caption")
                badge.add_css_class("accent")
                row.add_suffix(badge)
            row.version = version
            listbox.append(row)

        listbox.connect("row-selected", self._on_selected)
        self.listbox = listbox
        scroller = Gtk.ScrolledWindow(child=Adw.Clamp(maximum_size=760, child=listbox),
                                      vexpand=True)
        self.set_body(scroller)
        self.go.set_sensitive(False)      # 고르기 전에는 진행 불가

    def _on_selected(self, _listbox, row) -> None:
        self.chosen = getattr(row, "version", None) if row else None
        self.go.set_sensitive(
            self.chosen is not None and not self.chosen.current)


_ACTION_CSS = {
    "설치": "success", "업그레이드": "accent", "재설치": "accent",
    "삭제": "error", "다운그레이드": "warning",
}


class HistoryDialog(Adw.Dialog):
    """pacman.log 로 보는 최근 변경 이력. 날짜별로 묶는다."""

    def __init__(self, parent, window):
        super().__init__(title="변경 이력", content_width=760, content_height=640)
        self._parent = parent
        self.window = window

        self._title_widget = Adw.WindowTitle(title="변경 이력", subtitle="")
        header = Adw.HeaderBar(title_widget=self._title_widget)
        self._body = Adw.Bin(vexpand=True)
        toolbar = Adw.ToolbarView(content=self._body)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)
        self._body.set_child(ActionDialog._busy_page())

    def run(self) -> None:
        self.present(self._parent)

        def done(entries, error):
            if error is not None:
                self._body.set_child(Adw.StatusPage(
                    icon_name="dialog-warning-symbolic",
                    title="이력을 읽지 못했습니다", description=str(error)))
                return
            self._render(entries or [])

        run_async(maintenance.history, done)

    def _render(self, entries: list) -> None:
        if not entries:
            self._body.set_child(Adw.StatusPage(title="기록이 없습니다"))
            return

        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry.label] = counts.get(entry.label, 0) + 1
        self._title_widget.set_subtitle(
            f"최근 {len(entries)}건 · " + ", ".join(f"{k} {v}" for k, v in counts.items()))

        page = Adw.PreferencesPage()
        group = None
        current_day = None
        for entry in entries:
            day = entry.stamp[:10]
            if day != current_day:
                if group is not None:
                    page.add(group)
                current_day = day
                group = Adw.PreferencesGroup(title=day)
            group.add(self._row(entry))
        if group is not None:
            page.add(group)

        scroller = Gtk.ScrolledWindow(child=page, vexpand=True)
        self._body.set_child(scroller)

    def _row(self, entry) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(entry.name),
                            subtitle=GLib.markup_escape_text(entry.detail),
                            activatable=True)
        badge = Gtk.Label(label=entry.label, valign=Gtk.Align.CENTER)
        badge.add_css_class("caption")
        badge.add_css_class(_ACTION_CSS.get(entry.label, "dim-label"))
        badge.set_width_chars(6)
        row.add_prefix(badge)

        time_label = Gtk.Label(label=entry.stamp[11:16], valign=Gtk.Align.CENTER)
        time_label.add_css_class("caption")
        time_label.add_css_class("dim-label")
        row.add_suffix(time_label)

        row.connect("activated",
                    lambda *_: (self.close(), self.window.open_package(entry.name)))
        return row
