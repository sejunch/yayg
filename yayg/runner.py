"""yay 트랜잭션(설치/삭제/업그레이드)을 pty 위에서 실행한다.

VTE4가 없어도 되도록 파이썬 내장 pty를 쓴다. pty 덕분에 yay가 자기를 대화형
터미널로 인식하므로 sudo 비밀번호 입력, [Y/n] 확인 같은 프롬프트를 그대로
사용자에게 넘길 수 있다.
"""

from __future__ import annotations

import fcntl
import os
import pty
import re
import signal
import struct
import subprocess
import termios

from gi.repository import GLib

# CSI/OSC 이스케이프 + 문자셋 전환 시퀀스 제거
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[()][A-Za-z0-9]"
    r"|\x1b[=><]"
)

# sudo 프롬프트는 로케일에 따라 문구가 달라진다(한국어: "[sudo] <사용자>의 암호:").
# 아래에서 SUDO_PROMPT 를 고정하지만, su 등 다른 경로도 있으므로 넉넉하게 잡는다.
_PASSWORD_RE = re.compile(
    r"(?:\[sudo\]|password|passphrase|암호|비밀번호|passwort|contraseña|mot de passe|пароль)"
    r"[^:\n]*:\s*$",
    re.I,
)
_CONFIRM_RE = re.compile(r"\[(Y/n|y/N|Y/n/.|N/y)\]\s*$", re.I)

TERM_WIDTH = 100


class Transaction:
    """argv를 pty에서 실행하고 출력/종료를 콜백으로 넘긴다.

    on_output(committed: list[str], tail: str) -- committed는 이번에 완성된 줄들,
      tail은 아직 개행이 오지 않은 현재 줄(진행률 표시줄이 여기서 갱신된다).
    on_prompt(kind: str | None) -- 'password' | 'confirm' | None
    on_exit(status: int) -- 0이면 성공.
    """

    def __init__(self, argv, on_output, on_prompt, on_exit):
        self.argv = list(argv)
        self._on_output = on_output
        self._on_prompt = on_prompt
        self._on_exit = on_exit

        self.pid = -1
        self.fd = -1
        self._tail = ""
        self._cr_pending = False   # \r 를 만나 커서가 줄 앞에 있는 상태
        self._eof = False
        self._status: int | None = None
        self._src = 0
        self._prompt: str | None = None
        self.cancelled = False

    # -- 실행 ---------------------------------------------------------------

    def start(self) -> None:
        pid, fd = pty.fork()
        if pid == 0:
            # 자식: GLib을 건드리지 않고 곧바로 exec 한다.
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLUMNS"] = str(TERM_WIDTH)
            os.environ["LINES"] = "40"
            # 대화형 페이저가 뜨면 UI가 멈추므로 전부 무력화한다.
            os.environ["PAGER"] = "cat"
            os.environ["GIT_PAGER"] = "cat"
            os.environ["SYSTEMD_PAGER"] = "cat"
            os.environ["MANPAGER"] = "cat"
            # 로케일과 무관하게 항상 같은 프롬프트가 나오도록 고정한다.
            os.environ["SUDO_PROMPT"] = "[sudo] %p 비밀번호: "
            try:
                os.execvp(self.argv[0], self.argv)
            except Exception:
                pass
            os._exit(127)

        self.pid, self.fd = pid, fd
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, TERM_WIDTH, 0, 0))
        except OSError:
            pass

        self._src = GLib.unix_fd_add_full(
            GLib.PRIORITY_DEFAULT, fd,
            GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
            self._on_readable,
        )
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, pid, self._on_child_exit)

    # -- 입력 ---------------------------------------------------------------

    def send(self, text: str) -> None:
        """프롬프트 응답을 자식에게 보낸다 (개행 포함)."""
        if self.fd < 0:
            return
        try:
            os.write(self.fd, (text + "\n").encode())
        except OSError:
            pass
        self._set_prompt(None)

    def cancel(self) -> None:
        """프로세스 그룹에 SIGINT — yay가 정리할 기회를 준다."""
        if self.pid <= 0 or self._status is not None:
            return
        self.cancelled = True
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGINT)
        except OSError:
            pass

    # -- 내부 ---------------------------------------------------------------

    def _on_readable(self, fd, condition):
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        if not data:
            self._eof = True
            self._src = 0
            self._maybe_finish()
            return GLib.SOURCE_REMOVE
        self._feed(data.decode("utf-8", "replace"))
        return GLib.SOURCE_CONTINUE

    def _feed(self, text: str) -> None:
        text = _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\x07", "")
        segments = text.split("\n")
        committed: list[str] = []
        for i, seg in enumerate(segments):
            self._write(seg)
            if i < len(segments) - 1:
                committed.append(self._tail)
                self._tail = ""
                self._cr_pending = False

        self._on_output(committed, self._tail)
        self._detect_prompt(committed[-1] if committed else self._tail)

    def _write(self, seg: str) -> None:
        """캐리지 리턴을 반영해 현재 줄(tail)을 갱신한다.

        pacman/yay 진행률 표시줄은 `...50%\r...75%\r` 처럼 같은 줄을 계속
        덮어쓴다. 줄 끝의 \r 은 "커서만 줄 앞으로" 이므로 내용은 그대로 두고,
        다음에 실제 문자가 올 때 앞에서부터 덮어쓴다.
        """
        for index, part in enumerate(seg.split("\r")):
            if index > 0:
                self._cr_pending = True
            if not part:
                continue
            if self._cr_pending:
                self._tail = part
                self._cr_pending = False
            else:
                self._tail += part

    def _detect_prompt(self, line: str) -> None:
        probe = (self._tail or line).rstrip()
        if _PASSWORD_RE.search(probe):
            self._set_prompt("password")
        elif _CONFIRM_RE.search(probe):
            self._set_prompt("confirm")
        else:
            # 새 출력이 흘렀다면 직전 프롬프트는 이미 지나간 것이다.
            self._set_prompt(None)

    def _set_prompt(self, kind: str | None) -> None:
        if kind != self._prompt:
            self._prompt = kind
            self._on_prompt(kind)

    def _on_child_exit(self, pid, status):
        self._status = os.waitstatus_to_exitcode(status) if status >= 0 else status
        # 종료 후에도 pty에 남은 출력이 있을 수 있으므로 한 번 더 훑는다.
        if not self._eof and self.fd >= 0:
            GLib.timeout_add(50, self._drain)
        else:
            self._maybe_finish()

    def _drain(self):
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            data = b""
        if data:
            self._feed(data.decode("utf-8", "replace"))
            return GLib.SOURCE_CONTINUE
        self._eof = True
        if self._src:
            GLib.source_remove(self._src)
            self._src = 0
        self._maybe_finish()
        return GLib.SOURCE_REMOVE

    def _maybe_finish(self):
        if not (self._eof and self._status is not None):
            return
        if self._tail:
            self._on_output([self._tail], "")
            self._tail = ""
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1
        self._set_prompt(None)
        self._on_exit(self._status)


