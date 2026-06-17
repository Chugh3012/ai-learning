from __future__ import annotations

import secrets
import time

_ACTIONS = ("up", "down", "save", "click")
_ACTION_TO_ROW = {"up": "vote", "down": "vote", "save": "save", "click": "click"}
_TOKEN_TTL = 90 * 24 * 3600  # feedback links are valid for 90 days, then purged

class FeedbackStore:

    def __init__(self, account: str):
        self.account = account

    @property
    def enabled(self) -> bool:
        return bool(self.account)

    def _table(self, name: str):
        from azure.data.tables import TableServiceClient
        from azure.identity import DefaultAzureCredential
        return TableServiceClient(
            endpoint=f"https://{self.account}.table.core.windows.net",
            credential=DefaultAzureCredential(),
        ).get_table_client(name)

    def mint_tokens(self, lens: str, items: list[tuple]) -> dict[int, dict[str, str]]:
        if not self.enabled:
            return {}
        try:
            from azure.data.tables import UpdateMode
            table = self._table("feedbacktokens")
        except Exception as e:
            print(f"deliver: feedback tokens unavailable ({e}); sending plain links")
            return {}
        out: dict[int, dict[str, str]] = {}
        now = int(time.time())
        expires = now + _TOKEN_TTL
        try:
            for item_id, _title, url in items:
                per: dict[str, str] = {}
                for action in _ACTIONS:
                    tok = secrets.token_urlsafe(16)
                    table.upsert_entity(
                        {"PartitionKey": "tok", "RowKey": tok, "lens": lens,
                         "itemId": int(item_id), "action": action, "url": url,
                         "ts": now, "expiresTs": expires},
                        mode=UpdateMode.REPLACE,
                    )
                    per[action] = tok
                out[item_id] = per
        except Exception as e:
            print(f"deliver: token minting failed ({e}); sending plain links")
            return {}
        return out

    def purge_expired_tokens(self) -> int:
        # Delete feedback tokens past their TTL so the table stays bounded. Tokens minted
        # before expiresTs existed fall back to ts + TTL. Best-effort + graceful.
        if not self.enabled:
            return 0
        try:
            from azure.data.tables import UpdateMode  # noqa: F401
            table = self._table("feedbacktokens")
            cutoff = int(time.time()) - _TOKEN_TTL
            removed = 0
            for e in table.query_entities(
                    "PartitionKey eq 'tok' and ts lt @cut", parameters={"cut": cutoff}):
                try:
                    table.delete_entity("tok", str(e["RowKey"]))
                    removed += 1
                except Exception:
                    continue
            return removed
        except Exception as e:
            print(f"cleanup: token purge skipped ({e})")
            return 0

    def drain_events(self) -> list[tuple[int, str, str, float]]:
        if not self.enabled:
            return []
        table = self._table("feedbackevents")
        out: list[tuple[int, str, str, float]] = []
        for e in table.list_entities():
            try:
                lens = str(e.get("lens", ""))
                row = _ACTION_TO_ROW.get(str(e.get("action", "")))
                if not lens or row is None:
                    continue
                out.append((int(e["PartitionKey"]), lens, row, float(e["value"])))
            except (KeyError, ValueError, TypeError):
                continue
        return out

    def record_votes(self, lens: str, item_ids: list[int], value: float) -> int:
        if not self.enabled or not item_ids or not lens:
            return 0
        action = "up" if value > 0 else "down"
        try:
            from azure.data.tables import UpdateMode
            table = self._table("feedbackevents")
            now = int(time.time())
            for item_id in item_ids:
                table.upsert_entity(
                    {"PartitionKey": str(item_id), "RowKey": f"{lens}:vote", "lens": lens,
                     "value": float(value), "action": action, "ts": now},
                    mode=UpdateMode.REPLACE,
                )
        except Exception as e:
            print(f"votes: write failed ({e})")
            return 0
        return len(item_ids)
