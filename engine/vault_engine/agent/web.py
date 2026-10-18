"""Keyless web search (DuckDuckGo HTML endpoint) and readable-text page fetching."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from pydantic import BaseModel

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
MAX_PAGE_BYTES = 3 * 2**20


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str


class WebError(RuntimeError):
    pass


class _DdgParser(HTMLParser):
    """Collects result links (a.result__a) and their snippets (.result__snippet)."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict] = []
        self._field: str | None = None

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class") or ""
        if tag == "a" and "result__a" in classes:
            self.results.append({"title": "", "url": dict(attrs).get("href") or "", "snippet": ""})
            self._field = "title"
        elif "result__snippet" in classes and self.results:
            self._field = "snippet"

    def handle_endtag(self, tag):
        if tag in ("a", "td", "div"):
            self._field = None

    def handle_data(self, data):
        if self._field and self.results:
            self.results[-1][self._field] += data


def _real_url(href: str) -> str:
    # Result links go through DuckDuckGo's redirect: //duckduckgo.com/l/?uddg=<target>
    if "uddg=" in href:
        target = parse_qs(urlparse(href).query).get("uddg", [""])[0]
        return unquote(target)
    return href if href.startswith("http") else "https:" + href if href.startswith("//") else href


async def web_search(query: str, max_results: int = 6, region: str = "it-it") -> list[WebResult]:
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        try:
            resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query, "kl": region})
        except httpx.HTTPError as exc:
            raise WebError(f"ricerca web non riuscita: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise WebError(f"DuckDuckGo ha risposto HTTP {resp.status_code} (possibile limite di frequenza)")
    parser = _DdgParser()
    parser.feed(resp.text)
    results = []
    for item in parser.results:
        url = _real_url(item["url"])
        # Skip ads, which point back into duckduckgo.com/y.js.
        if not url.startswith("http") or "duckduckgo.com" in urlparse(url).netloc:
            continue
        results.append(WebResult(title=_clean(item["title"]), url=url, snippet=_clean(item["snippet"])))
        if len(results) >= max_results:
            break
    if not results and "anomaly" in resp.text.lower():
        raise WebError("DuckDuckGo ha bloccato la richiesta come automatica; riprova più tardi")
    return results


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "iframe", "template"}
    BLOCK = {"p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3") and not self._skip:
            self.parts.append("#" * int(tag[1]) + " ")
        if tag == "li" and not self._skip:
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return _clean(parser.title), text.strip()


async def fetch_url(url: str, max_chars: int = 12000) -> dict:
    if not re.match(r"^https?://", url):
        raise WebError("sono ammessi solo URL http(s)")
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        try:
            async with client.stream("GET", url) as resp:
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_PAGE_BYTES:
                        break
                status, ctype, final_url = resp.status_code, resp.headers.get("content-type", ""), str(resp.url)
                encoding = resp.encoding or "utf-8"
        except httpx.HTTPError as exc:
            raise WebError(f"download non riuscito: {type(exc).__name__}") from exc
    if status >= 400:
        raise WebError(f"HTTP {status}")
    raw = body.decode(encoding, errors="replace")
    if "html" in ctype or raw.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        title, text = html_to_text(raw)
    elif ctype.startswith("text/") or "json" in ctype:
        title, text = "", raw
    else:
        raise WebError(f"tipo di contenuto non supportato: {ctype or 'sconosciuto'}")
    truncated = len(text) > max_chars
    return {"url": final_url, "title": title, "text": text[:max_chars], "truncated": truncated}
