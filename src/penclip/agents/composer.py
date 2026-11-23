"""ComposerAgent — renders the final video from matched segments and timeline."""

import os
import subprocess
from typing import Any, Dict, List, Optional

from penclip.agents.base import BaseAgent, ExecutionContext
from penclip.core.state.state_manager import get_state_manager
from penclip.domain.value_objects.capability import CapabilityDeclaration
from penclip.domain.value_objects.execution_result import ExecutionResult
from penclip.domain.value_objects.intent import IntentType
from penclip.domain.value_objects.risk import RiskLevel
from penclip.logger import error, info, warning

DEFAULT_CONFIG = {
    "output_dir": "data/output",
    "clip_dir": "data/output/clips",
    "preview_resolution": "360p",
    "final_resolution": "1080p",
    "bgm_volume": 0.3,
    "max_av_drift": 0.5,
}

# V0.1 composes by plain concat; xfade transitions and filters are V0.2 scope.
_UNSUPPORTED_INTENTS = {
    IntentType.EFFECT_ADD_TRANSITION: "转场",
    IntentType.EFFECT_CHANGE_TRANSITION: "转场",
    IntentType.EFFECT_ADD_FILTER: "滤镜",
    IntentType.EFFECT_REMOVE_FILTER: "滤镜",
    IntentType.AUDIO_ADJUST_VOLUME: "音量调节",
    IntentType.AUDIO_ADJUST_BGM_VOLUME: "背景音乐音量",
}


def _join(directory: str, name: str) -> str:
    r"""规范化输出路径，避免面向用户的信息里出现 data/output\xxx 这种混合分隔符。"""
    return os.path.normpath(os.path.join(directory, name))