# -- 명령 조립 --------------------------------------------------------------

# PKGBUILD diff/편집 메뉴는 대화형 페이저나 편집기를 띄워 창을 멈추므로 끈다.
# 검토는 yayg 자체 미리보기 창(설정 > 설치)이 담당한다. 설치 확인([Y/n])은 그대로
# 남겨서 사용자가 트랜잭션 다이얼로그에서 직접 승인하게 한다.
#
# 문제는 이 플래그 이름이 yay 버전마다 다르다는 것이다. v12 는
# `--diffmenu=false`, 예전 버전은 `--nodiffmenu` 를 쓴다. 틀린 이름을 넘기면
# yay 가 아무것도 하지 않고 "잘못된 옵션" 으로 죽으므로, 추측하지 말고 물어본다.
# `yay <플래그> --version` 은 부작용이 없고, 플래그가 유효할 때만 버전을 찍는다.
_MENU_CANDIDATES = (
    ["--diffmenu=false", "--editmenu=false"],
    ["--nodiffmenu", "--noeditmenu"],
)

_menu_flags_cache: list[str] | None = None


def _accepts(flags: list[str]) -> bool:
    try:
        proc = subprocess.run(
            ["yay", *flags, "--version"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.stdout.lstrip().startswith("yay")


def menu_flags() -> list[str]:
    """이 yay 가 실제로 받아들이는, diff/편집 메뉴를 끄는 플래그.

    한 번만 확인하고 캐시한다. UI 스레드를 막지 않도록 워커에서 먼저 부른다.
    어느 후보도 안 통하면 빈 목록 — 메뉴가 뜨더라도 트랜잭션 창에서 답할 수 있다.
    """
    global _menu_flags_cache
    if _menu_flags_cache is None:
        _menu_flags_cache = next(
            (c for c in _MENU_CANDIDATES if _accepts(c)), []
        )
    return list(_menu_flags_cache)


def _flags(settings) -> tuple[list[str], list[str]]:
    flags = menu_flags()
    if settings is None:
        return flags, []
    return flags + settings.build_flags(), settings.extra_argv()


def install_cmd(names: list[str], settings=None, needed: bool = True) -> list[str]:
    flags, extra = _flags(settings)
    cmd = ["yay", "-S", *flags]
    if needed:
        cmd.append("--needed")
    return [*cmd, *extra, "--", *names]


def remove_cmd(names: list[str], settings=None) -> list[str]:
    # 기본 -Rns: 설정 파일과 함께 필요 없어진 의존성까지 제거
    mode = settings.remove_flag() if settings is not None else "Rns"
    return ["yay", f"-{mode}", "--", *names]


def cleanup_cmd(key: str) -> list[str] | None:
    """정리 화면의 각 항목에 대응하는 명령. sudo 는 트랜잭션 창이 받아 준다."""
    return {
        # -k2: 설치본 포함 최근 2개만 남긴다
        "pacman_cache": ["sudo", "paccache", "-r", "-k", "2"],
        "uninstalled": ["sudo", "paccache", "-r", "-u", "-k", "0"],
        # yay 가 자기 빌드 캐시를 정리하게 둔다 (확인 프롬프트는 창에서 답한다)
        "yay_cache": ["yay", "-Sc"],
    }.get(key)


def downgrade_cmd(location: str, settings=None) -> list[str]:
    """`-U` 는 로컬 파일 경로와 URL 을 모두 받는다."""
    _flags_unused, extra = _flags(settings)
    return ["yay", "-U", *extra, "--", location]


def install_reason_cmd(names: list[str], explicit: bool) -> list[str]:
    flag = "--asexplicit" if explicit else "--asdeps"
    return ["sudo", "pacman", "-D", flag, "--", *names]


def upgrade_cmd(names: list[str] | None = None, settings=None) -> list[str]:
    flags, extra = _flags(settings)
    if names:
        return ["yay", "-S", *flags, *extra, "--", *names]
    cmd = ["yay", "-Syu", *flags]
    if settings is not None and settings["devel_updates"]:
        cmd.append("--devel")
    return [*cmd, *extra]
