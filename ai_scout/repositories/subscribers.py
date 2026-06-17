from __future__ import annotations

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
