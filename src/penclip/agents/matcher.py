"""MatcherAgent — matches timeline slots to video segments via label overlap scoring."""

from typing import Any, Dict, List, Optional

from penclip.agents.base import BaseAgent, ExecutionContext
from penclip.core.state.state_manager import get_state_manager
from penclip.domain.entities.assembly_state import MatchCandidate, MatchResult
from penclip.domain.value_objects.capability import CapabilityDeclaration
from penclip.domain.value_objects.execution_result import ExecutionResult
from penclip.domain.value_objects.intent import IntentType
from penclip.domain.value_objects.risk import RiskLevel
from penclip.logger import info

DEFAULT_CONFIG = {
    "similarity_threshold": 0.3,
    "max_candidates_per_slot": 3,
    "label_weight": 0.7,
    "duration_weight": 0.3,
}

# Descriptive tags emitted by AnalyzerAgent._build_labels.
_TAGS = ("明亮", "昏暗", "中等亮度", "长镜头", "短镜头", "横屏", "竖屏")
_COLOURS = ("红色", "橙色", "黄色", "绿色", "青色", "蓝色")
# Generic words that must not create a fake match against 来源:<name> labels.
_STOPWORDS = (
    "视频", "画面", "片段", "素材", "镜头", "这个", "那个", "一个", "一些",
    "不要", "可以", "需要", "使用", "放在", "开头", "中间", "结尾", "时候",
)


