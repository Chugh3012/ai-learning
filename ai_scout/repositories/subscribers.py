from __future__ import annotations

import json

class SubscriberStore:

    def __init__(self, account: str):
        self._account = account or ""
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self._account)

    def _table(self):
        if self._client is None:
            from azure.data.tables import TableServiceClient
            from azure.identity import DefaultAzureCredential
            svc = TableServiceClient(
                endpoint=f"https://{self._account}.table.core.windows.net",
                credential=DefaultAzureCredential(),
            )
            self._client = svc.get_table_client("subscribers")
        return self._client

    def confirmed(self) -> list[dict]:
        if not self.enabled:
            return []
        try:
            rows = self._table().query_entities("PartitionKey eq 'sub' and status eq 'active'")
            out: list[dict] = []
            for r in rows:
                email = str(r.get("email", ""))
                raw = r.get("profiles")
                if not (email or raw):
                    continue
                profiles = None
                if raw:
                    try:
                        profiles = json.loads(raw)
                    except Exception:
                        profiles = None
                out.append({
                    "user_id": str(r.get("userId", "")),
                    "email": email,
                    "name": str(r.get("name", "")),
                    "kind": str(r.get("kind") or "subscriber"),
                    "profiles": profiles,
                })
            return out
        except Exception as e:
            print(f"subscribers: read failed ({e})")
            return []
