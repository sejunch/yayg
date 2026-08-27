"""디스크 정리 현황과 다운그레이드 후보. GTK 의존성 없음."""

from __future__ import annotations

import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .backend import BackendError, _run, format_size, parse_info_blocks, _parse_size

PACMAN_CACHE = Path("/var/cache/pacman/pkg")
YAY_CACHE = Path.home() / ".cache" / "yay"
ARCHIVE = "https://archive.archlinux.org/packages"
USER_AGENT = "yayg/0.1"

# <이름>-<버전>-<릴리스>-<아키텍처>.pkg.tar.<zst|xz>
_PKG_RE = re.compile(
    r"^(?P<name>.+)-(?P<version>[^-]+-[^-]+)-(?P<arch>x86_64|any|i686)"
    r"\.pkg\.tar\.(?:zst|xz|gz)$"
)


@dataclass
class Usage:
    key: str             # 정리 동작을 고르는 데 쓰는 식별자
    label: str
    size: int
    count: int
    reclaimable: int = 0
    detail: str = ""


def _dir_size(path: Path) -> tuple[int, int]:
    total = files = 0
    for root, _dirs, names in os.walk(path, onerror=lambda _e: None):
        for name in names:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
                files += 1
            except OSError:
                pass
    return total, files


def _paccache_savings(args: list[str]) -> int:
    """paccache 예행 연습(-d)에서 회수 가능한 바이트."""
    if not shutil.which("paccache"):
        return 0
    rc, out, err = _run(["paccache", "-d", *args], timeout=120)
    text = out + err
    if "no candidate" in text:
        return 0
    # ==> finished dry run: 42 candidates (disk space saved: 1.2 GiB)
    if match := re.search(r"disk space saved:\s*([\d.]+\s*[KMGT]?i?B)", text):
        return _parse_size(match.group(1))
    return 0


def cache_usage() -> list[Usage]:
    """정리 화면에 띄울 항목들. 회수 가능량이 0이면 이미 깨끗하다는 뜻이다."""
    rows: list[Usage] = []

    size, count = _dir_size(PACMAN_CACHE)
    rows.append(Usage(
        "pacman_cache", "pacman 패키지 캐시", size, count,
        reclaimable=_paccache_savings(["-k", "2"]),
        detail=str(PACMAN_CACHE),
    ))

    uninstalled = _paccache_savings(["-u", "-k", "0"])
    if uninstalled:
        rows.append(Usage("uninstalled", "설치되지 않은 패키지의 캐시", uninstalled, 0,
                          reclaimable=uninstalled, detail="이미 지운 패키지의 파일"))

    if YAY_CACHE.is_dir():
        size, count = _dir_size(YAY_CACHE)
        rows.append(Usage("yay_cache", "yay 빌드 캐시", size, count, reclaimable=size,
                          detail=str(YAY_CACHE)))

    orphans = _orphans()
    if orphans:
        total = sum(size for _n, size in orphans)
        rows.append(Usage("orphans", f"고아 패키지 {len(orphans)}개", total, len(orphans),
                          reclaimable=total,
                          detail="아무 패키지도 의존하지 않는 패키지"))
    return rows


def _orphans() -> list[tuple[str, int]]:
    rc, out, _ = _run(["pacman", "-Qdtq"], timeout=30)
    names = [line.strip() for line in out.splitlines() if line.strip()]
    if not names:
        return []
    rc, out, _ = _run(["pacman", "-Qi", *names], timeout=60)
    sizes = {d["Name"]: _parse_size(d.get("Installed Size", ""))
             for d in parse_info_blocks(out) if d.get("Name")}
    return [(n, sizes.get(n, 0)) for n in names]


# -- 다운그레이드 -------------------------------------------------------------

@dataclass
class Version:
    version: str
    source: str          # 'cache' | 'archive'
    location: str        # 로컬 경로 또는 URL
    current: bool = False


def _cache_versions(name: str) -> list[Version]:
    found = []
    try:
        entries = list(PACMAN_CACHE.iterdir())
    except OSError:
        return found
    for entry in entries:
        match = _PKG_RE.match(entry.name)
        if match and match.group("name") == name:
            found.append(Version(match.group("version"), "cache", str(entry)))
    return found


def _archive_versions(name: str) -> list[Version]:
    url = f"{ARCHIVE}/{name[0]}/{urllib.parse.quote(name)}/"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read(4 * 1024 * 1024).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise BackendError(f"Arch 아카이브에 연결하지 못했습니다: {exc}") from exc

    found = []
    for href in re.findall(r'href="([^"]+\.pkg\.tar\.(?:zst|xz|gz))"', html):
        match = _PKG_RE.match(href)
        if match and match.group("name") == name:
            found.append(Version(match.group("version"), "archive", url + href))
    return found


def _version_key(text: str):
    """pacman 의 vercmp 규칙을 정확히 따르지는 않지만, 정렬 표시용으로는 충분하다."""
    return [int(p) if p.isdigit() else p
            for p in re.split(r"[.\-_+]", text.replace(":", "."))]


def downgrade_candidates(name: str, current: str = "",
                         include_archive: bool = True) -> list[Version]:
    """캐시에 있는 것 먼저, 없으면 Arch 아카이브에서. 최신 버전이 위로 온다."""
    versions = {v.version: v for v in _cache_versions(name)}
    if include_archive:
        try:
            for version in _archive_versions(name):
                versions.setdefault(version.version, version)
        except BackendError:
            if not versions:
                raise
    for version in versions.values():
        version.current = version.version == current
    try:
        ordered = sorted(versions.values(), key=lambda v: _version_key(v.version),
                         reverse=True)
    except TypeError:      # 버전 표기가 섞여 비교가 안 되면 문자열 정렬로 물러난다
        ordered = sorted(versions.values(), key=lambda v: v.version, reverse=True)
    return ordered


# -- pacman 로그 이력 ---------------------------------------------------------

PACMAN_LOG = Path("/var/log/pacman.log")

# [2026-08-27T23:22:09+0900] [ALPM] upgraded foo (1.0-1 -> 1.1-1)
_LOG_RE = re.compile(
    r"^\[(?P<stamp>[0-9T:+\-]{19,25})\]\s+\[ALPM\]\s+"
    r"(?P<action>installed|upgraded|downgraded|removed|reinstalled)\s+"
    r"(?P<name>\S+)\s+\((?P<detail>[^)]*)\)"
)

ACTION_LABELS = {
    "installed": "설치", "upgraded": "업그레이드", "downgraded": "다운그레이드",
    "removed": "삭제", "reinstalled": "재설치",
}


@dataclass
class LogEntry:
    stamp: str          # ISO 8601
    action: str
    name: str
    detail: str

    @property
    def label(self) -> str:
        return ACTION_LABELS.get(self.action, self.action)


def history(limit: int = 400) -> list[LogEntry]:
    """pacman.log 의 최근 변경 이력 (최신순)."""
    try:
        with open(PACMAN_LOG, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as exc:
        raise BackendError(f"pacman 로그를 읽지 못했습니다: {exc}") from exc

    entries: list[LogEntry] = []
    for line in reversed(lines):
        if (match := _LOG_RE.match(line)) is None:
            continue
        entries.append(LogEntry(match.group("stamp"), match.group("action"),
                                match.group("name"), match.group("detail")))
        if len(entries) >= limit:
            break
    return entries
