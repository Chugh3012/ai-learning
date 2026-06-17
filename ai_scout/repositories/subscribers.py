from __future__ import annotations

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

    def confirmed(self) -> list[tuple[str, str]]:
        if not self.enabled:
            return []
        try:
            rows = self._table().query_entities("PartitionKey eq 'sub' and status eq 'active'")
            return [(str(r.get("email", "")), str(r.get("name", ""))) for r in rows
                    if str(r.get("email", ""))]
        except Exception as e:
            print(f"subscribers: read failed ({e})")
            return []
