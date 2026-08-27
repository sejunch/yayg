"""패키지 목록 행과 상세 정보 패널."""

from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import appstream, backend, icons
from .backend import Package
from .util import package_icon, run_async

_REPO_CSS = {"aur": "accent", "repo": "accent", "local": "dim-label"}


def _file_gicon(path: str) -> Gio.Icon:
    return Gio.FileIcon.new(Gio.File.new_for_path(path))


def package_image(name: str, size: int = 32) -> Gtk.Image | None:
    """패키지 아이콘. 못 찾으면 None (호출한 쪽이 저장소 배지를 쓴다).

    Gtk.Image 의 pixel_size 는 icon-name/GIcon 에만 적용되고 paintable 에는
    먹지 않는다. 그래서 파일 아이콘도 Gdk.Texture 가 아니라 Gio.FileIcon 으로
    넘겨야 128px 원본이 그대로 그려지지 않는다.
    """
    found = icons.index().lookup(name)
    if found is None:
        return None

    kind, value = found
    gicon = None
    if kind == "themed":
        display = Gdk.Display.get_default()
        theme = Gtk.IconTheme.get_for_display(display) if display else None
        if theme is not None and theme.has_icon(value):
            gicon = Gio.ThemedIcon.new(value)
        elif path := icons.index().file_icon(name):
            gicon = _file_gicon(path)
    else:
        gicon = _file_gicon(value)

    if gicon is None:
        return None
    image = Gtk.Image.new_from_gicon(gicon)
    image.set_pixel_size(size)
    image.set_valign(Gtk.Align.CENTER)
    return image


# 아이콘이 있는 행과 배지만 있는 행의 제목이 같은 위치에서 시작하도록,
# 접두 위젯은 모두 이 폭의 상자에 넣는다.
PREFIX_WIDTH = 56


def _prefix(child: Gtk.Widget) -> Gtk.Widget:
    box = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=False)
    box.set_size_request(PREFIX_WIDTH, -1)
    child.set_halign(Gtk.Align.CENTER)
    box.append(child)
    return box


def _badge(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0.5, valign=Gtk.Align.CENTER)
    label.add_css_class("caption")
    label.add_css_class(_REPO_CSS.get(text, "dim-label"))
    label.set_max_width_chars(8)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    return label


class PackageRow(Adw.ActionRow):
    """목록 한 줄. 우측 버튼으로 설치/삭제/업그레이드를 바로 실행한다."""

    def __init__(self, pkg: Package, window, mode: str = "search", page=None):
        super().__init__(activatable=True, title_lines=1, subtitle_lines=2)
        self.pkg = pkg
        self.window = window
        self.page = page
        self.selecting = page is not None and page.selection_mode

        self.set_title(GLib.markup_escape_text(pkg.name))
        if mode == "updates":
            subtitle = f"{pkg.installed_version}  →  {pkg.new_version}"
        else:
            subtitle = pkg.description or "설명 없음"
        self.set_subtitle(GLib.markup_escape_text(subtitle))

        if self.selecting:
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.set_active(pkg.name in page.selected)
            check.connect("toggled", lambda c: page.toggle(pkg, c.get_active()))
            self.add_prefix(_prefix(check))
            self._check = check
        else:
            self._check = None
            prefix = None
            if window.settings["show_package_icons"]:
                prefix = package_image(pkg.name)
            self.add_prefix(_prefix(prefix or _badge(pkg.repo or "local")))

        suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                         valign=Gtk.Align.CENTER)

        for tag, css in self._tags(pkg, mode)[:2]:
            chip = Gtk.Label(label=tag)
            chip.add_css_class("caption")
            chip.add_css_class(css)
            # 좁은 행에서 라벨이 눌려 잘리지 않도록 최소 폭을 글자 수로 못 박는다
            chip.set_width_chars(len(tag))
            chip.set_ellipsize(Pango.EllipsizeMode.NONE)
            suffix.append(chip)

        if self.selecting:
            self.add_suffix(suffix)
            self.connect("activated", lambda *_: self._check.set_active(
                not self._check.get_active()))
            return

        button = Gtk.Button(valign=Gtk.Align.CENTER)
        if mode == "updates":
            button.set_label("업그레이드")
            button.add_css_class("suggested-action")
            button.connect("clicked", lambda *_: window.upgrade(pkg))
        elif pkg.installed:
            button.set_label("삭제")
            button.add_css_class("destructive-action")
            button.connect("clicked", lambda *_: window.remove(pkg))
        else:
            button.set_label("설치")
            button.add_css_class("suggested-action")
            button.connect("clicked", lambda *_: window.install(pkg))
        suffix.append(button)

        self.add_suffix(suffix)
        self.connect("activated", lambda *_: window.show_details(pkg))

    @staticmethod
    def _tags(pkg: Package, mode: str) -> list[tuple[str, str]]:
        """행 우측에 붙일 칩. 좁은 행을 고려해 앞의 두 개만 표시된다."""
        tags: list[tuple[str, str]] = []
        if mode == "updates":
            return tags
        if pkg.installed:
            tags.append(("설치됨", "success"))
        if pkg.out_of_date:
            tags.append(("기한 만료", "error"))
        if pkg.orphaned:
            # 검색 결과의 고아 = AUR 관리자 없음, 설치 목록의 고아 = 아무도 의존하지 않음
            tags.append(("관리자 없음" if mode == "search" else "고아", "warning"))
        if mode == "installed" and pkg.size:
            tags.append((backend.format_size(pkg.size), "dim-label"))
        elif mode == "search" and pkg.is_aur and pkg.votes:
            tags.append((f"▲ {pkg.votes}", "dim-label"))
        return tags


