import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.services import ingest

class _FakeFeed:
    def __init__(self, entries, status=None, bozo=0):
        self.entries = entries
        self.bozo = bozo
        if status is not None:
            self.status = status

def _parser(sequence):
    calls = {"n": 0}

    def parse(url, agent=None):
        feed = sequence[min(calls["n"], len(sequence) - 1)]
        calls["n"] += 1
        return feed
    parse.calls = calls
    return parse

class TestFetchRetry(unittest.TestCase):
    def _run(self, seq, attempts=3):
        p = _parser(seq)
        with mock.patch.dict(sys.modules, {"feedparser": mock.Mock(parse=p)}), \
             mock.patch.object(ingest.time, "sleep"):
            feed = ingest._fetch_feed("u", attempts=attempts)
        return feed, p.calls["n"]

    def test_retries_on_429_then_succeeds(self):
        feed, n = self._run([_FakeFeed([], status=429), _FakeFeed([{"title": "ok"}], status=200)])
        self.assertEqual(n, 2)
        self.assertEqual(len(feed.entries), 1)

    def test_retries_on_502(self):
        feed, n = self._run([_FakeFeed([], status=502), _FakeFeed([], status=503),
                             _FakeFeed([{"t": 1}], status=200)])
        self.assertEqual(n, 3)
        self.assertEqual(len(feed.entries), 1)

    def test_no_retry_on_404(self):
        feed, n = self._run([_FakeFeed([], status=404)])
        self.assertEqual(n, 1)
        self.assertEqual(feed.entries, [])

    def test_retries_on_connection_bozo(self):
        feed, n = self._run([_FakeFeed([], status=None, bozo=1), _FakeFeed([{"t": 1}], status=200)])
        self.assertEqual(n, 2)
        self.assertEqual(len(feed.entries), 1)

    def test_stops_after_attempts_cap(self):
        _feed, n = self._run([_FakeFeed([], status=503)], attempts=3)
        self.assertEqual(n, 3)

if __name__ == "__main__":
    unittest.main()
