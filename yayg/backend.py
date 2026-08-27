"""yay/pacman 호출과 출력 파싱. GTK 의존성 없음 — 전부 워커 스레드에서 호출된다."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field

# 파싱 대상 출력은 항상 C 로케일로 받는다 (단위 표기와 필드명 고정).
_C_ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}

SEARCH_TIMEOUT = 45
INFO_TIMEOUT = 30


class BackendError(Exception):
    pass


@dataclass
class Package:
    name: str
    version: str = ""
    repo: str = ""
    description: str = ""
    installed: bool = False
    installed_version: str = ""
    new_version: str = ""          # 업데이트 목록에서만 채워짐
    votes: int = 0
    popularity: float = 0.0
    out_of_date: bool = False
    orphaned: bool = False
    size: int = 0                  # 설치 용량(바이트)
    explicit: bool = False
    info: dict = field(default_factory=dict)

    @property
    def is_aur(self) -> bool:
        return self.repo == "aur"

    @property
    def qualified(self) -> str:
        return f"{self.repo}/{self.name}" if self.repo and self.repo != "aur" else self.name


def _run(argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            argv, capture_output=True, text=True, errors="replace",
            env=_C_ENV, timeout=timeout,
        )
    except FileNotFoundError:
        raise BackendError(f"명령을 찾을 수 없습니다: {argv[0]}")
    except subprocess.TimeoutExpired:
        raise BackendError(f"시간 초과: {' '.join(argv)}")
    return p.returncode, p.stdout, p.stderr


# --------------------------------------------------------------------------
# 검색
# --------------------------------------------------------------------------

# 예) aur/zen-browser-bin 1.21.15b-1 (+339 21.10) (Installed: 1.21.8b-1)
#     extra/firefox 154.0-1 (84.4 MiB 294.9 MiB) (Installed)
_HEAD_RE = re.compile(r"^(?P<repo>[^/\s]+)/(?P<name>\S+)\s+(?P<version>\S+)(?P<rest>.*)$")
_VOTES_RE = re.compile(r"\(\+(\d+)\s+([\d.]+)\)")
_INSTALLED_RE = re.compile(r"\(Installed(?::\s*([^)]+))?\)")


def _parse_search(text: str) -> list[Package]:
    out: list[Package] = []
    cur: Package | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[:1].isspace():
            if cur is not None and not cur.description:
                cur.description = line.strip()
            continue
        m = _HEAD_RE.match(line)
        if not m:
            continue
        rest = m.group("rest")
        cur = Package(
            name=m.group("name"),
            version=m.group("version"),
            repo=m.group("repo"),
            out_of_date="(Out-of-date" in rest,
            orphaned="(Orphaned)" in rest,
        )
        if (v := _VOTES_RE.search(rest)):
            cur.votes = int(v.group(1))
            cur.popularity = float(v.group(2))
        if (i := _INSTALLED_RE.search(rest)):
            cur.installed = True
            cur.installed_version = i.group(1) or cur.version
        out.append(cur)
    return out


def search(term: str, include_aur: bool = True, limit: int = 0) -> list[Package]:
    term = term.strip().lstrip("-")
    if not term:
        return []
    argv = ["yay", "-Ss"] + ([] if include_aur else ["--repo"]) + [term]
    rc, out, err = _run(argv, timeout=SEARCH_TIMEOUT)
    if rc != 0 and not out.strip():
        # 결과 없음도 rc=1 이므로, stderr에 실제 오류가 있을 때만 예외로 올린다.
        msg = err.strip()
        if msg and "no results" not in msg.lower():
            raise BackendError(msg.splitlines()[0])
        return []
    pkgs = _parse_search(out)

    q = term.lower()

    def rank(p: Package) -> tuple:
        n = p.name.lower()
        if n == q:
            score = 0
        elif n.startswith(q):
            score = 1
        elif q in n:
            score = 2
        else:
            score = 3
        # 같은 점수면 공식 저장소 먼저, 그다음 AUR 인기순
        return (score, p.is_aur, -p.popularity, n)

    pkgs.sort(key=rank)
    return pkgs[:limit] if limit else pkgs


# --------------------------------------------------------------------------
# 설치된 패키지
# --------------------------------------------------------------------------

_SIZE_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "TiB": 1024 ** 4}
_SIZE_RE = re.compile(r"([\d.]+)\s*([KMGT]?i?B)")


def _parse_size(value: str) -> int:
    m = _SIZE_RE.search(value or "")
    if not m:
        return 0
    return int(float(m.group(1)) * _SIZE_UNITS.get(m.group(2), 1))


def parse_info_blocks(text: str):
    """`pacman -Qi` / `yay -Si` 스타일의 `키 : 값` 블록을 dict 로 변환."""
    for block in re.split(r"\n\s*\n", text):
        if not block.strip():
            continue
        data: dict[str, str] = {}
        key = None
        for line in block.splitlines():
            if line[:1].isspace() and key:
                data[key] += " " + line.strip()
                continue
            k, sep, v = line.partition(":")
            if not sep:
                continue
            key = k.strip()
            data[key] = v.strip()
        if data:
            yield data


def installed_packages() -> list[Package]:
    rc, out, err = _run(["pacman", "-Qi"], timeout=90)
    if rc != 0:
        raise BackendError(err.strip() or "pacman -Qi 실패")

    foreign = set(_lines(_run(["pacman", "-Qmq"], timeout=30)[1]))
    orphans = set(_lines(_run(["pacman", "-Qdtq"], timeout=30)[1]))

    pkgs = []
    for d in parse_info_blocks(out):
        name = d.get("Name")
        if not name:
            continue
        pkgs.append(Package(
            name=name,
            version=d.get("Version", ""),
            repo="aur" if name in foreign else "local",
            description=d.get("Description", ""),
            installed=True,
            installed_version=d.get("Version", ""),
            size=_parse_size(d.get("Installed Size", "")),
            explicit=d.get("Install Reason", "").startswith("Explicitly"),
            orphaned=name in orphans,
            info=d,
        ))
    pkgs.sort(key=lambda p: p.name)
    return pkgs


def _lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]


# --------------------------------------------------------------------------
# 업데이트
# --------------------------------------------------------------------------

# 예) firefox 143.0.1-1 -> 154.0-1
_UPD_RE = re.compile(r"^(?P<name>\S+)\s+(?P<old>\S+)\s+->\s+(?P<new>\S+)")


def _parse_updates(text: str, repo: str) -> list[Package]:
    out = []
    for line in text.splitlines():
        m = _UPD_RE.match(line.strip())
        if not m:
            continue
        out.append(Package(
            name=m.group("name"),
            version=m.group("new"),
            new_version=m.group("new"),
            installed=True,
            installed_version=m.group("old"),
            repo=repo,
        ))
    return out


def check_updates(source: str = "checkupdates", include_aur: bool = True,
                  devel: bool = False) -> list[Package]:
    """저장소 업데이트는 checkupdates(임시 DB 사용 — 부분 업그레이드 위험 없음),
    AUR 업데이트는 `yay -Qua` 로 확인한다.

    `yay -Qu --repo` 는 마지막으로 동기화한 로컬 DB와 비교하므로, 한동안
    `-Sy` 를 하지 않았다면 업데이트가 없는 것처럼 보인다."""
    pkgs: list[Package] = []

    if source == "checkupdates" and shutil.which("checkupdates"):
        rc, out, err = _run(["checkupdates"], timeout=120)
        # rc 2 = 업데이트 없음, rc 1 = 실제 오류
        if rc not in (0, 2):
            raise BackendError(err.strip() or "checkupdates 실패")
        pkgs += _parse_updates(out, "repo")
    else:
        rc, out, _ = _run(["yay", "-Qu", "--repo"], timeout=120)
        pkgs += _parse_updates(out, "repo")

    if include_aur:
        argv = ["yay", "-Qua"] + (["--devel"] if devel else [])
        rc, out, err = _run(argv, timeout=300 if devel else 180)
        if rc not in (0, 1):
            raise BackendError(err.strip() or "yay -Qua 실패")
        pkgs += _parse_updates(out, "aur")

    pkgs.sort(key=lambda p: (p.repo != "repo", p.name))
    return pkgs


# --------------------------------------------------------------------------
# 상세 정보
# --------------------------------------------------------------------------

def package_info(pkg: Package) -> dict:
    """설치된 패키지는 로컬 DB에서, 아니면 yay -Si 로 (AUR은 네트워크 조회)."""
    if pkg.installed:
        rc, out, _ = _run(["pacman", "-Qi", pkg.name], timeout=INFO_TIMEOUT)
        if rc == 0:
            for d in parse_info_blocks(out):
                return d
    rc, out, err = _run(["yay", "-Si", pkg.qualified], timeout=INFO_TIMEOUT)
    if rc != 0:
        raise BackendError(err.strip().splitlines()[0] if err.strip() else "정보를 가져오지 못했습니다")
    for d in parse_info_blocks(out):
        return d
    return {}


def removal_preview(names: list[str], mode: str = "Rns") -> list[Package]:
    """`-Rns` 로 실제 제거될 패키지 전체. 의존성 연쇄까지 포함한다.

    pacman 은 `--nosave`(-n)와 `--print` 를 같이 쓰지 못하게 막는다. -n 은 설정
    파일 보존 여부만 바꾸고 제거 대상 집합에는 영향이 없으므로 빼고 물어본다.
    root 권한은 필요 없다."""
    flags = mode.replace("n", "") or "R"
    rc, out, err = _run(
        ["pacman", f"-{flags}", "--print", "--print-format", "%n %v", *names],
        timeout=60,
    )
    if rc != 0:
        raise BackendError(err.strip().splitlines()[0] if err.strip()
                           else "제거 대상을 계산하지 못했습니다")

    targets: list[Package] = []
    requested = set(names)
    for line in out.splitlines():
        name, _, version = line.strip().partition(" ")
        if not name:
            continue
        targets.append(Package(name=name, version=version, installed=True,
                               explicit=name in requested))

    # 회수 용량은 따로 물어봐야 한다 (--print-format 에 크기가 없다)
    if targets:
        rc, out, _ = _run(["pacman", "-Qi", *[p.name for p in targets]], timeout=60)
        if rc == 0:
            sizes = {d["Name"]: _parse_size(d.get("Installed Size", ""))
                     for d in parse_info_blocks(out) if d.get("Name")}
            for pkg in targets:
                pkg.size = sizes.get(pkg.name, 0)

    # 직접 고른 것 먼저, 그다음 이름순
    targets.sort(key=lambda p: (not p.explicit, p.name))
    return targets


def is_installed(name: str) -> bool:
    return _run(["pacman", "-Qq", name], timeout=15)[0] == 0


def format_size(n: int) -> str:
    if n <= 0:
        return "—"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GiB"