# --------------------------------------------------------------------------


_INFO_FIELDS = [
    ("Version", "버전"),
    ("Repository", "저장소"),
    ("Licenses", "라이선스"),
    ("Installed Size", "설치 용량"),
    ("Download Size", "다운로드 크기"),
    ("Maintainer", "관리자"),
    ("Packager", "패키저"),
    ("Votes", "투표"),
    ("Popularity", "인기도"),
    ("Install Date", "설치 날짜"),
    ("Build Date", "빌드 날짜"),
    ("Last Modified", "최종 수정"),
]

# 의존성 표기에서 패키지 이름만 뽑아낸다.
#   일반:   glibc  libtree-sitter.so=0.26-64  gvim>=9.0  'ayatana-ido'
#   선택적: python-pynvim: for Python plugin support  xclip: for clipboard support
# 선택적 의존성은 "이름: 설명" 이 공백으로 이어 붙어 오므로 콜론을 기준으로 잡는다.
_OPTDEP_RE = re.compile(r"(?:^|\s)([A-Za-z0-9][A-Za-z0-9@._+-]*):")
_DEP_SPLIT_RE = re.compile(r"[<>=]")


def _dependency_names(value: str, optional: bool = False) -> list[str]:
    if optional:
        tokens = _OPTDEP_RE.findall(value)
    else:
        tokens = [t.strip("'\"") for t in value.split()]

    names: list[str] = []
    for token in tokens:
        token = _DEP_SPLIT_RE.split(token)[0].strip()
        if not token or ".so" in token or any(c in token for c in "()[]:,"):
            continue                      # 공유 라이브러리·설명 조각은 패키지가 아니다
        if token not in names:
            names.append(token)
    return names


# (필드, 표시 이름, 선택적 의존성 형식인가)
_DEP_FIELDS = [
    ("Depends On", "의존성", False),
    ("Optional Deps", "선택적 의존성", True),
    ("Make Deps", "빌드 의존성", False),
    ("Required By", "이 패키지를 필요로 함", False),
    ("Optional For", "이 패키지의 선택적 의존", False),
    ("Conflicts With", "충돌", False),
    ("Provides", "제공", False),
]


def _fetch_screenshots(name: str) -> list[str]:
    paths = [appstream.download(url) for url in appstream.screenshots(name, 4)]
    return [p for p in paths if p]


