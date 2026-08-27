"""설치 전에 AUR PKGBUILD 를 보여주는 검토 창."""

from __future__ import annotations

import datetime as _dt
import difflib
import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk, Pango

from . import aur
from .util import run_async

# 아주 가벼운 bash 하이라이팅. 완전한 파서가 아니라 눈으로 읽기 좋게 하는 정도다.
_TOKEN_RE = re.compile(
    r"""
      (?P<comment>\#[^\n]*)
    | (?P<string>"(?:\\.|[^"\\])*"|'[^']*')
    | (?P<func>^[ \t]*[A-Za-z_][A-Za-z0-9_]*(?=[ \t]*\([ \t]*\)))
    | (?P<assign>^[ \t]*[A-Za-z_][A-Za-z0-9_]*(?==))
    | (?P<keyword>\b(?:if|then|else|elif|fi|for|while|until|do|done|case|esac|in|
                       function|return|local|export|source|exit)\b)
    """,
    re.X | re.M,
)

# libadwaita 의 밝음/어둠 전환을 따라가야 해서 팔레트를 둘 준비한다.
_TAGS = ("comment", "string", "func", "assign", "keyword", "notable",
         "diff_add", "diff_del", "diff_hunk")

_PALETTE = {
    False: {  # 밝은 배경
        "comment":   {"foreground": "#6f7c85", "style": Pango.Style.ITALIC},
        "string":    {"foreground": "#1a7f37"},
        "func":      {"foreground": "#8250df"},
        "assign":    {"foreground": "#953800"},
        "keyword":   {"foreground": "#cf222e"},
        "notable":   {"background": "#fff1cc"},
        "diff_add":  {"foreground": "#0a5227", "background": "#d7f5de"},
        "diff_del":  {"foreground": "#8b1a20", "background": "#ffd7d5"},
        "diff_hunk": {"foreground": "#8250df", "weight": Pango.Weight.BOLD},
    },
    True: {   # 어두운 배경
        "comment":   {"foreground": "#8b949e", "style": Pango.Style.ITALIC},
        "string":    {"foreground": "#7ee787"},
        "func":      {"foreground": "#d2a8ff"},
        "assign":    {"foreground": "#ffa657"},
        "keyword":   {"foreground": "#ff7b72"},
        "notable":   {"background": "#4a3a12"},
        "diff_add":  {"foreground": "#7ee787", "background": "#12261c"},
        "diff_del":  {"foreground": "#ff7b72", "background": "#33161a"},
        "diff_hunk": {"foreground": "#d2a8ff", "weight": Pango.Weight.BOLD},
    },
}

DIFF_TAB = "변경 사항"


def _diff_text(cached: dict, files: dict) -> str:
    """마지막으로 빌드한 버전과 지금 AUR 에 있는 버전의 차이."""
    chunks = []
    for name, new in files.items():
        old = cached.get(name)
        if old is None or old == new:
            continue
        lines = difflib.unified_diff(
            old.splitlines(), new.splitlines(),
            fromfile=f"{name}  (설치된 버전)", tofile=f"{name}  (새 버전)",
            lineterm="", n=3,
        )
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)


