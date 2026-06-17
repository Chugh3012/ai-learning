import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "function"))

# Stub ONLY azure.functions (not shipped with the package deps); the other azure modules
# (data.tables UpdateMode, core.exceptions) are real and importable.
if "azure.functions" not in sys.modules:
    fmod = types.ModuleType("azure.functions")

    class AuthLevel:
        ANONYMOUS = "anonymous"

    class FunctionApp:
        def route(self, *a, **k):
            def deco(fn):
                return fn
            return deco

    class HttpResponse:
        def __init__(self, body="", status_code=200, mimetype=None, headers=None):
            self.body = body
            self.status_code = status_code
            self.headers = headers or {}

        def get_body(self):
            return self.body.encode() if isinstance(self.body, str) else (self.body or b"")

    class HttpRequest:
        def __init__(self, method="GET", url="https://fn/api/x", params=None,
                     headers=None, body=None):
            self.method = method
            self.url = url
            self.params = params or {}
            self.headers = headers or {}
            self._body = body

        def get_json(self):
            import json
            if self._body is None:
                raise ValueError("no body")
            return json.loads(self._body) if isinstance(self._body, str) else self._body

    fmod.AuthLevel = AuthLevel
    fmod.FunctionApp = FunctionApp
    fmod.HttpResponse = HttpResponse
    fmod.HttpRequest = HttpRequest
    sys.modules["azure.functions"] = fmod

import function_app as fa  # noqa: E402
from azure.core.exceptions import ResourceNotFoundError  # noqa: E402
HttpRequest = sys.modules["azure.functions"].HttpRequest


class FakeTable:
    def __init__(self):
        self.rows = {}

    def create_table_if_not_exists(self, *a, **k):
        pass

    def get_entity(self, partition_key=None, row_key=None):
        r = self.rows.get((partition_key, row_key))
        if r is None:
            raise ResourceNotFoundError("not found")
        return dict(r)

    def upsert_entity(self, entity, mode=None):
        self.rows[(entity["PartitionKey"], entity["RowKey"])] = dict(entity)

    def update_entity(self, entity, mode=None):
        self.rows.setdefault((entity["PartitionKey"], entity["RowKey"]), {}).update(entity)

    def delete_entity(self, partition_key=None, row_key=None):
        self.rows.pop((partition_key, row_key), None)

    def query_entities(self, query, parameters=None):
        params = parameters or {}
        conds = [c.strip() for c in query.split(" and ")]

        def match(row):
            for c in conds:
                field, _, val = c.partition(" eq ")
                field, val = field.strip(), val.strip()
                if val.startswith("@"):
                    val = params.get(val[1:])
                elif val.startswith("'"):
                    val = val.strip("'")
                if str(row.get(field)) != str(val):
                    return False
            return True
        return [dict(r) for r in self.rows.values() if match(r)]


class FakeService:
    def __init__(self):
        self.tables = {}

    def create_table_if_not_exists(self, name):
        self.tables.setdefault(name, FakeTable())

    def get_table_client(self, name):
        return self.tables.setdefault(name, FakeTable())


def _emailhash(email):
    return fa._email_key(email)


class FunctionRouteTest(unittest.TestCase):
    def setUp(self):
        self.svc = FakeService()
        for p in (
            mock.patch.object(fa, "_tables", return_value=self.svc),
            mock.patch.object(fa, "_send_confirmation", return_value=True),
            mock.patch.object(fa, "_send_welcome", return_value=True),
        ):
            self.mock = p.start()
            self.addCleanup(p.stop)
        self.send_conf = fa._send_confirmation
        self.send_welcome = fa._send_welcome

    def sub_table(self):
        return self.svc.tables.get("subscribers", FakeTable())


