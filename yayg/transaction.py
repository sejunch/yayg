"""yay 트랜잭션 진행 상황을 보여주는 다이얼로그."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk

from .runner import Transaction


class TransactionDialog(Adw.Dialog):
    def __init__(self, parent, title: str, argv: list[str], on_finished=None):
        super().__init__(title=title, content_width=820, content_height=560)
        self._parent = parent
        self._on_finished = on_finished
        self._finished = False
        self.set_can_close(False)

        # -- 로그 뷰 --------------------------------------------------------
        self.buf = Gtk.TextBuffer()
        self.view = Gtk.TextView(
            buffer=self.buf, editable=False, cursor_visible=False,
            monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
            top_margin=12, bottom_margin=12, left_margin=12, right_margin=12,
        )
        self._tail_mark = self.buf.create_mark("tail", self.buf.get_end_iter(), True)
        self._end_mark = self.buf.create_mark("end", self.buf.get_end_iter(), False)

        scroller = Gtk.ScrolledWindow(child=self.view, vexpand=True)
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._vadj = scroller.get_vadjustment()

        # -- 헤더 -----------------------------------------------------------
        self._status_label = Gtk.Label(label="실행 중…")
        self._status_label.add_css_class("dim-label")
        self._status_label.add_css_class("caption")
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        heading = Gtk.Label(label=title)
        heading.add_css_class("heading")
        title_box.append(heading)
        title_box.append(self._status_label)

        header = Adw.HeaderBar(title_widget=title_box)
        header.set_show_end_title_buttons(False)
        self._action_button = Gtk.Button(label="취소")
        self._action_button.add_css_class("destructive-action")
        self._action_button.connect("clicked", self._on_action)
        header.pack_end(self._action_button)

        # -- 입력 줄 --------------------------------------------------------
        self._entry = Gtk.Entry(hexpand=True, placeholder_text="프롬프트에 답하려면 여기에 입력하세요")
        self._entry.connect("activate", lambda *_: self._send(self._entry.get_text()))

        self._yes = Gtk.Button(label="예")
        self._yes.add_css_class("suggested-action")
        self._yes.connect("clicked", lambda *_: self._send("y"))
        self._no = Gtk.Button(label="아니오")
        self._no.connect("clicked", lambda *_: self._send("n"))
        self._yes.set_visible(False)
        self._no.set_visible(False)

        send = Gtk.Button(icon_name="document-send-symbolic", tooltip_text="입력 전송")
        send.connect("clicked", lambda *_: self._send(self._entry.get_text()))

        self._input_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._input_bar.set_margin_top(6)
        self._input_bar.set_margin_bottom(6)
        self._input_bar.set_margin_start(12)
        self._input_bar.set_margin_end(12)
        for w in (self._entry, send, self._yes, self._no):
            self._input_bar.append(w)

        toolbar = Adw.ToolbarView(content=scroller)
        toolbar.add_top_bar(header)
        toolbar.add_bottom_bar(self._input_bar)
        self.set_child(toolbar)

        # -- 실행 -----------------------------------------------------------
        self._append_line(f"$ {' '.join(argv)}")
        self.txn = Transaction(argv, self._on_output, self._on_prompt, self._on_exit)

    def run(self) -> None:
        self.present(self._parent)
        self.txn.start()
        self._entry.grab_focus()

    # -- 로그 출력 ----------------------------------------------------------

    def _append_line(self, line: str) -> None:
        self.buf.insert(self.buf.get_end_iter(), line + "\n")
        self.buf.move_mark(self._tail_mark, self.buf.get_end_iter())

    def _on_output(self, committed: list[str], tail: str) -> None:
        at_bottom = self._vadj.get_value() >= (
            self._vadj.get_upper() - self._vadj.get_page_size() - 40
        )

        # 이전에 그려둔 미완성 줄을 지우고 새로 그린다.
        start = self.buf.get_iter_at_mark(self._tail_mark)
        self.buf.delete(start, self.buf.get_end_iter())
        if committed:
            self.buf.insert(self.buf.get_end_iter(), "\n".join(committed) + "\n")
            self.buf.move_mark(self._tail_mark, self.buf.get_end_iter())
        if tail:
            self.buf.insert(self.buf.get_end_iter(), tail)

        if at_bottom:
            self.view.scroll_to_mark(self._end_mark, 0, True, 0, 1)

    # -- 프롬프트 -----------------------------------------------------------

    def _on_prompt(self, kind: str | None) -> None:
        if self._finished:
            return
        is_password = kind == "password"
        self._entry.set_visibility(not is_password)
        self._entry.set_placeholder_text(
            "sudo 비밀번호" if is_password else "프롬프트에 답하려면 여기에 입력하세요"
        )
        self._yes.set_visible(kind == "confirm")
        self._no.set_visible(kind == "confirm")
        if kind:
            self._entry.grab_focus()

    def _send(self, text: str) -> None:
        if self._finished:
            return
        self.txn.send(text)
        self._entry.set_text("")

    # -- 종료 ---------------------------------------------------------------

    def _on_action(self, _button) -> None:
        if self._finished:
            self.close()
        else:
            self._append_line("\n-- 취소 요청 (SIGINT) --")
            self.txn.cancel()

    def _on_exit(self, status: int) -> None:
        self._finished = True
        self.set_can_close(True)
        self._input_bar.set_visible(False)

        if self.txn.cancelled:
            text, css = "취소됨", "warning"
        elif status == 0:
            text, css = "완료", "success"
        else:
            text, css = f"실패 (종료 코드 {status})", "error"

        self._status_label.set_label(text)
        self._status_label.remove_css_class("dim-label")
        self._status_label.add_css_class(css)

        self._action_button.set_label("닫기")
        self._action_button.remove_css_class("destructive-action")
        self._action_button.add_css_class("suggested-action")
        self.view.scroll_to_mark(self._end_mark, 0, True, 0, 1)

        if self._on_finished:
            GLib.idle_add(self._on_finished, status == 0)
