"""Netzzugriff fuer Kaufrecherche und Buch-/Filmdaten.

Bewusst eng gehalten: Es geht nur ein Suchbegriff hinaus, nie Notizen,
Aufgaben oder sonst etwas aus deiner Datenbank. Mit ALLOW_WEB=0 ist hier
komplett Schluss, dann arbeitet Kompass rein örtlich.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

from ..config import ALLOW_WEB, SEARXNG_URL, TMDB_API_KEY

log = logging.getLogger("kompass.web")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9,en;q=0.6"}


class WebDisabled(Exception):
    pass


def enabled() -> bool:
    return bool(ALLOW_WEB)


def search(query: str, limit: int = 6) -> list[dict[str, str]]:
    """Websuche. Eigene SearXNG-Instanz, sonst DuckDuckGo."""
    if not ALLOW_WEB:
        raise WebDisabled("Internetzugriff ist abgeschaltet (ALLOW_WEB=0).")
    if SEARXNG_URL:
        hits = _searxng(query, limit)
        if hits:
            return hits
    return _duckduckgo(query, limit)


def _searxng(query: str, limit: int) -> list[dict[str, str]]:
    try:
        r = httpx.get(f"{SEARXNG_URL}/search",
                      params={"q": query, "format": "json", "language": "de"},
                      headers=HEADERS, timeout=20)
        r.raise_for_status()
        out = []
        for item in (r.json().get("results") or [])[:limit]:
            out.append({"title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", "")})
        return out
    except (httpx.HTTPError, ValueError) as e:
        log.warning("SearXNG antwortet nicht (%s) — weiche auf DuckDuckGo aus.", e)
        return []


_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.S)
_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(?P<text>.*?)</a>', re.S)


def _duckduckgo(query: str, limit: int) -> list[dict[str, str]]:
    try:
        r = httpx.post("https://html.duckduckgo.com/html/",
                       data={"q": query, "kl": "de-de"},
                       headers=HEADERS, timeout=25, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("Suche fehlgeschlagen: %s", e)
        return []
    titles = _RESULT_RE.findall(r.text)
    snippets = _SNIPPET_RE.findall(r.text)
    out: list[dict[str, str]] = []
    for i, (url, title) in enumerate(titles[:limit]):
        out.append({
            "title": _text(title),
            "url": _unwrap(html.unescape(url)),
            "snippet": _text(snippets[i]) if i < len(snippets) else "",
        })
    return out


def _unwrap(url: str) -> str:
    """DuckDuckGo verpackt Ziele in einen eigenen Weiterleitungslink."""
    if "duckduckgo.com/l/" in url:
        query = parse_qs(urlparse(url).query)
        if query.get("uddg"):
            return query["uddg"][0]
    if url.startswith("//"):
        return "https:" + url
    return url


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)


def _text(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", raw))).strip()


def fetch_text(url: str, limit: int = 6000) -> str:
    """Eine Seite holen und auf reinen Text eindampfen."""
    if not ALLOW_WEB:
        raise WebDisabled("Internetzugriff ist abgeschaltet (ALLOW_WEB=0).")
    try:
        r = httpx.get(url, headers=HEADERS, timeout=25, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.info("Seite nicht lesbar (%s): %s", url, e)
        return ""
    if "text/html" not in r.headers.get("content-type", "text/html"):
        return ""
    body = _SCRIPT_RE.sub(" ", r.text)
    return _text(body)[:limit]


# ------------------------------------------------------- Bücher und Filme

def openlibrary(title: str, limit: int = 5) -> list[dict[str, Any]]:
    """Buchdaten von OpenLibrary — frei, ohne Schlüssel."""
    if not ALLOW_WEB:
        return []
    try:
        r = httpx.get("https://openlibrary.org/search.json",
                      params={"q": title, "limit": limit, "lang": "ger"},
                      headers=HEADERS, timeout=20)
        r.raise_for_status()
        docs = r.json().get("docs") or []
    except (httpx.HTTPError, ValueError) as e:
        log.info("OpenLibrary antwortet nicht: %s", e)
        return []
    out = []
    for d in docs[:limit]:
        out.append({
            "title": d.get("title"),
            "creator": ", ".join((d.get("author_name") or [])[:2]) or None,
            "year": d.get("first_publish_year"),
            "url": f"https://openlibrary.org{d.get('key')}" if d.get("key") else None,
            "subjects": (d.get("subject") or [])[:6],
        })
    return out


def tmdb(title: str, kind: str = "movie", limit: int = 5) -> list[dict[str, Any]]:
    """Film- und Seriendaten. Nur wenn ein TMDB-Schlüssel hinterlegt ist."""
    if not ALLOW_WEB or not TMDB_API_KEY:
        return []
    path = "tv" if kind == "series" else "movie"
    try:
        r = httpx.get(f"https://api.themoviedb.org/3/search/{path}",
                      params={"api_key": TMDB_API_KEY, "query": title,
                              "language": "de-DE"},
                      headers=HEADERS, timeout=20)
        r.raise_for_status()
        results = r.json().get("results") or []
    except (httpx.HTTPError, ValueError) as e:
        log.info("TMDB antwortet nicht: %s", e)
        return []
    out = []
    for d in results[:limit]:
        date_str = d.get("release_date") or d.get("first_air_date") or ""
        out.append({
            "title": d.get("title") or d.get("name"),
            "year": int(date_str[:4]) if date_str[:4].isdigit() else None,
            "why": (d.get("overview") or "")[:400],
            "url": f"https://www.themoviedb.org/{path}/{d.get('id')}",
            "rating": d.get("vote_average"),
        })
    return out


def price_query(title: str) -> str:
    return f"{title} Preis kaufen"


def review_query(title: str) -> str:
    return f"{title} Test Erfahrungen Nachteile"


def alternative_query(title: str) -> str:
    return f"{title} Alternative günstiger Vergleich"


def quote(term: str) -> str:
    return quote_plus(term)
