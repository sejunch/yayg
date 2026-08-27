"""AUR에서 PKGBUILD와 함께 딸려오는 로컬 파일을 받아온다. GTK 의존성 없음.

`yay -G` 는 git clone 을 하므로 "설치 전에 잠깐 훑어본다"는 용도에는 무겁다.
여기서는 AUR RPC 로 pkgbase 를 알아낸 뒤 cgit 의 plain 뷰에서 파일만 가져온다.
"""

from __future__ import annotations

import json
import re
import shlex
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AUR_BASE = "https://aur.archlinux.org"
USER_AGENT = "yayg/0.1 (https://aur.archlinux.org)"
TIMEOUT = 20
MAX_BYTES = 512 * 1024


class AurError(Exception):
    pass


def _get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read(MAX_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise AurError(f"AUR 응답 오류 {exc.code}: {url.rsplit('/', 1)[-1]}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise AurError(f"AUR에 연결하지 못했습니다: {exc}") from exc


def package_meta(name: str) -> dict:
    url = f"{AUR_BASE}/rpc/v5/info?arg[]={urllib.parse.quote(name)}"
    try:
        payload = json.loads(_get(url))
    except ValueError as exc:
        raise AurError("AUR 응답을 해석하지 못했습니다") from exc
    results = payload.get("results") or []
    if not results:
        raise AurError(f"AUR에 '{name}' 패키지가 없습니다")
    return results[0]


def _plain(base: str, filename: str) -> str:
    return _get(
        f"{AUR_BASE}/cgit/aur.git/plain/{urllib.parse.quote(filename)}"
        f"?h={urllib.parse.quote(base)}"
    )


# -- PKGBUILD 안의 로컬 파일 찾기 ---------------------------------------------

_ASSIGN_RE = re.compile(r"^[ \t]*(\w+)[ \t]*=[ \t]*(\()?", re.M)
_VAR_RE = re.compile(r"\$\{?(pkgname|pkgbase)\}?")


def _assignment_bodies(text: str, names: set[str]) -> list[str]:
    """`install=...` / `source=(...)` / `source_x86_64=(...)` 의 우변을 모은다."""
    bodies = []
    for match in _ASSIGN_RE.finditer(text):
        key = match.group(1)
        if key.split("_")[0] not in names:
            continue
        if match.group(2):  # 배열 — 괄호 균형이 맞을 때까지 읽는다
            depth, index = 1, match.end()
            while index < len(text) and depth:
                if text[index] == "(":
                    depth += 1
                elif text[index] == ")":
                    depth -= 1
                index += 1
            bodies.append(text[match.end():index - 1])
        else:
            end = text.find("\n", match.end())
            bodies.append(text[match.end():end if end != -1 else len(text)])
    return bodies


def local_files(pkgbuild: str, base: str) -> list[str]:
    """PKGBUILD 와 같은 저장소에 들어 있는 파일 이름들 (.install, 패치 등)."""
    found: list[str] = []
    for body in _assignment_bodies(pkgbuild, {"install", "source"}):
        try:
            tokens = shlex.split(body, comments=True)
        except ValueError:
            continue
        for token in tokens:
            token = token.rsplit("::", 1)[-1]          # name::url 형태
            if "://" in token or not token:
                continue
            token = _VAR_RE.sub(base, token)
            if "$" in token or "/" in token:           # 값을 못 펼쳤거나 경로면 건너뛴다
                continue
            if token not in found:
                found.append(token)
    return found


# yay 는 AUR 저장소를 여기에 clone 해 둔다. 마지막으로 빌드한 시점의 PKGBUILD 가
# 남아 있으므로, 업데이트할 때 "지난번에 승인한 것에서 뭐가 바뀌었나" 를 볼 수 있다.
YAY_CACHE = Path.home() / ".cache" / "yay"


def cached_file(base: str, filename: str) -> str | None:
    """마지막으로 빌드했을 때의 파일 내용. 없으면 None."""
    try:
        return (YAY_CACHE / base / filename).read_text(errors="replace")
    except OSError:
        return None


def fetch_sources(name: str) -> dict:
    """{'base', 'meta', 'files': {이름: 내용}, 'cached': {이름: 이전 내용}, 'missing': [...]}"""
    meta = package_meta(name)
    base = meta.get("PackageBase") or name

    pkgbuild = _plain(base, "PKGBUILD")
    files = {"PKGBUILD": pkgbuild}
    missing = []
    for filename in local_files(pkgbuild, base)[:8]:   # 너무 많으면 앞의 몇 개만
        try:
            files[filename] = _plain(base, filename)
        except AurError:
            missing.append(filename)                   # 릴리스 tarball 등은 저장소에 없다

    cached = {}
    for filename in files:
        if (previous := cached_file(base, filename)) is not None:
            cached[filename] = previous

    return {"base": base, "meta": meta, "files": files,
            "cached": cached, "missing": missing}


# -- 눈으로 확인할 지점 표시 ---------------------------------------------------
# 보안 검사가 아니다. 어차피 PKGBUILD 전체를 읽어야 하고, 이건 그중 흔히 문제가
# 되는 표현에 눈을 먼저 가게 하려는 표시일 뿐이다. 정상적인 쓰임도 많다.

NOTABLE = [
    (re.compile(r"(?:curl|wget)[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z|k)?sh"), "내려받은 내용을 바로 셸로 실행"),
    (re.compile(r"\bsudo\b"), "sudo 호출"),
    (re.compile(r"\beval\b"), "eval"),
    (re.compile(r"base64\s+(?:-d|--decode)"), "base64 디코드"),
    (re.compile(r"\bchmod\s+(?:-R\s+)?0?777\b"), "777 권한"),
    (re.compile(r"/etc/(?:passwd|shadow|sudoers|sudoers\.d)"), "민감한 시스템 파일"),
    (re.compile(r"\b(?:crontab|systemctl\s+enable|systemd-run)\b"), "자동 실행 등록"),
    (re.compile(r"\b(?:nc|ncat|netcat)\s+-"), "netcat"),
    (re.compile(r"http://"), "암호화되지 않은 http:// 주소"),
]


def notable_lines(text: str) -> dict[int, list[str]]:
    """{줄 번호(0부터): [사유, ...]}"""
    hits: dict[int, list[str]] = {}
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pattern, reason in NOTABLE:
            if pattern.search(line):
                hits.setdefault(index, []).append(reason)
    return hits