class TestSubscribe(FunctionRouteTest):
    def test_honeypot_returns_success_without_storing_or_sending(self):
        req = HttpRequest(method="POST", body={"email": "a@b.com", "company": "bot"})
        r = fa.subscribe(req)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.sub_table().rows), 0)
        fa._send_confirmation.assert_not_called()

    def test_invalid_email_rejected(self):
        r = fa.subscribe(HttpRequest(method="POST", body={"email": "not-an-email"}))
        self.assertEqual(r.status_code, 400)
        fa._send_confirmation.assert_not_called()

    def test_valid_subscribe_creates_pending_and_sends(self):
        r = fa.subscribe(HttpRequest(method="POST", body={"email": "new@user.com", "name": "N"}))
        self.assertEqual(r.status_code, 200)
        key = _emailhash("new@user.com")
        self.assertIn(("pending", key), self.sub_table().rows)
        fa._send_confirmation.assert_called_once()

    def test_rate_limited_blocks_send(self):
        with mock.patch.object(fa, "_rate_ok", return_value=False):
            r = fa.subscribe(HttpRequest(method="POST", body={"email": "x@y.com"}))
        self.assertEqual(r.status_code, 429)
        fa._send_confirmation.assert_not_called()


class TestConfirm(FunctionRouteTest):
    def _seed_pending(self, email, token, created):
        key = _emailhash(email)
        self.svc.get_table_client("subscribers").upsert_entity({
            "PartitionKey": "pending", "RowKey": key, "email": email, "name": "",
            "token": token, "userId": "usr_test", "kind": "subscriber",
            "createdTs": created, "status": "pending",
        })
        return key

    def test_confirm_activates_and_removes_pending(self):
        key = self._seed_pending("c@u.com", "tok123", int(time.time()))
        r = fa.confirm(HttpRequest(method="GET", url="https://fn/api/confirm", params={"t": "tok123"}))
        self.assertEqual(r.status_code, 200)
        rows = self.sub_table().rows
        self.assertEqual(str(rows[("sub", key)]["status"]), "active")
        self.assertNotIn(("pending", key), rows)
        fa._send_welcome.assert_called_once()

    def test_expired_confirm_link_deletes_and_rejects(self):
        key = self._seed_pending("old@u.com", "tokOld", int(time.time()) - fa._CONFIRM_TTL - 10)
        r = fa.confirm(HttpRequest(method="GET", url="https://fn/api/confirm", params={"t": "tokOld"}))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"expired", r.get_body().lower())
        self.assertNotIn(("pending", key), self.sub_table().rows)
        fa._send_welcome.assert_not_called()


class TestUnsubscribe(FunctionRouteTest):
    def _seed_active(self, email, token):
        key = _emailhash(email)
        self.svc.get_table_client("subscribers").upsert_entity({
            "PartitionKey": "sub", "RowKey": key, "email": email, "token": token,
            "userId": "usr_u", "kind": "subscriber", "status": "active",
        })
        return key

    def test_unsubscribe_get_flips_status(self):
        key = self._seed_active("u@u.com", "utok")
        r = fa.unsubscribe(HttpRequest(method="GET", params={"t": "utok"}))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(str(self.sub_table().rows[("sub", key)]["status"]), "unsubscribed")

    def test_unsubscribe_post_oneclick_returns_200(self):
        self._seed_active("p@u.com", "ptok")
        r = fa.unsubscribe(HttpRequest(method="POST", params={"t": "ptok"}))
        self.assertEqual(r.status_code, 200)

    def test_unsubscribe_missing_token(self):
        r = fa.unsubscribe(HttpRequest(method="GET", params={}))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"missing", r.get_body().lower())


class TestFeedbackExpiry(FunctionRouteTest):
    def test_expired_feedback_token_returns_410(self):
        self.svc.get_table_client("feedbacktokens").upsert_entity({
            "PartitionKey": "tok", "RowKey": "ftok", "action": "up", "itemId": 1,
            "lens": "usr_x:prf", "ts": 0, "expiresTs": int(time.time()) - 5,
        })
        r = fa.feedback(HttpRequest(method="GET", params={"t": "ftok"}))
        self.assertEqual(r.status_code, 410)

    def test_valid_feedback_token_records_event(self):
        self.svc.get_table_client("feedbacktokens").upsert_entity({
            "PartitionKey": "tok", "RowKey": "ok", "action": "up", "itemId": 7,
            "lens": "usr_x:prf", "ts": int(time.time()), "expiresTs": int(time.time()) + 99,
        })
        r = fa.feedback(HttpRequest(method="GET", params={"t": "ok"}))
        self.assertEqual(r.status_code, 200)
        self.assertIn(("7", "usr_x:prf:vote"), self.svc.tables["feedbackevents"].rows)


if __name__ == "__main__":
    unittest.main()
