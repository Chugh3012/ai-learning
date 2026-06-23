from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from prism.lib.config import SCRATCH_DIR
from prism.repositories.knowledge import KnowledgeBase

QUALITY_FLOOR = 65.0

@dataclass(frozen=True)
class SourceQualityRow:
    source_id: int
    title: str
    url: str
    category: str
    items_total: int
    ranked_total: int
    quality_ranked_total: int
    delivered_total: int
    saves_total: int
    clicks_total: int
    positive_votes_total: int
    skips_total: int

    @classmethod
    def from_dict(cls, row: dict) -> "SourceQualityRow":
        return cls(
            source_id=int(row.get("source_id") or 0),
            title=str(row.get("title") or ""),
            url=str(row.get("url") or ""),
            category=str(row.get("category") or ""),
            items_total=int(row.get("items_total") or 0),
            ranked_total=int(row.get("ranked_total") or 0),
            quality_ranked_total=int(row.get("quality_ranked_total") or 0),
            delivered_total=int(row.get("delivered_total") or 0),
            saves_total=int(row.get("saves_total") or 0),
            clicks_total=int(row.get("clicks_total") or 0),
            positive_votes_total=int(row.get("positive_votes_total") or 0),
            skips_total=int(row.get("skips_total") or 0),
        )

    @property
    def quality_rate(self) -> float:
        return self.quality_ranked_total / self.ranked_total if self.ranked_total else 0.0

    @property
    def delivered_rate(self) -> float:
        return self.delivered_total / self.items_total if self.items_total else 0.0

    @property
    def action_total(self) -> int:
        return self.saves_total + self.clicks_total + self.positive_votes_total

    @property
    def action_rate(self) -> float:
        return self.action_total / self.delivered_total if self.delivered_total else 0.0

    @property
    def skip_rate(self) -> float:
        return self.skips_total / self.delivered_total if self.delivered_total else 0.0

    @property
    def score(self) -> float:
        raw = (
            0.45 * self.quality_rate
            + 0.35 * self.action_rate
            + 0.20 * self.delivered_rate
            - 0.25 * self.skip_rate
        )
        return round(min(1.0, max(0.0, raw)) * 100, 1)

class SourceQualityDashboard:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    def rows(self) -> list[SourceQualityRow]:
        return [SourceQualityRow.from_dict(r)
                for r in self.kb.source_quality(QUALITY_FLOOR)]

    def write(self, path: Path | None = None, limit: int = 20) -> Path:
        path = path or (SCRATCH_DIR / "source-quality.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(self.rows(), limit=limit), encoding="utf-8")
        return path

    @staticmethod
    def render(rows: list[SourceQualityRow], limit: int = 20) -> str:
        rows = sorted(rows, key=lambda r: (-r.score, -r.items_total, r.title.lower()))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            "# Source Quality Dashboard",
            "",
            f"Generated: {now}",
            f"Quality threshold: relevance >= {QUALITY_FLOOR:g}",
            "",
            "| Source | Category | Items | Ranked | Quality % | Delivered | Actions | Skip % | Score |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in rows[:limit]:
            lines.append(
                f"| {SourceQualityDashboard._label(row)} | "
                f"{SourceQualityDashboard._safe(row.category or '-')} "
                f"| {row.items_total} | {row.ranked_total} "
                f"| {SourceQualityDashboard._pct(row.quality_rate)} "
                f"| {row.delivered_total} | {row.action_total} "
                f"| {SourceQualityDashboard._pct(row.skip_rate)} | {row.score:g} |"
            )
        if not rows:
            lines.append("| No sources yet | - | 0 | 0 | 0% | 0 | 0 | 0% | 0 |")
        watch = [r for r in rows if r.items_total >= 3 and r.score < 35.0]
        if watch:
            lines.extend([
                "",
                "## Watchlist",
                "",
                "| Source | Why |",
                "|---|---|",
            ])
            for row in watch[:10]:
                lines.append(f"| {SourceQualityDashboard._label(row)} | "
                             f"{SourceQualityDashboard._why(row)} |")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _label(row: SourceQualityRow) -> str:
        title = row.title or row.url or f"source {row.source_id}"
        return SourceQualityDashboard._safe(title)

    @staticmethod
    def _safe(value: str) -> str:
        return value.replace("|", "\\|")

    @staticmethod
    def _pct(value: float) -> str:
        return f"{value * 100:.0f}%"

    @staticmethod
    def _why(row: SourceQualityRow) -> str:
        if row.ranked_total and row.quality_rate < 0.25:
            return "Few ranked items clear the quality threshold"
        if row.delivered_total and row.action_rate == 0:
            return "Delivered items have no positive actions yet"
        if row.delivered_total and row.skip_rate >= 0.5:
            return "Delivered items are often skipped"
        return "Low combined quality and engagement score"
