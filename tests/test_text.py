import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.lib import text


def _resolves_to(*ips):
    def fake(host, port, *a, **k):
        out = []
        for ip in ips:
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            out.append((fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 80)))
        return out
    return fake


class TestIpClassification(unittest.TestCase):
    def test_public_ipv4_allowed(self):
        self.assertTrue(text._ip_is_public("93.184.216.34"))

    def test_public_ipv6_allowed(self):
        self.assertTrue(text._ip_is_public("2606:2800:220:1:248:1893:25c8:1946"))

    def test_private_and_special_rejected(self):
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.10", "172.16.0.1",
                   "169.254.169.254", "0.0.0.0", "100.64.0.1", "198.18.0.1"):
            self.assertFalse(text._ip_is_public(ip), ip)

    def test_ipv6_special_rejected(self):
        for ip in ("::1", "fe80::1", "fc00::1", "fd12:3456::1", "::"):
            self.assertFalse(text._ip_is_public(ip), ip)

    def test_ipv4_mapped_private_rejected(self):
        self.assertFalse(text._ip_is_public("::ffff:10.0.0.1"))


class TestSsrfGuard(unittest.TestCase):
    def test_rejects_non_http_scheme(self):
        self.assertFalse(text.is_safe_public_url("ftp://example.com/x"))
        self.assertFalse(text.is_safe_public_url("file:///etc/passwd"))

    def test_rejects_missing_host(self):
        self.assertFalse(text.is_safe_public_url("http:///nohost"))

    def test_rejects_metadata_endpoint(self):
        with mock.patch.object(text.socket, "getaddrinfo", _resolves_to("169.254.169.254")):
            self.assertFalse(text.is_safe_public_url("http://metadata.local/latest"))

    def test_rejects_if_any_resolved_ip_is_private(self):
        with mock.patch.object(text.socket, "getaddrinfo",
                               _resolves_to("93.184.216.34", "10.0.0.1")):
            self.assertFalse(text.is_safe_public_url("http://mixed/x"))

    def test_allows_public_ip(self):
        with mock.patch.object(text.socket, "getaddrinfo", _resolves_to("93.184.216.34")):
            self.assertTrue(text.is_safe_public_url("https://example.com/article"))

    def test_fails_closed_on_resolution_error(self):
        with mock.patch.object(text.socket, "getaddrinfo", side_effect=socket.gaierror):
            self.assertFalse(text.is_safe_public_url("https://nope.invalid/x"))


class _FakeResp:
    status = 200

    def getheader(self, k, d=None):
        return "text/html; charset=utf-8" if k == "Content-Type" else d

    def read(self, n):
        return b"<html>ok</html>"


class TestFetchPinning(unittest.TestCase):
    def test_fulltext_skips_unsafe_url_without_fetching(self):
        with mock.patch.object(text.socket, "getaddrinfo", _resolves_to("127.0.0.1")):
            self.assertEqual(text.fulltext("http://localhost/secret"), "")

    def test_fetch_rejects_private_resolution(self):
        with mock.patch.object(text.socket, "getaddrinfo", _resolves_to("127.0.0.1")):
            self.assertEqual(text._fetch_html("http://localhost/secret"), "")

    def test_fetch_connects_to_validated_ip(self):
        captured = {}

        class _FakeConn:
            def __init__(self, host, ip, **kw):
                captured["host"], captured["ip"] = host, ip

            def request(self, method, path, headers=None):
                captured["path"] = path

            def getresponse(self):
                return _FakeResp()

            def close(self):
                pass

        with mock.patch.object(text, "_resolve_public_ip", return_value="93.184.216.34"), \
             mock.patch.object(text, "_PinnedHTTPSConnection", _FakeConn):
            out = text._fetch_html("https://example.com/article")
        self.assertEqual(captured["ip"], "93.184.216.34")  # pinned to the validated IP
        self.assertEqual(captured["host"], "example.com")   # Host/SNI stays the real name
        self.assertIn("ok", out)

    def test_redirect_to_private_is_blocked(self):
        class _RedirResp:
            status = 302

            def getheader(self, k, d=None):
                return "http://169.254.169.254/latest/meta-data/" if k == "Location" else d

            def read(self, n):
                return b""

        class _FakeConn:
            def __init__(self, host, ip, **kw):
                pass

            def request(self, *a, **k):
                pass

            def getresponse(self):
                return _RedirResp()

            def close(self):
                pass

        def resolve(host, port):
            return "93.184.216.34" if host == "example.com" else ""

        with mock.patch.object(text, "_resolve_public_ip", side_effect=resolve), \
             mock.patch.object(text, "_PinnedHTTPSConnection", _FakeConn), \
             mock.patch.object(text, "_PinnedHTTPConnection", _FakeConn):
            self.assertEqual(text._fetch_html("https://example.com/start"), "")


if __name__ == "__main__":
    unittest.main()
