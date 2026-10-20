"""Keyless web search (DuckDuckGo HTML endpoint) and readable-text page fetching."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import urllib.request
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from pydantic import BaseModel

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
MAX_PAGE_BYTES = 3 * 2**20
MAX_REDIRECTS = 5

# Destinations the fetch agent must never reach: the local machine, LAN hosts and
# link-local/CGNAT ranges (SSRF). Checked on every resolved IP of every redirect hop.
_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8", "10.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
        "192.168.0.0/16", "100.64.0.0/10",  # RFC 1918 + loopback + link-local + CGNAT
        "198.18.0.0/15",  # benchmarking range (RFC 2544): not routable
        "::/128", "::1/128", "fc00::/7", "fe80::/10",
        "64:ff9b::/96",  # NAT64 embeds arbitrary IPv4, loopback/LAN included (Bug #12)
    )
)


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Bug #12: an IPv4-mapped IPv6 literal (::ffff:127.0.0.1) belongs to no IPv4
    # network object, but on dual-stack hosts (Windows is one) it reaches the same
    # local services — judge it by the embedded IPv4 address.
    mapped = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) else None
    if mapped is not None:
        ip = mapped
    if any(ip in net for net in _BLOCKED_NETWORKS):
        return True
    # Belt and braces beyond the explicit list: the ipaddress registry properties
    # cover documentation ranges, 240/4 and future special-purpose assignments.
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    )


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str


class WebError(RuntimeError):
    pass


async def _validate_url(url: str) -> list[str]:
    """Resolves the host and rejects private/loopback/link-local destinations (SSRF guard).

    Returns the validated IP addresses. Callers should connect to one of THESE
    IPs (see _pinned_target): resolving the name again at connection time would
    reopen the DNS-rebinding window (Miglioramento #16)."""
    parsed = httpx.URL(url)
    host = parsed.host
    if not host:
        raise WebError("URL senza host")
    try:
        ips = [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, parsed.port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise WebError(f"host non risolvibile: {host}") from exc
        ips = list(dict.fromkeys(str(ipaddress.ip_address(info[4][0])) for info in infos))
    blocked = [ip for ip in ips if _is_blocked(ipaddress.ip_address(ip))]
    if blocked:
        raise WebError(f"destinazione privata o locale non consentita: {host} ({', '.join(blocked)})")
    return ips


def _pinned_target(url: str, ip: str) -> tuple[httpx.URL, dict[str, str], dict]:
    """Builds the request target that pins the connection to an ALREADY VALIDATED IP.

    DNS rebinding closes: between the SSRF check and the connection a hostile DNS
    (TTL 0) could swap a public IP for 127.0.0.1, because httpx would resolve the
    name a second time. Connecting to the validated IP removes the second lookup;
    the original Host header and TLS SNI are preserved so name-based hosting and
    certificates keep working."""
    parsed = httpx.URL(url)
    host = parsed.host  # brackets stripped by httpx for IPv6 literals
    bracketed_host = f"[{host}]" if ":" in host else host
    bracketed_ip = f"[{ip}]" if ":" in ip else ip
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    host_header = bracketed_host if port == default_port else f"{bracketed_host}:{port}"
    headers = {"Host": host_header}
    extensions = {"sni_hostname": host} if parsed.scheme == "https" else {}
    return parsed.copy_with(host=bracketed_ip), headers, extensions


def _proxy_for(url: str) -> str | None:
    """Bug #29: se per questa URL è attivo un proxy (variabili d'ambiente o, su
    Windows, il registro di sistema), la risoluzione DNS la fa il proxy e fissare
    l'IP è inutile — anzi il CONNECT verso un IP numerico viene rifiutato dai proxy
    che filtrano per nome. In quel caso la richiesta va inviata per nome host."""
    parsed = httpx.URL(url)
    host = parsed.host
    try:
        if urllib.request.proxy_bypass(host):
            return None
        proxies = urllib.request.getproxies()  # env + registro di sistema su Windows
    except Exception:
        return None
    return proxies.get(parsed.scheme) or proxies.get("all")


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
        raise WebError("sono ammesse solo URL http(s)")
    current = url
    # Redirects are followed manually so EVERY hop's destination is validated:
    # a public page must not be able to bounce the agent onto 127.0.0.1 or the LAN.
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        try:
            for _ in range(MAX_REDIRECTS + 1):
                ips = await _validate_url(current)
                # Bug #29: dietro un proxy la risoluzione la fa il proxy e il pinning
                # dell'IP romperebbe la richiesta (CONNECT per IP numerico rifiutato):
                # si invia per nome host. Senza proxy si fissano gli IP già validati,
                # in ordine (Miglioramento #20: al ConnectError si prova il successivo).
                targets = [(httpx.URL(current), {}, {})] if _proxy_for(current) else [_pinned_target(current, ip) for ip in ips]
                for attempt, (pinned, hop_headers, extensions) in enumerate(targets):
                    try:
                        async with client.stream("GET", pinned, headers=hop_headers, extensions=extensions, follow_redirects=False) as resp:
                            # bytearray: body += chunk on bytes copies the whole buffer per block.
                            body = bytearray()
                            async for chunk in resp.aiter_bytes():
                                body += chunk
                                if len(body) > MAX_PAGE_BYTES:
                                    break
                            status, ctype = resp.status_code, resp.headers.get("content-type", "")
                            location = resp.headers.get("location")
                            encoding = resp.encoding or "utf-8"
                        break  # tentativo riuscito
                    except httpx.ConnectError:
                        if attempt == len(targets) - 1:
                            raise
                        continue  # Miglioramento #20: prossimo IP validato
                else:
                    raise WebError("connessione non riuscita")
                if status in (301, 302, 303, 307, 308) and location:
                    current = urljoin(current, location)
                    continue
                final_url = current  # the original (unpinned) URL, not the IP
                break
            else:
                raise WebError(f"troppi redirect (oltre {MAX_REDIRECTS})")
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
