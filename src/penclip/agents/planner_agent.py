"""Bridge module — re-exports PlannerAgent for backward compatibility.

Existing code imports:
    from penclip.agents.planner_agent import get_planner_agent
"""

from penclip.agents.planner import PlannerAgent, get_planner_agent

__all__ = ["get_planner_agent", "PlannerAgent"]
