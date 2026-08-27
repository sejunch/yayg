"""Arch 뉴스와 마지막 전체 업그레이드 시각. GTK 의존성 없음.

Arch 에서 가장 흔한 사고가 "수동 개입 필요" 공지를 못 보고 `-Syu` 하는 것이다.
업그레이드 직전에 마지막 업그레이드 이후 올라온 공지를 보여주기 위한 모듈.
"""

from __future__ import annotations

import datetime as _dt
import html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

FEED_URL = "https://archlinux.org/feeds/news/"
PACMAN_LOG = "/var/log/pacman.log"
USER_AGENT = "yayg/0.1"
TIMEOUT = 15

# 공지 문구는 영어 고정이다. 수동 개입이 필요한 글을 눈에 띄게 하려는 목적.
_INTERVENTION_RE = re.compile(
    r"manual intervention|requires? (?:manual|user) |action (?:is )?required"
    r"|before (?:upgrading|updating)|do not upgrade|breaking change",
    re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")


class NewsError(Exception):
    pass


@dataclass
class NewsItem:
    title: str
    url: str
    date: _dt.datetime | None
    summary: str
    needs_intervention: bool


def _strip_html(text: str, limit: int = 400) -> str:
    plain = html.unescape(_TAG_RE.sub(" ", text or ""))
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:limit] + ("…" if len(plain) > limit else "")


def fetch(limit: int = 15) -> list[NewsItem]:
    request = urllib.request.Request(FEED_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(1024 * 1024)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise NewsError(f"Arch 뉴스를 가져오지 못했습니다: {exc}") from exc

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise NewsError("뉴스 피드를 해석하지 못했습니다") from exc

    items = []
    for element in root.iter("item"):
        title = (element.findtext("title") or "").strip()
        if not title:
            continue
        raw_date = element.findtext("pubDate")
        date = None
        if raw_date:
            try:
                date = parsedate_to_datetime(raw_date)
            except (TypeError, ValueError):
                date = None
        body = element.findtext("description") or ""
        items.append(NewsItem(
            title=title,
            url=(element.findtext("link") or "").strip(),
            date=date,
            summary=_strip_html(body),
            needs_intervention=bool(_INTERVENTION_RE.search(title + " " + body)),
        ))
        if len(items) >= limit:
            break
    return items


def last_full_upgrade() -> _dt.datetime | None:
    """pacman.log 에서 마지막 `-Syu` 시각. 뉴스를 어디까지 읽었는지 기준이 된다."""
    stamp = None
    try:
        with open(PACMAN_LOG, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "starting full system upgrade" not in line:
                    continue
                if match := re.match(r"\[([0-9T:+\-]{19,25})\]", line):
                    try:
                        stamp = _dt.datetime.fromisoformat(match.group(1))
                    except ValueError:
                        continue
    except OSError:
        return None
    return stamp


def since(items: list[NewsItem], moment: _dt.datetime | None) -> list[NewsItem]:
    """moment 이후에 올라온 공지만. moment 가 없으면 개입이 필요한 것만 남긴다."""
    if moment is None:
        return [i for i in items if i.needs_intervention]
    cutoff = moment
    if cutoff.tzinfo is None:
        cutoff = cutoff.astimezone()
    result = []
    for item in items:
        if item.date is None:
            continue
        stamp = item.date if item.date.tzinfo else item.date.astimezone()
        if stamp > cutoff:
            result.append(item)
    return result