class ComposerAgent(BaseAgent):
    agent_id = "composer"
    agent_name = "ComposerAgent"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        super().__init__(config=cfg)

    def declare_capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            name="video_composer",
            intents=[
                IntentType.STATE_RENDER,
                IntentType.EFFECT_ADD_TRANSITION, IntentType.EFFECT_CHANGE_TRANSITION,
                IntentType.EFFECT_ADD_FILTER, IntentType.EFFECT_REMOVE_FILTER,
                IntentType.AUDIO_ADJUST_VOLUME, IntentType.AUDIO_ADD_BGM,
                IntentType.AUDIO_ADJUST_BGM_VOLUME,
            ],
            description="Renders final video with concat and optional background music",
            input_schema={
                "timeline": {"type": "object", "description": "TimelineBlueprint with matched segments"},
            },
            output_schema={
                "output_path": {"type": "string", "description": "Path to rendered video"},
            },
            risk_level=RiskLevel.HIGH,
            version=self.version,
            agent_id=self.agent_id,
        )

    def execute(self, params: Dict[str, Any], context: ExecutionContext) -> ExecutionResult:
        intent = params.get("intent")
        if isinstance(intent, str):
            intent = next((i for i in IntentType if i.value == intent), None)
        if intent in _UNSUPPORTED_INTENTS:
            return ExecutionResult(
                success=False,
                message=f"{_UNSUPPORTED_INTENTS[intent]}效果属于 V0.2 范围，V0.1 仅支持直接拼接与背景音乐",
                status="unsupported",
                suggestions=["先执行「合成」生成成片", "V0.2 将支持转场与滤镜"],
            )

        state_manager = get_state_manager()
        state = state_manager.get_session(self._extract_session_id(context) or "")
        if state is None:
            return ExecutionResult(success=False, message="没有可合成的会话", status="failed")

        from penclip.services.file_service import FileService

        files = FileService()
        plan = self._collect_plan(state)
        if not plan:
            return ExecutionResult(
                success=False,
                message="没有已匹配的片段，请先分析素材并完成匹配",
                status="failed",
            )

        available, missing = [], 0
        for item in plan:
            asset = state.get_asset(item["asset_id"])
            path = files.resolve_video(asset.file_path) if asset else None
            if path is None:
                missing += 1
                continue
            available.append({**item, "video_path": path})
        if missing:
            warning(f"ComposerAgent: {missing} slot(s) point at unreadable assets")
        if not available:
            return ExecutionResult(
                success=False,
                message=f"合成的 {missing} 个片段均无法读取（素材需为本地视频文件）",
                status="failed",
            )

        clip_paths = self._extract_clips(available)
        if not clip_paths:
            return ExecutionResult(success=False, message="片段裁剪全部失败，无法合成", status="failed")

        output_path = self._render_video(clip_paths)
        if not output_path:
            return ExecutionResult(success=False, message="ffmpeg 合成失败", status="failed")

        bgm = (state.global_context.bgm_path or "").strip()
        if bgm:
            mixed = self._mix_audio(output_path, bgm)
            if mixed:
                output_path = mixed

        if os.path.getsize(output_path) <= 0:
            return ExecutionResult(
                success=False, message=f"输出文件为空: {output_path}", status="failed",
            )

        drift = self._av_drift(output_path)
        if drift is None:
            return ExecutionResult(
                success=False, message=f"输出文件不可解码: {output_path}", status="failed",
            )
        if drift > self._config["max_av_drift"]:
            return ExecutionResult(
                success=False,
                message=f"音画不同步：视频与音频时长相差 {drift:.2f}s（{output_path}）",
                status="failed",
            )

        state.current_phase = "rendered"
        state_manager.update_session(state)
        size = os.path.getsize(output_path)
        info(f"ComposerAgent: rendered {len(clip_paths)} clip(s) -> {output_path} ({size} bytes)")
        return ExecutionResult(
            success=True,
            data={"output_path": output_path, "clip_count": len(clip_paths), "size_bytes": size},
            message=f"已合成 {len(clip_paths)} 个片段 → {output_path}",
        )

    @staticmethod
    def _av_drift(output_path: str) -> Optional[float]:
        """Return |video − audio| duration in seconds, or None if undecodable."""
        import csv
        import shutil
        import subprocess

        if shutil.which("ffprobe") is None:
            warning("ComposerAgent: ffprobe unavailable, skipping A/V sync check")
            return -1.0
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
             "-of", "csv=p=0", output_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
        )
        if result.returncode != 0:
            return None

        durations: Dict[str, float] = {}
        for row in csv.reader(result.stdout.splitlines()):
            if len(row) < 2 or row[0] not in ("video", "audio"):
                continue
            try:
                durations[row[0]] = float(row[1])
            except ValueError:
                continue

        if "video" not in durations:
            return None
        return abs(durations["video"] - durations.get("audio", durations["video"]))

    @staticmethod
    def _collect_plan(state: Any) -> List[Dict[str, Any]]:
        """Resolve each slot to its best-matched segment, in timeline order."""
        plan: List[Dict[str, Any]] = []
        for slot in sorted(state.slots, key=lambda s: s.position):
            match = state.match_results.get(slot.slot_id)
            best = match.get_best_candidate() if match else None
            if best is None:
                continue
            segment = next(
                (s for a in state.analysis_results.values() for s in a.segments
                 if s.segment_id == best.segment_id),
                None,
            )
            if segment is None:
                continue
            plan.append({
                "slot_id": slot.slot_id,
                "segment_id": segment.segment_id,
                "asset_id": segment.asset_id,
                "start_time": segment.start_time,
                "end_time": segment.end_time,
            })
        return plan

    def _extract_clips(self, plan: List[Dict[str, Any]]) -> List[str]:
        from penclip.services.ffmpeg_service import FFmpegService

        ffmpeg = FFmpegService()
        os.makedirs(self._config["clip_dir"], exist_ok=True)
        clips: List[str] = []
        for index, item in enumerate(plan):
            target = _join(self._config["clip_dir"], f"clip_{index:02d}_{item['segment_id']}.mp4")
            if os.path.exists(target) or ffmpeg.cut_segment(
                item["video_path"], item["start_time"], item["end_time"], target
            ):
                clips.append(target)
            else:
                error(f"ComposerAgent: cut failed for slot {item['slot_id']}")
        return clips

    def _render_video(self, clip_paths: List[str]) -> Optional[str]:
        from penclip.services.ffmpeg_service import FFmpegService

        os.makedirs(self._config["output_dir"], exist_ok=True)
        output_path = _join(self._config["output_dir"], "composed_output.mp4")
        return FFmpegService().concat_clips(clip_paths, output_path)

    def _mix_audio(self, video_path: str, bgm_path: str) -> Optional[str]:
        """Overlay looping BGM under the original audio track (amix, not replace)."""
        from penclip.utils.ffmpeg_env_utils import find_ffmpeg

        if not os.path.isfile(bgm_path):
            warning(f"ComposerAgent: BGM not found, keeping original audio: {bgm_path}")
            return None

        mixed_path = _join(self._config["output_dir"], "composed_bgm.mp4")
        volume = float(self._config["bgm_volume"])
        command = [
            find_ffmpeg(), "-y",
            "-i", video_path,
            "-stream_loop", "-1", "-i", bgm_path,
            "-filter_complex",
            f"[1:a]volume={volume}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            mixed_path,
        ]
        try:
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            error(f"ComposerAgent: BGM mix crashed: {exc}")
            return None

        if result.returncode == 0 and os.path.exists(mixed_path):
            info(f"ComposerAgent: mixed BGM into {mixed_path}")
            return mixed_path
        error(f"ComposerAgent: BGM mix failed: {result.stderr[-400:]}")
        return None

    @staticmethod
    def _extract_session_id(context: Any) -> Optional[str]:
        if isinstance(context, dict):
            return context.get("session_id")
        if isinstance(context, ExecutionContext):
            return context.session_id
        return None
