from __future__ import annotations

from datetime import datetime, timezone

class Metrics:
    def __init__(self, endpoint: str = "", rule_id: str = "", stream: str = ""):
        self.endpoint = endpoint
        self.rule_id = rule_id
        self.stream = stream
        self.run = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.rows: list[dict] = []

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint and self.rule_id and self.stream)

    def add(self, metric: str, value: float, lens: str = "", channel: str = "") -> None:
        self.rows.append({
            "TimeGenerated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Run": self.run,
            "Metric": metric,
            "Value": float(value),
            "Lens": lens,
            "Channel": channel,
        })

    def flush(self) -> None:
        if not self.rows:
            return
        summary = ", ".join(
            f"{r['Metric']}={r['Value']:g}" + (f"[{r['Lens']}]" if r["Lens"] else "")
            for r in self.rows)
        if not self.enabled:
            print(f"metrics (local only, not shipped): {summary}")
            self.rows = []
            return
        try:
            from azure.identity import DefaultAzureCredential
            from azure.monitor.ingestion import LogsIngestionClient
            client = LogsIngestionClient(self.endpoint, credential=DefaultAzureCredential())
            client.upload(rule_id=self.rule_id, stream_name=self.stream, logs=self.rows)
            print(f"metrics: shipped {len(self.rows)} rows to Azure Monitor")
        except Exception as e:
            print(f"metrics: ship failed, kept local ({e}); {summary}")
        self.rows = []
