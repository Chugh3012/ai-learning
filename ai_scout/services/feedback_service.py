from __future__ import annotations

import time

from ai_scout.lib.config import config_json
from ai_scout.repositories.feedback import FeedbackStore
from ai_scout.repositories.knowledge import KnowledgeBase

_ROW_TO_KIND = {"vote": "fb_vote", "save": "fb_save", "click": "fb_click"}

def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))

class FeedbackService:
    def __init__(self, kb: KnowledgeBase, store: FeedbackStore):
        self.kb = kb
        self.store = store

    def _cfg(self) -> tuple[dict, dict, int]:
        cfg = config_json("feedback.json")
        return cfg.get("weights", {}), cfg.get("influence", {}), int(cfg.get("skip_days", 2))

    def ingest(self, feedback_lenses: set[str]) -> int:
        try:
            events = self.store.drain_events()
        except Exception as e:
            print(f"feedback: events unavailable ({e}); aging skips from local KB only")
            events = []
        now = int(time.time())
        lenses = sorted(feedback_lenses)
        for lens in lenses:
            self.kb.delete_signals([f"fb_vote:{lens}", f"fb_save:{lens}", f"fb_click:{lens}"])
            self.kb.insert_signals(
                [(iid, f"{_ROW_TO_KIND[row]}:{lens}", val, now)
                 for iid, l, row, val in events if l == lens and row in _ROW_TO_KIND])
            self._age_skips(lens, now)
            self.kb.commit()
            self._recompute_affinity(lens, now)
        print(f"feedback: ingested {len(events)} events across {len(lenses)} lens(es)")
        return len(events)

    def _age_skips(self, lens: str, now: int) -> None:
        _, _, skip_days = self._cfg()
        cutoff = now - int(skip_days) * 86400
        self.kb.delete_signals([f"fb_skip:{lens}"])
        ids = self.kb.sent_unactioned(
            lens, cutoff, [f"fb_vote:{lens}", f"fb_save:{lens}", f"fb_click:{lens}"])
        if ids:
            self.kb.insert_signals([(iid, f"fb_skip:{lens}", 1.0, now) for iid in ids])

    def _recompute_affinity(self, lens: str, now: int) -> None:
        weights, influence, _ = self._cfg()
        w_vote = float(weights.get("vote", 1.0))
        w_save = float(weights.get("save", 0.5))
        w_click = float(weights.get("click", 0.25))
        w_skip = float(weights.get("skip", -0.3))
        infl_src = float(influence.get("source", 12))
        infl_topic = float(influence.get("topic", 8))

        raw: dict[int, float] = {}
        kinds = (f"fb_vote:{lens}", f"fb_save:{lens}", f"fb_click:{lens}", f"fb_skip:{lens}")
        for item_id, vote, save, click, skip in self.kb.gesture_scores(kinds):
            raw[item_id] = (w_vote * (vote or 0) + w_save * (save or 0)
                            + w_click * (click or 0) + w_skip * (skip or 0))

        src_sum: dict[int, float] = {}
        src_cnt: dict[int, int] = {}
        for item_id, source_id in (self.kb.items_meta(list(raw)) if raw else []):
            src_sum[source_id] = src_sum.get(source_id, 0.0) + raw[item_id]
            src_cnt[source_id] = src_cnt.get(source_id, 0) + 1
        topic_sum: dict[str, float] = {}
        topic_cnt: dict[str, int] = {}
        for item_id, topic in (self.kb.item_topics(list(raw)) if raw else []):
            topic_sum[topic] = topic_sum.get(topic, 0.0) + raw[item_id]
            topic_cnt[topic] = topic_cnt.get(topic, 0) + 1
        src_aff = {s: _clamp(src_sum[s] / src_cnt[s]) for s in src_sum}
        topic_aff = {t: _clamp(topic_sum[t] / topic_cnt[t]) for t in topic_sum}

        self.kb.delete_signals([f"affinity:{lens}"])
        inserts = []
        for item_id, source_id, topics in self.kb.rank_eligible_with_tags():
            s_aff = src_aff.get(source_id, 0.0)
            topic_list = [t for t in (topics or "").split(",") if t]
            t_aff = (sum(topic_aff.get(t, 0.0) for t in topic_list) / len(topic_list)
                     if topic_list else 0.0)
            points = infl_src * s_aff + infl_topic * t_aff
            if points:
                inserts.append((item_id, f"affinity:{lens}", points, now))
        if inserts:
            self.kb.insert_signals(inserts)
        self.kb.commit()
