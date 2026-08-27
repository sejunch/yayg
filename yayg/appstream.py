"""AppStream 카탈로그의 스크린샷. GTK 의존성 없음.

`archlinux-appstream-data` 는 아이콘은 로컬에 캐시해 두지만 스크린샷은 원본
URL 만 담고 있다. 즉 스크린샷을 보려면 각 프로젝트 웹사이트에 직접 접속하게
된다. 그래서 기본값은 꺼짐이고, 켠 뒤에는 받은 이미지를 로컬에 캐시한다.
"""

from __future__ import annotations

import gzip
import hashlib
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

CATALOG_DIRS = (Path("/usr/share/swcatalog/xml"), Path("/usr/share/app-info/xml"))
CACHE_DIR = Path.home() / ".cache" / "yayg" / "screenshots"
USER_AGENT = "yayg/0.1"
TIMEOUT = 20
MAX_BYTES = 8 * 1024 * 1024


class _Index:
    def __init__(self):
        self._lock = threading.Lock()
        self._ready = False
        self._shots: dict[str, list[str]] = {}

    def ensure(self) -> None:
        with self._lock:
            if self._ready:
                return
            self._build()
            self._ready = True

    def _build(self) -> None:
        root_dir = next((d for d in CATALOG_DIRS if d.is_dir()), None)
        if root_dir is None:
            return
        for path in sorted(root_dir.glob("*.xml.gz")):
            try:
                root = ET.fromstring(gzip.open(path).read())
            except (OSError, ET.ParseError, EOFError):
                continue
            for component in root:
                name = component.findtext("pkgname")
                if not name or name in self._shots:
                    continue
                urls = [(image.text or "").strip()
                        for image in component.findall("screenshots/screenshot/image")
                        if (image.text or "").strip().startswith("https://")]
                if urls:
                    # 같은 스크린샷의 여러 크기가 섞여 나오므로 중복을 없앤다
                    self._shots[name] = list(dict.fromkeys(urls))

    def urls(self, name: str, limit: int = 4) -> list[str]:
        if not self._ready:
            return []
        return self._shots.get(name, [])[:limit]


_index = _Index()


def index() -> _Index:
    return _index


def screenshots(name: str, limit: int = 4) -> list[str]:
    _index.ensure()
    return _index.urls(name, limit)


def cached_path(url: str) -> Path:
    suffix = Path(url).suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        suffix = ".img"
    return CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:32] + suffix)


def download(url: str) -> str | None:
    """이미 받은 것은 그대로 쓴다. 실패하면 None."""
    target = cached_path(url)
    if target.exists() and target.stat().st_size > 0:
        return str(target)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = response.read(MAX_BYTES)
        if not data:
            return None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(data)
        temporary.replace(target)
        return str(target)
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
