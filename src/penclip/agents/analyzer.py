"""AnalyzerAgent — performs scene detection and semantic annotation on video assets."""

from typing import Any, Dict, List, Optional

from penclip.agents.base import BaseAgent, ExecutionContext
from penclip.core.state.state_manager import get_state_manager
from penclip.domain.entities.assembly_state import AnalysisResult
from penclip.domain.entities.segment import Segment
from penclip.domain.entities.video_asset import AssetStatus
from penclip.domain.value_objects.capability import CapabilityDeclaration
from penclip.domain.value_objects.execution_result import ExecutionResult
from penclip.domain.value_objects.intent import IntentType
from penclip.domain.value_objects.risk import RiskLevel
from penclip.logger import info, warning

DEFAULT_CONFIG = {
    "min_segment_duration": 2.0,
    "max_segments_per_video": 100,
    "scene_threshold": None,
    "frame_interval": 1.0,
}


class AnalyzerAgent(BaseAgent):
    agent_id = "analyzer"
    agent_name = "AnalyzerAgent"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        super().__init__(config=cfg)

    def declare_capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            name="video_analyzer",
            intents=[
                IntentType.ANALYZE_FULL, IntentType.ANALYZE_INCREMENTAL,
                IntentType.ANALYZE_PRIORITY, IntentType.ANALYZE_CANCEL,
            ],
            description="Scene detection and semantic annotation of video assets",
            input_schema={
                "asset_ids": {"type": "list", "description": "List of asset IDs to analyze"},
            },
            output_schema={
                "analysis_results": {"type": "object", "description": "Per-asset analysis results"},
            },
            risk_level=RiskLevel.MEDIUM,
            version=self.version,
            agent_id=self.agent_id,
        )

    def execute(self, params: Dict[str, Any], context: ExecutionContext) -> ExecutionResult:
        from penclip.services.file_service import FileService
        from penclip.services.scene_detect_service import SceneDetectService

        state_manager = get_state_manager()
        state = state_manager.get_session(self._extract_session_id(context) or "")
        if state is None:
            return ExecutionResult(
                success=False,
                message="没有可分析的会话，请先添加素材",
                status="failed",
            )

        asset_ids = params.get("asset_ids") or [a.asset_id for a in state.assets]

        detector = SceneDetectService({
            "min_segment_duration": self._config["min_segment_duration"],
            "scene_threshold": self._config["scene_threshold"],
            "frame_interval": self._config["frame_interval"],
        })
        files = FileService()

        results: Dict[str, Any] = {}
        analyzed = skipped = 0
        for asset_id in asset_ids:
            asset = state.get_asset(asset_id)
            if asset is None:
                warning(f"AnalyzerAgent: unknown asset {asset_id}")
                skipped += 1
                continue

            video_path = files.resolve_video(asset.file_path)
            if video_path is None:
                warning(f"AnalyzerAgent: asset '{asset.filename}' is not a readable local video")
                asset.status = AssetStatus.ERROR
                skipped += 1
                continue

            self._fill_metadata(asset, video_path)
            scenes = detector.segment_video(video_path)
            if not scenes:
                warning(f"AnalyzerAgent: no scene detected in {video_path}")
                asset.status = AssetStatus.ERROR
                skipped += 1
                continue

            capped = [s for s in scenes if s["duration"] > 0][: int(self._config["max_segments_per_video"])]
            segments = self._annotate_segments(capped, asset)
            state.analysis_results[asset.asset_id] = AnalysisResult(
                asset_id=asset.asset_id,
                segments=segments,
                analysis_duration=sum(s.duration for s in segments),
                status="completed",
            )
            asset.status = AssetStatus.ANALYZED
            results[asset.asset_id] = [s.model_dump() for s in segments]
            analyzed += 1

        if analyzed == 0:
            return ExecutionResult(
                success=False,
                message=f"分析失败：{skipped} 个素材均无法处理（素材需为可读取的本地视频文件）",
                status="failed",
            )

        state.current_phase = "analyzed"
        state_manager.update_session(state)
        total_segments = sum(len(v) for v in results.values())
        info(f"AnalyzerAgent: analyzed {analyzed} asset(s), {total_segments} segment(s), skipped {skipped}")
        return ExecutionResult(
            success=True,
            data={"analysis_results": results},
            message=f"已分析 {analyzed} 个素材，共 {total_segments} 个片段",
        )

    @staticmethod
    def _fill_metadata(asset: Any, video_path: str) -> None:
        """Backfill duration/size, which AssetAgent records without probing."""
        if asset.duration and asset.width and asset.height:
            return
        from penclip.services.ffmpeg_service import FFmpegService

        meta = FFmpegService().get_metadata(video_path)
        asset.duration = asset.duration or float(meta.get("duration") or 0.0)
        asset.width = asset.width or int(meta.get("width") or 0)
        asset.height = asset.height or int(meta.get("height") or 0)

    def _annotate_segments(self, scenes: List[Dict[str, Any]], asset: Any) -> List[Segment]:
        """Attach broad V0.1 labels — semantic CLIP tags arrive in V0.2."""
        return [
            Segment(
                asset_id=asset.asset_id,
                start_time=float(scene["start_time"]),
                end_time=float(scene["end_time"]),
                labels=self._build_labels(asset, scene.get("descriptor") or {}, scene["duration"]),
            )
            for scene in scenes
        ]

    @staticmethod
    def _build_labels(asset: Any, descriptor: Dict[str, Any], duration: float) -> List[str]:
        labels: List[str] = []
        stem = (asset.filename or "").rsplit(".", 1)[0].strip()
        if stem:
            labels.append(f"来源:{stem}")

        hue = descriptor.get("hue")
        if hue is not None:
            labels.append(f"色调:{AnalyzerAgent._hue_name(float(hue))}")

        brightness = float(descriptor.get("brightness") or 0.0)
        if brightness >= 170:
            labels.append("明亮")
        elif brightness > 0 and brightness <= 60:
            labels.append("昏暗")
        elif brightness > 0:
            labels.append("中等亮度")

        if duration >= 10:
            labels.append("长镜头")
        elif duration <= 3:
            labels.append("短镜头")

        if asset.width and asset.height:
            labels.append("竖屏" if asset.height > asset.width else "横屏")
        return labels

    @staticmethod
    def _hue_name(hue: float) -> str:
        """Map an OpenCV hue (0-180, degrees/2) to a broad colour name.

        Band edges sit at midpoints of measured pure colours: red=0, orange=19,
        yellow=30, green=60, cyan=90, blue=120, magenta=150.
        """
        if hue < 7 or hue >= 170:
            return "红色"
        if hue < 22:
            return "橙色"
        if hue < 45:
            return "黄色"
        if hue < 75:
            return "绿色"
        if hue < 105:
            return "青色"
        return "蓝色"

    @staticmethod
    def _extract_session_id(context: Any) -> Optional[str]:
        if isinstance(context, dict):
            return context.get("session_id")
        if isinstance(context, ExecutionContext):
            return context.session_id
        return None