class PkgbuildDialog(Adw.Dialog):
    """하나 이상의 AUR 패키지에 대해 PKGBUILD 와 딸린 파일을 보여준다.

    `계속` 을 누르면 on_continue() 가 호출된다. 닫거나 취소하면 아무 일도 없다.
    """

    def __init__(self, parent, names: list[str], on_continue, title: str = "PKGBUILD 검토"):
        super().__init__(title=title, content_width=940, content_height=720)
        self._parent = parent
        self._names = list(dict.fromkeys(names))
        self._on_continue = on_continue
        self._cache: dict[str, dict] = {}
        self._token = 0
        self._views: list[tuple[Gtk.TextBuffer, str]] = []

        self._title_widget = Adw.WindowTitle(title=title, subtitle="")
        header = Adw.HeaderBar(title_widget=self._title_widget)
        header.set_show_end_title_buttons(False)

        if len(self._names) > 1:
            self._picker = Gtk.DropDown.new_from_strings(self._names)
            self._picker.set_tooltip_text("검토할 패키지 선택")
            self._picker.connect("notify::selected", lambda *_: self._load())
            header.pack_start(self._picker)
        else:
            self._picker = None

        self._aur_link = Gtk.LinkButton(label="AUR 페이지")
        self._aur_link.set_visible(False)
        header.pack_end(self._aur_link)

        self._meta_label = Gtk.Label(xalign=0, wrap=True)
        self._meta_label.add_css_class("caption")
        self._meta_label.add_css_class("dim-label")
        self._meta_label.set_margin_start(12)
        self._meta_label.set_margin_end(12)
        self._meta_label.set_margin_top(6)
        self._meta_label.set_margin_bottom(6)

        self._switcher = Gtk.StackSwitcher(halign=Gtk.Align.CENTER)
        self._switcher.set_margin_bottom(6)
        self._switcher.set_visible(False)

        self._banner = Adw.Banner()
        self._banner.set_revealed(False)

        self._stack = Gtk.Stack(vexpand=True,
                                transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._switcher.set_stack(self._stack)

        self._body = Gtk.Stack(vexpand=True)
        self._body.add_named(self._stack, "files")
        self._body.add_named(self._busy_page(), "busy")
        self._error_page = Adw.StatusPage(icon_name="dialog-warning-symbolic")
        self._body.add_named(self._error_page, "error")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self._banner)
        content.append(self._body)

        cancel = Gtk.Button(label="취소")
        cancel.connect("clicked", lambda *_: self.close())
        self._go = Gtk.Button(label="계속")
        self._go.add_css_class("suggested-action")
        self._go.set_sensitive(False)
        self._go.connect("clicked", self._on_go)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          halign=Gtk.Align.END)
        actions.set_margin_top(8)
        actions.set_margin_bottom(8)
        actions.set_margin_start(12)
        actions.set_margin_end(12)
        actions.append(cancel)
        actions.append(self._go)

        toolbar = Adw.ToolbarView(content=content)
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self._meta_label)
        toolbar.add_top_bar(self._switcher)
        toolbar.add_bottom_bar(actions)
        self.set_child(toolbar)

        self._style = Adw.StyleManager.get_default()
        self._style.connect("notify::dark", lambda *_: self._recolor())

    @staticmethod
    def _busy_page() -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        spinner = Adw.Spinner()
        spinner.set_size_request(32, 32)
        label = Gtk.Label(label="AUR에서 PKGBUILD를 가져오는 중…")
        label.add_css_class("dim-label")
        box.append(spinner)
        box.append(label)
        return box

    # -- 실행 ---------------------------------------------------------------

    def run(self) -> None:
        self.present(self._parent)
        self._load()

    def _current_name(self) -> str:
        if self._picker is not None:
            return self._names[self._picker.get_selected()]
        return self._names[0]

    def _load(self) -> None:
        name = self._current_name()
        self._title_widget.set_subtitle(name)
        if name in self._cache:
            self._render(self._cache[name])
            return

        self._token = token = self._token + 1
        self._body.set_visible_child_name("busy")
        self._banner.set_revealed(False)
        self._go.set_sensitive(False)

        def done(data, error):
            if token != self._token:
                return
            if error is not None:
                self._error_page.set_title("PKGBUILD를 가져오지 못했습니다")
                self._error_page.set_description(
                    f"{error}\n\n내용을 확인하지 못했으므로 진행할 수 없습니다. "
                    "그래도 설치하려면 설정 > 설치에서 PKGBUILD 미리보기를 끄세요."
                )
                self._body.set_visible_child_name("error")
                # 내용을 못 봤으니 그냥 진행하게 두지 않는다.
                self._go.set_sensitive(False)
                return
            self._cache[name] = data
            self._render(data)

        run_async(aur.fetch_sources, done, name)

    # -- 그리기 -------------------------------------------------------------

    def _render(self, data: dict) -> None:
        while (child := self._stack.get_first_child()) is not None:
            self._stack.remove(child)
        self._views.clear()

        total_notable = 0
        flagged: list[str] = []
        reasons: list[str] = []

        # 업데이트라면 "지난번에 빌드한 것에서 뭐가 바뀌었나" 가 가장 중요하다.
        # 전문을 매번 다시 읽는 것보다 여기서 악의적 변경이 훨씬 잘 보인다.
        sources = dict(data["files"])
        if diff := _diff_text(data.get("cached") or {}, data["files"]):
            sources = {DIFF_TAB: diff, **sources}

        for filename, text in sources.items():
            buffer, notable = self._make_buffer(
                text, "diff" if filename == DIFF_TAB else "bash")
            self._views.append((buffer, filename))
            total_notable += len(notable)
            if notable:
                flagged.append(filename)
                for why in notable.values():
                    for reason in why:
                        if reason not in reasons:
                            reasons.append(reason)

            view = Gtk.TextView(
                buffer=buffer, editable=False, cursor_visible=False, monospace=True,
                wrap_mode=Gtk.WrapMode.NONE,
                top_margin=12, bottom_margin=12, left_margin=12, right_margin=12,
            )
            scroller = Gtk.ScrolledWindow(child=view, vexpand=True)
            # 표시된 줄이 있는 파일은 탭 이름에 알려준다 (배너는 전체 기준이라
            # 어느 탭을 봐야 하는지 알기 어렵다)
            label = f"⚠ {filename}" if notable else filename
            self._stack.add_titled(scroller, filename, label)

        self._switcher.set_visible(len(sources) > 1)
        self._meta_label.set_label(self._meta_text(data))
        if DIFF_TAB in sources:
            self._title_widget.set_subtitle(
                f"{self._current_name()} · 지난번 빌드 이후 변경됨")
        elif data.get("cached"):
            self._title_widget.set_subtitle(
                f"{self._current_name()} · 지난번 빌드와 동일")

        url = f"{aur.AUR_BASE}/packages/{data['base']}"
        self._aur_link.set_uri(url)
        self._aur_link.set_visible(True)

        if total_notable:
            where = ", ".join(flagged)
            self._banner.set_title(
                f"{where}: 눈여겨볼 줄 {total_notable}개 — {', '.join(reasons[:3])}"
                + (" 등" if len(reasons) > 3 else "")
            )
            self._banner.set_revealed(True)
            # 표시된 파일을 먼저 띄운다 (변경 사항 탭이 있으면 그쪽이 우선)
            first = DIFF_TAB if DIFF_TAB in sources else flagged[0]
            if child := self._stack.get_child_by_name(first):
                self._stack.set_visible_child(child)
        elif data["missing"]:
            self._banner.set_title(
                "저장소에 없는 소스 파일: " + ", ".join(data["missing"])
            )
            self._banner.set_revealed(True)

        self._recolor()
        self._body.set_visible_child_name("files")
        self._go.set_sensitive(True)

    @staticmethod
    def _meta_text(data: dict) -> str:
        meta = data["meta"]
        parts = [f"{data['base']} {meta.get('Version', '')}"]
        if maintainer := meta.get("Maintainer"):
            parts.append(f"관리자 {maintainer}")
        else:
            parts.append("관리자 없음")
        if (votes := meta.get("NumVotes")) is not None:
            parts.append(f"▲ {votes}")
        if modified := meta.get("LastModified"):
            date = _dt.datetime.fromtimestamp(modified).strftime("%Y-%m-%d")
            parts.append(f"최종 수정 {date}")
        if meta.get("OutOfDate"):
            parts.append("기한 만료 표시됨")
        return "  ·  ".join(parts)

    def _make_buffer(self, text: str, mode: str = "bash") -> tuple[Gtk.TextBuffer, dict]:
        buffer = Gtk.TextBuffer()
        buffer.set_text(text)
        table = buffer.get_tag_table()
        for name in _TAGS:
            table.add(Gtk.TextTag(name=name))

        if mode == "diff":
            return buffer, self._tag_diff(buffer, text)

        for match in _TOKEN_RE.finditer(text):
            buffer.apply_tag_by_name(
                match.lastgroup,
                buffer.get_iter_at_offset(match.start()),
                buffer.get_iter_at_offset(match.end()),
            )

        notable = aur.notable_lines(text)
        for line in notable:
            self._tag_line(buffer, line, "notable")
        return buffer, notable

    def _tag_diff(self, buffer: Gtk.TextBuffer, text: str) -> dict:
        """+/- 줄에 색을 입히고, 새로 들어온(+) 줄 중 눈여겨볼 것만 돌려준다."""
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line.startswith(("+++", "---", "@@")):
                tag = "diff_hunk"
            elif line.startswith("+"):
                tag = "diff_add"
            elif line.startswith("-"):
                tag = "diff_del"
            else:
                continue
            self._tag_line(buffer, index, tag)

        # 지워진 줄에서 sudo 가 사라진 것은 좋은 소식이므로, 추가된 줄만 본다.
        return {i: why for i, why in aur.notable_lines(text).items()
                if i < len(lines) and lines[i].startswith("+")
                and not lines[i].startswith("+++")}

    @staticmethod
    def _tag_line(buffer: Gtk.TextBuffer, line: int, tag: str) -> None:
        start = buffer.get_iter_at_line(line)
        if isinstance(start, tuple):        # GTK 4.6+ 는 (성공, iter) 를 준다
            ok, start = start
            if not ok:
                return
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        buffer.apply_tag_by_name(tag, start, end)

    def _recolor(self) -> None:
        palette = _PALETTE[self._style.get_dark()]
        for buffer, _ in self._views:
            table = buffer.get_tag_table()
            for name, properties in palette.items():
                if (tag := table.lookup(name)) is None:
                    continue
                for prop, value in properties.items():
                    tag.set_property(prop, value)

    def _on_go(self, _button) -> None:
        self.close()
        if self._on_continue:
            GLib.idle_add(self._on_continue)
