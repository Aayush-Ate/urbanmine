"""Who the rate limiter thinks the caller is.

Behind Vercel (and Cloudflare, once it is in front) the socket peer is the
proxy. Keying the analyze limit on that gives the whole site one shared bucket:
20 photos a minute for everyone instead of 20 per person. These pin the header
order that fixes it, and that two callers actually get separate buckets.

No image is needed: the limit is checked before the body is read, so a
text/plain upload is enough to reach the interesting branch.
"""
import unittest

from fastapi.testclient import TestClient

from app.core.ratelimit import SlidingWindow, client_ip


class _Req:
    """Just enough of a Request for client_ip: headers and a socket peer."""

    def __init__(self, headers=None, host=None):
        self.headers = headers or {}
        self.client = type("Peer", (), {"host": host})() if host else None


class TestClientIp(unittest.TestCase):
    def test_cloudflare_header_wins(self):
        ip = client_ip(_Req({"cf-connecting-ip": "203.0.113.7",
                             "x-forwarded-for": "10.0.0.1, 10.0.0.2"}, "172.16.0.1"))
        self.assertEqual(ip, "203.0.113.7")

    def test_forwarded_for_uses_the_first_hop(self):
        # Vercel appends proxies to the right; the caller is the leftmost entry.
        ip = client_ip(_Req({"x-forwarded-for": "198.51.100.9, 10.0.0.1"}, "172.16.0.1"))
        self.assertEqual(ip, "198.51.100.9")

    def test_socket_peer_is_the_fallback(self):
        self.assertEqual(client_ip(_Req({}, "127.0.0.1")), "127.0.0.1")

    def test_nothing_at_all_does_not_raise(self):
        self.assertEqual(client_ip(_Req({}, None)), "unknown")


class TestAnalyzeLimitPerCaller(unittest.TestCase):
    def setUp(self):
        from app import main
        self.main = main
        self.http = TestClient(main.app)
        self.real_limit = main.ANALYZE_LIMIT
        main.ANALYZE_LIMIT = SlidingWindow(limit=1, window_s=60)

    def tearDown(self):
        self.main.ANALYZE_LIMIT = self.real_limit

    def _post(self, ip):
        return self.http.post(
            "/api/analyze",
            files={"file": ("note.txt", b"not a photo", "text/plain")},
            headers={"cf-connecting-ip": ip},
        )

    def test_two_callers_get_their_own_bucket(self):
        # Before the fix both landed in the proxy's bucket and the second 429'd.
        self.assertEqual(self._post("203.0.113.10").status_code, 200)
        self.assertEqual(self._post("203.0.113.11").status_code, 200)

    def test_the_same_caller_is_still_limited(self):
        self.assertEqual(self._post("203.0.113.12").status_code, 200)
        self.assertEqual(self._post("203.0.113.12").status_code, 429)


if __name__ == "__main__":
    unittest.main()