class DetailsPane(Adw.Bin):
    """오른쪽 상세 패널. 선택된 패키지 정보를 비동기로 가져와 채운다."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.pkg: Package | None = None
        self._token = 0

        self._header = Adw.HeaderBar()
        self._title = Adw.WindowTitle(title="패키지", subtitle="")
        self._header.set_title_widget(self._title)

        self._content = Adw.Bin(vexpand=True)
        toolbar = Adw.ToolbarView(content=self._content)
        toolbar.add_top_bar(self._header)
        self.set_child(toolbar)
        self.clear()

    def clear(self) -> None:
        self.pkg = None
        self._title.set_title("패키지")
        self._title.set_subtitle("")
        self._content.set_child(Adw.StatusPage(
            icon_name=package_icon(),
            title="선택된 패키지 없음",
            description="목록에서 패키지를 고르면 상세 정보가 여기에 표시됩니다.",
        ))

    def show(self, pkg: Package) -> None:
        self.pkg = pkg
        self._token = token = self._token + 1
        self._title.set_title(pkg.name)
        self._title.set_subtitle(pkg.repo or "local")

        spinner = Adw.StatusPage(title="정보를 가져오는 중…")
        spinner.set_paintable(Adw.SpinnerPaintable(widget=spinner))
        self._content.set_child(spinner)

        def done(info, error):
            if token != self._token:  # 그 사이 다른 패키지를 골랐다
                return
            if error is not None:
                self._content.set_child(Adw.StatusPage(
                    icon_name="dialog-warning-symbolic",
                    title="정보를 가져오지 못했습니다",
                    description=str(error),
                ))
                return
            self._content.set_child(self._build(pkg, info or {}))

        run_async(backend.package_info, done, pkg)

    # -- 본문 구성 ----------------------------------------------------------

    def _build(self, pkg: Package, info: dict) -> Gtk.Widget:
        page = Adw.PreferencesPage()

        intro = Adw.PreferencesGroup()
        intro.add(self._intro_box(pkg, info))
        page.add(intro)

        if self.window.settings["show_screenshots"]:
            self._add_screenshots(page, pkg)

        facts = Adw.PreferencesGroup(title="정보")
        shown = False
        for key, label in _INFO_FIELDS:
            value = info.get(key)
            if value and value != "None":
                facts.add(self._row(label, value))
                shown = True
        if pkg.installed and (reason := info.get("Install Reason")):
            facts.add(self._reason_row(pkg, reason))
            shown = True
        if url := (info.get("URL") or info.get("AUR URL")):
            facts.add(self._link_row("웹사이트", url))
            shown = True
        if pkg.is_aur and (aur := info.get("AUR URL")) and aur != info.get("URL"):
            facts.add(self._link_row("AUR 페이지", aur))
        if shown:
            page.add(facts)

        for key, label, optional in _DEP_FIELDS:
            value = info.get(key)
            if value and value != "None":
                page.add(self._dep_group(label, value, optional))

        return page

    # -- 의존성 칩 ----------------------------------------------------------

    def _dep_group(self, label: str, value: str,
                   optional: bool = False) -> Adw.PreferencesGroup:
        """의존성 이름을 눌러서 이동할 수 있게 만든다.

        Gtk.FlowBox 는 한 줄 안의 칸 너비를 같게 맞추므로, tree-sitter-markdown
        같은 긴 이름 하나가 줄 전체를 넓혀 두세 개밖에 못 들어간다. 그래서
        마크업 링크가 들어간 줄바꿈 라벨을 쓴다 — 글자처럼 자연스럽게 흐른다.
        """
        group = Adw.PreferencesGroup(title=label)
        names = _dependency_names(value, optional)
        if not names:
            group.add(self._row(label, value))
            return group

        markup = "   ".join(
            f'<a href="pkg:{GLib.markup_escape_text(n)}">{GLib.markup_escape_text(n)}</a>'
            for n in names
        )
        link_label = Gtk.Label(label=markup, use_markup=True, wrap=True,
                               xalign=0, selectable=False)
        link_label.set_wrap_mode(Pango.WrapMode.WORD)  # 이름이 중간에 잘리지 않게
        for margin in ("top", "bottom", "start", "end"):
            getattr(link_label, f"set_margin_{margin}")(12)
        link_label.connect("activate-link", self._on_dep_clicked)

        group.add(link_label)
        return group

    def _on_dep_clicked(self, _label, uri: str) -> bool:
        if uri.startswith("pkg:"):
            self.window.open_package(uri[4:])
        return True     # 기본 동작(브라우저 열기)을 막는다

    def _add_screenshots(self, page: Adw.PreferencesPage, pkg: Package) -> None:
        """스크린샷은 원격에서 받아야 한다. 자리를 먼저 만들어 순서를 지키고,
        받아오지 못하면 그 자리를 없앤다."""
        group = Adw.PreferencesGroup()
        carousel = Adw.Carousel(allow_scroll_wheel=False)
        carousel.set_size_request(-1, 300)
        indicator = Adw.CarouselIndicatorDots(carousel=carousel, visible=False)

        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                              valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        spinner = Adw.Spinner()
        spinner.set_size_request(24, 24)
        placeholder.append(spinner)
        carousel.append(placeholder)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(carousel)
        box.append(indicator)
        group.add(box)
        page.add(group)

        token = self._token

        def loaded(paths, error):
            if token != self._token:
                return
            if error is not None or not paths:
                page.remove(group)
                return
            carousel.remove(placeholder)
            for path in paths:
                picture = Gtk.Picture.new_for_filename(path)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                picture.set_size_request(-1, 300)
                carousel.append(picture)
            indicator.set_visible(len(paths) > 1)

        run_async(_fetch_screenshots, loaded, pkg.name)

    def _intro_box(self, pkg: Package, info: dict) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)

        if self.window.settings["show_package_icons"]:
            if image := package_image(pkg.name, 64):
                image.set_valign(Gtk.Align.START)
                box.append(image)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                         hexpand=True, valign=Gtk.Align.CENTER)
        name = Gtk.Label(label=pkg.name, xalign=0, wrap=True, selectable=True)
        name.add_css_class("title-2")
        labels.append(name)
        if description := (info.get("Description") or pkg.description):
            summary = Gtk.Label(label=description, xalign=0, wrap=True)
            summary.add_css_class("dim-label")
            labels.append(summary)
        box.append(labels)

        actions = self._actions(pkg)
        actions.set_valign(Gtk.Align.CENTER)
        box.append(actions)
        return box

    def _actions(self, pkg: Package) -> Gtk.Widget:
        """주 동작만 밖에 두고 나머지는 메뉴로 접는다.
        버튼을 셋 다 늘어놓으면 좁은 패널에서 설명이 세로로 짓눌린다."""
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)

        if not pkg.installed:
            install = Gtk.Button(label="설치")
            install.add_css_class("suggested-action")
            install.connect("clicked", lambda *_: self.window.install(pkg))
            box.append(install)
            return box

        remove = Gtk.Button(label="삭제")
        remove.add_css_class("destructive-action")
        remove.connect("clicked", lambda *_: self.window.remove(pkg))
        box.append(remove)

        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        popover = Gtk.Popover(child=popover_box)
        for label, callback in (
            ("재설치", lambda: self.window.install(pkg, reinstall=True)),
            ("버전 변경", lambda: self.window.downgrade(pkg)),
        ):
            item = Gtk.Button(label=label)
            item.add_css_class("flat")
            item.set_halign(Gtk.Align.FILL)
            item.get_child().set_xalign(0)
            item.connect("clicked", lambda _b, fn=callback: (popover.popdown(), fn()))
            popover_box.append(item)

        more = Gtk.MenuButton(icon_name="view-more-symbolic", popover=popover,
                              tooltip_text="다른 동작")
        box.append(more)
        return box

    def _reason_row(self, pkg: Package, reason: str) -> Adw.ActionRow:
        """명시적 설치 / 의존성 설치를 여기서 바로 바꿀 수 있게 한다.
        의존성으로 표시된 패키지는 아무도 안 쓰게 되면 고아로 잡힌다."""
        explicit = reason.startswith("Explicitly")
        row = Adw.ActionRow(
            title="설치 이유",
            subtitle="직접 설치함 — 고아로 잡히지 않습니다" if explicit
                     else "다른 패키지의 의존성 — 아무도 안 쓰면 고아가 됩니다",
        )
        row.set_subtitle_lines(0)
        button = Gtk.Button(label="의존성으로 표시" if explicit else "직접 설치로 표시",
                            valign=Gtk.Align.CENTER)
        button.connect("clicked",
                       lambda *_: self.window.set_install_reason(pkg, not explicit))
        row.add_suffix(button)
        return row

    @staticmethod
    def _row(label: str, value: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=label, subtitle=GLib.markup_escape_text(value))
        row.set_subtitle_lines(0)      # 줄바꿈 허용
        row.set_subtitle_selectable(True)
        return row

    @staticmethod
    def _link_row(label: str, url: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=label, subtitle=GLib.markup_escape_text(url),
                            activatable=True)
        row.set_subtitle_lines(0)
        row.add_suffix(Gtk.Image(icon_name="adw-external-link-symbolic"))
        row.connect("activated", lambda *_: Gtk.UriLauncher(uri=url).launch(None, None, None, None))
        return row