class MatcherAgent(BaseAgent):
    agent_id = "matcher"
    agent_name = "MatcherAgent"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        super().__init__(config=cfg)

    def declare_capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            name="segment_matcher",
            intents=[
                IntentType.CLIP_TRIM, IntentType.CLIP_REPLACE,
                IntentType.CLIP_SWAP, IntentType.CLIP_REMOVE,
                IntentType.CLIP_PREVIEW, IntentType.EXECUTE,
            ],
            description="Label-overlap matching of video segments to timeline slots",
            input_schema={
                "slots": {"type": "list", "description": "Slots to match"},
                "segments": {"type": "list", "description": "Available segments"},
            },
            output_schema={
                "match_results": {"type": "object", "description": "Per-slot match results"},
            },
            risk_level=RiskLevel.MEDIUM,
            version=self.version,
            agent_id=self.agent_id,
        )

    def execute(self, params: Dict[str, Any], context: ExecutionContext) -> ExecutionResult:
        state_manager = get_state_manager()
        state = state_manager.get_session(self._extract_session_id(context) or "")

        slots = params.get("slots") or [
            {"slot_id": s.slot_id, "semantic_query": s.semantic_query,
             "min_duration": s.min_duration, "max_duration": s.max_duration,
             "source_constraint": s.source_constraint}
            for s in (state.slots if state else [])
        ]
        segments = params.get("segments") or self._collect_segments(state)

        if not slots:
            return ExecutionResult(
                success=False, message="没有待匹配的槽位，请先创建时间线", status="failed",
            )
        if not segments:
            return ExecutionResult(
                success=False, message="没有可匹配的片段，请先分析素材", status="failed",
            )

        results: Dict[str, MatchResult] = {}
        for slot_data in slots:
            matches = self._apply_constraints(
                self._semantic_search(slot_data.get("semantic_query", ""), segments, slot_data),
                slot_data, segments,
            )
            ranked = self._rank_by_similarity(matches)
            results[slot_data.get("slot_id", "")] = MatchResult(
                slot_id=slot_data.get("slot_id", ""),
                candidates=ranked[: int(self._config["max_candidates_per_slot"])],
            )

        matched = sum(1 for r in results.values() if r.candidates)
        if matched == 0:
            return ExecutionResult(
                success=False,
                message="没有任何槽位匹配到候选片段，请补充素材或调整描述",
                status="failed",
            )

        if state is not None:
            state.match_results = results
            state.current_phase = "matched"
            state_manager.update_session(state)

        info(f"MatcherAgent: {matched}/{len(results)} slot(s) matched")
        return ExecutionResult(
            success=True,
            data={"match_results": {k: v.model_dump() for k, v in results.items()}},
            message=f"已匹配 {matched}/{len(results)} 个槽位",
        )

    @staticmethod
    def _collect_segments(state: Any) -> List[Dict[str, Any]]:
        if state is None:
            return []
        segments: List[Dict[str, Any]] = []
        for analysis in state.analysis_results.values():
            segments.extend(s.model_dump() for s in analysis.segments)
        return segments

    def _semantic_search(self, query: str, segments: List[Dict], slot: Dict) -> List[MatchCandidate]:
        """Score every segment against one slot query (V0.1: labels, not vectors)."""
        candidates: List[MatchCandidate] = []
        threshold = float(self._config["similarity_threshold"])
        for segment in segments:
            labels = list(segment.get("labels") or [])
            duration = float(segment.get("end_time", 0.0)) - float(segment.get("start_time", 0.0))
            label_score = self._label_score(query, labels)
            duration_score = self._duration_score(duration, slot)
            overall = round(
                self._config["label_weight"] * label_score
                + self._config["duration_weight"] * duration_score,
                4,
            )
            if overall <= 0 or (label_score > 0 and overall < threshold):
                continue
            candidates.append(MatchCandidate(
                segment_id=segment.get("segment_id", ""),
                similarity_score=round(label_score, 4),
                duration_match_score=round(duration_score, 4),
                overall_score=overall,
                score_breakdown={
                    "label": round(label_score, 4),
                    "duration": round(duration_score, 4),
                },
            ))
        return candidates

    @staticmethod
    def _label_score(query: str, labels: List[str]) -> float:
        score = 0.0
        for label in labels:
            if label.startswith("来源:"):
                stem = label.split(":", 1)[1]
                if stem and stem in query.replace("\\", "/").replace("/", " "):
                    score += 1.0
            elif any(f"色调:{c}" == label for c in _COLOURS):
                colour = label.split(":", 1)[1]
                if colour and colour[:2] in query:
                    score += 1.0
            elif any(t in label for t in _TAGS) and label in query:
                score += 0.5

        if score > 0:
            return min(1.0, score)

        return MatcherAgent._token_overlap(query, labels)

    @staticmethod
    def _token_overlap(query: str, labels: List[str]) -> float:
        """Weak fallback: meaningful 2-gram overlap when no structured tag hits."""
        grams = {
            query[i:i + 2]
            for i in range(len(query) - 1)
            if not query[i:i + 2].isspace() and query[i:i + 2] not in _STOPWORDS
        }
        if not grams:
            return 0.0
        label_text = " ".join(labels)
        hits = sum(1 for g in grams if g in label_text)
        return min(0.4, 0.4 * hits / len(grams)) if hits else 0.0

    @staticmethod
    def _duration_score(duration: float, slot: Dict) -> float:
        """1.0 inside [min, max]; graded outside so slots can still be filled."""
        low = float(slot.get("min_duration") or 0.0)
        high = float(slot.get("max_duration") or 0.0) or low
        if duration <= 0:
            return 0.0
        if low <= duration <= high:
            return 1.0
        span = max((low + high) / 2.0, 1.0)
        overshoot = (duration - high) if duration > high else (low - duration)
        return max(0.0, 1.0 - overshoot / span)

    def _apply_constraints(self, candidates: List[MatchCandidate], constraints: Dict,
                           segments: List[Dict]) -> List[MatchCandidate]:
        """Honour Slot.source_constraint by restricting to that asset's segments."""
        source = constraints.get("source_constraint")
        if not source:
            return candidates
        labels = {s.get("segment_id", ""): list(s.get("labels") or []) for s in segments}
        kept = [
            c for c in candidates
            if any(lbl.startswith("来源:") and source in lbl.split(":", 1)[1]
                   for lbl in labels.get(c.segment_id, []))
        ]
        return kept or candidates

    def _rank_by_similarity(self, candidates: List[MatchCandidate]) -> List[MatchCandidate]:
        return sorted(candidates, key=lambda c: c.overall_score, reverse=True)

    @staticmethod
    def _extract_session_id(context: Any) -> Optional[str]:
        if isinstance(context, dict):
            return context.get("session_id")
        if isinstance(context, ExecutionContext):
            return context.session_id
        return None
