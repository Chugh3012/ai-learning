from __future__ import annotations

import html
import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit

_MAX_REDIRECTS = 4
_MAX_BYTES = 3_000_000
_TIMEOUT = 10
_UA = "Mozilla/5.0 (compatible; ai-scout/1.0)"

class _PinnedHTTPConnection(http.client.HTTPConnection):
    # Connect to a pre-validated IP (no second DNS lookup) so the address we vetted is the
    # address we talk to — closes the DNS-rebinding / TOCTOU window. Host header stays the
    # real hostname (http.client sets it from self.host).
    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)

class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        # SNI + certificate validation use the real hostname, not the pinned IP.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)

def clean(text: str, limit: int = 900) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]

def digest_item_ids(md: str) -> list[int]:
    # A delivered digest ends with a machine-readable footer of the items it featured, in rank
    # order: "<!-- items: 12,7,30 -->" (see DeliverySink). Consumers (reel render) read this to
    # act on exactly what kb-sync selected, instead of re-running selection. Empty if absent.
    m = re.search(r"<!--\s*items:\s*([\d,\s]+?)\s*-->", md or "")
    return [int(x) for x in m.group(1).split(",") if x.strip().isdigit()] if m else []

def _ip_is_public(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # Allow ONLY globally-routable addresses. is_global already excludes private, loopback,
    # link-local, CGNAT (100.64.0.0/10), and reserved space; the explicit denies are belt-
    # and-suspenders across Python versions.
    return ip.is_global and not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified)

def _resolve_public_ip(host: str, port: int) -> str:
    # Resolve and require EVERY returned address to be public; return the first to pin.
    # Empty string if resolution fails or any address is non-global (fail closed).
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    addrs = [info[4][0] for info in infos]
    if not addrs or not all(_ip_is_public(a) for a in addrs):
        return ""
    return addrs[0]

def is_safe_public_url(url: str) -> bool:
    # SSRF guard for fetching attacker-influenced (feed item) URLs: only http(s), and the
    # host must resolve exclusively to public IPs. Blocks localhost, private ranges, CGNAT,
    # and the cloud metadata endpoint (169.254.169.254). Fails closed if unverifiable.
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        port = parts.port or (443 if parts.scheme == "https" else 80)
        return bool(_resolve_public_ip(parts.hostname, port))
    except Exception:
        return False

def _fetch_html(url: str) -> str:
    # Redirect-safe, rebinding-safe fetch: for EVERY hop resolve + validate the host, then
    # connect to the exact validated IP (pinned). Caps the redirect chain and body size.
    # Returns "" on any unsafe hop, error, or oversize response.
    for _ in range(_MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return ""
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            ip = _resolve_public_ip(parts.hostname, port)
        except Exception:
            return ""
        if not ip:
            return ""
        conn_cls = _PinnedHTTPSConnection if parts.scheme == "https" else _PinnedHTTPConnection
        kwargs = {"port": port, "timeout": _TIMEOUT}
        if parts.scheme == "https":
            kwargs["context"] = ssl.create_default_context()
        conn = conn_cls(parts.hostname, ip, **kwargs)
        try:
            path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            conn.request("GET", path, headers={"User-Agent": _UA, "Accept": "text/html",
                                               "Connection": "close"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location")
                if not loc:
                    return ""
                url = urljoin(url, loc)
                continue
            data = resp.read(_MAX_BYTES + 1)
            if len(data) > _MAX_BYTES:
                return ""
            ctype = resp.getheader("Content-Type", "") or ""
            m = re.search(r"charset=([\w-]+)", ctype)
            return data.decode(m.group(1) if m else "utf-8", "replace")
        except Exception:
            return ""
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return ""

def fulltext(url: str, limit: int = 2500) -> str:
    if not url:
        return ""
    downloaded = _fetch_html(url)
    if not downloaded:
        return ""
    try:
        import trafilatura
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        return clean(text or "", limit)
    except Exception:
        return ""
