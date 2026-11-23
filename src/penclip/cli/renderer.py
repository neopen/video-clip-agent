"""CLI renderer — formats hub responses for terminal output."""

from typing import Any

from penclip.core.hub.central_hub import HubResponse

_MAX_VALUE_LENGTH = 72


def render_response(response: HubResponse, print_fn=print):
    status = "OK" if response.success else "FAIL"
    print_fn(f"[{status}] {response.message}")
    if response.intent:
        print_fn(f"  Intent: {response.intent.value}")
    if response.needs_confirmation:
        print_fn(f"  ⚠ {response.confirmation_message}")
    if response.needs_clarification:
        print_fn(f"  ? {response.clarification}")
    for key, value in (response.data or {}).items():
        print_fn(f"  {key}: {_brief(value)}")
    for suggestion in response.suggestions:
        print_fn(f"  建议：{suggestion}")


def _brief(value: Any) -> str:
    """Compact one-line rendering; console users want the summary, not the dump."""
    if isinstance(value, dict):
        return f"{len(value)} 项" + (f"（{', '.join(list(value)[:4])}）" if value else "")
    if isinstance(value, (list, tuple)):
        return f"{len(value)} 条" + (f"（{', '.join(_brief(v) for v in value[:3])}）" if value else "")
    text = getattr(value, "value", value)
    text = str(text)
    return text if len(text) <= _MAX_VALUE_LENGTH else text[:_MAX_VALUE_LENGTH] + "…"
