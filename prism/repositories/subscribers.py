from __future__ import annotations

import secrets

_PENDING_TTL = 7 * 24 * 3600  # un-confirmed signups are dropped after a week

class SubscriberStore:

    def __init__(self, account: str):
        self._account = account or ""
        self._svc = None

    @property
    def enabled(self) -> bool:
        return bool(self._account)

    def _service(self):
        if self._svc is None:
            from azure.data.tables import TableServiceClient
            from azure.identity import DefaultAzureCredential
            self._svc = TableServiceClient(
                endpoint=f"https://{self._account}.table.core.windows.net",
                credential=DefaultAzureCredential(),
            )
        return self._svc

    def _profiles_for(self, user_id: str) -> list[dict] | None:
        if not user_id:
            return None
        try:
            rows = self._service().get_table_client("profiles").query_entities(
                "PartitionKey eq @uid", parameters={"uid": user_id})
            profs = [{
                "id": str(r["RowKey"]),
                "name": str(r.get("name", "")),
                "channel": str(r.get("channel", "email")),
                "cadence": str(r.get("cadence", "daily")),
                "top": int(r.get("top", 5)),
                "min_score": float(r.get("min_score", 0)),
                "interest": str(r.get("interest", "")),
                "self_review": bool(r.get("self_review", False)),
                "topic_id": str(r.get("topic_id", "ai")),
            } for r in rows]
            return profs or None
        except Exception:
            return None

    def confirmed(self) -> list[dict]:
        if not self.enabled:
            return []
        try:
            users = self._service().get_table_client("subscribers").query_entities(
                "PartitionKey eq 'sub' and status eq 'active'")
            out: list[dict] = []
            for u in users:
                uid = str(u.get("userId", ""))
                email = str(u.get("email", ""))
                profiles = self._profiles_for(uid)
                if not (email or profiles):
                    continue
                out.append({
                    "user_id": uid,
                    "email": email,
                    "name": str(u.get("name", "")),
                    "kind": str(u.get("kind") or "subscriber"),
                    "token": str(u.get("token", "")),
                    "profiles": profiles,
                })
            return out
        except Exception as e:
            print(f"subscribers: read failed ({e})")
            return []

    def _mint(self, prefix: str) -> str:
        # The registry OWNS identity. Same opaque format the Function uses for people
        # ("usr_"/"prf_" + 8 hex); resolution is always by kind + topic, never by a readable id.
        return prefix + secrets.token_hex(4)

    def provision_feed(self, kind: str, topic_id: str, interest: str, *, channel: str = "digest",
                       cadence: str = "daily", top: int = 6, name: str = "") -> tuple[str, str]:
        # Create/update an automation feed (a reel or builder lens) that the registry OWNS: one
        # user per kind, one profile per topic under it. Idempotent by (kind, topic_id, channel).
        # Consumers never call this and never see an id format — they only READ lenses.
        from azure.data.tables import UpdateMode
        subs = self._service().get_table_client("subscribers")
        profs = self._service().get_table_client("profiles")
        user = next((u for u in subs.query_entities(
            "PartitionKey eq 'sub' and kind eq @k", parameters={"k": kind})), None)
        uid = str(user["userId"]) if user else self._mint("usr_")
        if not user:
            subs.upsert_entity({
                "PartitionKey": "sub", "RowKey": uid, "userId": uid, "kind": kind,
                "status": "active", "name": name or f"{kind} feed", "email": "", "token": "",
            }, mode=UpdateMode.REPLACE)
        existing = next((p for p in profs.query_entities("PartitionKey eq @u", parameters={"u": uid})
                         if str(p.get("topic_id")) == topic_id and str(p.get("channel")) == channel),
                        None)
        pid = str(existing["RowKey"]) if existing else self._mint("prf_")
        profs.upsert_entity({
            "PartitionKey": uid, "RowKey": pid, "name": name or f"{kind} {topic_id}",
            "channel": channel, "cadence": cadence, "top": int(top), "min_score": 0.0,
            "interest": interest, "self_review": False, "topic_id": topic_id,
        }, mode=UpdateMode.REPLACE)
        return uid, pid

    def list_feeds(self, kind: str = "") -> list[dict]:
        subs = self._service().get_table_client("subscribers")
        profs = self._service().get_table_client("profiles")
        out: list[dict] = []
        for u in subs.query_entities("PartitionKey eq 'sub'"):
            k = str(u.get("kind") or "")
            if k in ("", "subscriber") or (kind and k != kind):
                continue
            uid = str(u.get("userId", ""))
            for p in profs.query_entities("PartitionKey eq @u", parameters={"u": uid}):
                out.append({"kind": k, "user_id": uid, "profile_id": str(p["RowKey"]),
                            "topic_id": str(p.get("topic_id", "")), "channel": str(p.get("channel", "")),
                            "cadence": str(p.get("cadence", "")), "interest": str(p.get("interest", ""))})
        return out

    def remove_feed(self, kind: str, topic_id: str) -> int:
        subs = self._service().get_table_client("subscribers")
        profs = self._service().get_table_client("profiles")
        removed = 0
        for u in subs.query_entities("PartitionKey eq 'sub' and kind eq @k", parameters={"k": kind}):
            uid = str(u.get("userId", ""))
            for p in list(profs.query_entities("PartitionKey eq @u", parameters={"u": uid})):
                if str(p.get("topic_id")) == topic_id:
                    profs.delete_entity(uid, str(p["RowKey"]))
                    removed += 1
        return removed

    def purge_stale_pending(self) -> int:
        # Drop un-confirmed signups whose confirmation window has lapsed. Best-effort.
        if not self.enabled:
            return 0
        try:
            import time
            table = self._service().get_table_client("subscribers")
            cutoff = int(time.time()) - _PENDING_TTL
            removed = 0
            for e in table.query_entities(
                    "PartitionKey eq 'pending' and createdTs lt @cut",
                    parameters={"cut": cutoff}):
                try:
                    table.delete_entity("pending", str(e["RowKey"]))
                    removed += 1
                except Exception:
                    continue
            return removed
        except Exception as e:
            print(f"cleanup: pending purge skipped ({e})")
            return 0
