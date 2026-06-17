"""kb_sync._fetch_feed — retry on transient HTTP failures only (offline, feedparser mocked)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import kb_sync  # noqa: E402


class _FakeFeed:
    def __init__(self, entries, status=None, bozo=0):
        self.entries = entries
        self.bozo = bozo
        if status is not None:
            self.status = status


def _parser(sequence):
    """Return a fake feedparser.parse that yields the given feeds in order, recording calls."""
    calls = {"n": 0}

    def parse(url, agent=None):
        feed = sequence[min(calls["n"], len(sequence) - 1)]
        calls["n"] += 1
        return feed
    parse.calls = calls
    return parse


class TestFetchRetry(unittest.TestCase):
    def test_retries_on_429_then_succeeds(self):
        seq = [_FakeFeed([], status=429), _FakeFeed([{"title": "ok"}], status=200)]
        p = _parser(seq)
        with mock.patch.dict(sys.modules, {"feedparser": mock.Mock(parse=p)}), \
             mock.patch.object(kb_sync.time, "sleep"):
            feed = kb_sync._fetch_feed("u", "ua", attempts=3)
        self.assertEqual(p.calls["n"], 2)            # retried once
        self.assertEqual(len(feed.entries), 1)       # got the good feed

    def test_retries_on_502(self):
        seq = [_FakeFeed([], status=502), _FakeFeed([], status=503), _FakeFeed([{"t": 1}], status=200)]
        p = _parser(seq)
        with mock.patch.dict(sys.modules, {"feedparser": mock.Mock(parse=p)}), \
             mock.patch.object(kb_sync.time, "sleep"):
            feed = kb_sync._fetch_feed("u", "ua", attempts=3)
        self.assertEqual(p.calls["n"], 3)
        self.assertEqual(len(feed.entries), 1)

    def test_no_retry_on_404(self):
        seq = [_FakeFeed([], status=404)]
        p = _parser(seq)
        with mock.patch.dict(sys.modules, {"feedparser": mock.Mock(parse=p)}), \
             mock.patch.object(kb_sync.time, "sleep"):
            feed = kb_sync._fetch_feed("u", "ua", attempts=3)
        self.assertEqual(p.calls["n"], 1)            # 404 is permanent -> no retry
        self.assertEqual(feed.entries, [])

    def test_retries_on_connection_bozo(self):
        # connection error: feedparser sets bozo with no status
        seq = [_FakeFeed([], status=None, bozo=1), _FakeFeed([{"t": 1}], status=200)]
        p = _parser(seq)
        with mock.patch.dict(sys.modules, {"feedparser": mock.Mock(parse=p)}), \
             mock.patch.object(kb_sync.time, "sleep"):
            feed = kb_sync._fetch_feed("u", "ua", attempts=3)
        self.assertEqual(p.calls["n"], 2)
        self.assertEqual(len(feed.entries), 1)

    def test_stops_after_attempts_cap(self):
        seq = [_FakeFeed([], status=503)]            # always transient-empty
        p = _parser(seq)
        with mock.patch.dict(sys.modules, {"feedparser": mock.Mock(parse=p)}), \
             mock.patch.object(kb_sync.time, "sleep"):
            feed = kb_sync._fetch_feed("u", "ua", attempts=3)
        self.assertEqual(p.calls["n"], 3)            # exactly `attempts` tries, then gives up
        self.assertEqual(feed.entries, [])


if __name__ == "__main__":
    unittest.main()
