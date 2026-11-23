"""IntentRecognizer 关键词单元测试 —— 长词优先，避免短词吞掉更具体的意图。"""

import pytest

from penclip.core.hub.intent_recognizer import IntentRecognizer, is_asset_url
from penclip.domain.value_objects.intent import IntentType


@pytest.mark.parametrize(("text", "intent"), [
    ("能做什么", IntentType.STATE_QUERY_CAPABILITIES),
    ("优先分析这段", IntentType.ANALYZE_PRIORITY),
    ("匹配片段", IntentType.EXECUTE),
    ("裁剪这段到10秒", IntentType.CLIP_TRIM),
    ("进度到哪了", IntentType.STATE_QUERY_PROGRESS),
    ("做个旅行Vlog，风景放开头", IntentType.PLAN_CREATE),
    ("合成", IntentType.STATE_RENDER),
    ("撤销", IntentType.STATE_UNDO),
])
def test_recognizer_picks_the_longest_matching_keyword(text, intent):
    assert IntentRecognizer().recognize(text).intent == intent


@pytest.mark.parametrize("text", [
    "https://example.com/a.mp4",
    r"data\test_media\solid_red.mp4",
    "E:/Videos/shot.mov",
])
def test_video_paths_and_urls_are_asset_add(text):
    assert is_asset_url(text) is True
    assert IntentRecognizer().recognize(text).intent == IntentType.ASSET_ADD


def test_plain_prose_is_not_an_asset():
    assert is_asset_url("做个有电影感的旅行Vlog") is False


def test_single_character_input_needs_clarification():
    recognizer = IntentRecognizer()

    assert recognizer.needs_clarification("剪") is True
    assert recognizer.needs_clarification("剪这段") is False
