"""Persistent lifecycle and ordered events for Agent goals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import GoalNode, RunEvent


GoalStatus = Literal["pending", "running", "completed", "failed", "cancelled"]

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


def serialize_goal(node: GoalNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "run_id": node.run_id,
        "parent_id": node.parent_id,
        "title": node.title,
        "kind": node.kind,
        "status": node.status,
        "agent_profile": node.agent_profile,
        "model_provider": node.model_provider,
        "model_name": node.model_name,
        "tool_call_budget": node.tool_call_budget,
        "tool_repeat_limit": node.tool_repeat_limit,
        "sequence": node.sequence,
        "attempt": node.attempt,
        "max_attempts": node.max_attempts,
        "dependencies": json.loads(node.dependencies_json or "[]"),
        "error_message": node.error_message,
        "started_at": node.started_at.isoformat() if node.started_at else None,
        "completed_at": node.completed_at.isoformat() if node.completed_at else None,
    }


def serialize_event(event: RunEvent) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "run_id": event.run_id,
        "node_id": event.node_id,
        "sequence": event.sequence,
        "type": event.event_type,
        "timestamp": event.created_at.isoformat(),
        "payload": json.loads(event.payload_json or "{}"),
    }


class GoalRuntime:
    """Manage a run's goal state and append-only event sequence."""

    def __init__(self, db: Session, run_id: str) -> None:
        self.db = db
        self.run_id = run_id
        self._sequence = int(
            db.query(func.max(RunEvent.sequence))
            .filter(RunEvent.run_id == run_id)
            .scalar()
            or 0
        )
        self._node_sequence = int(
            db.query(func.max(GoalNode.sequence))
            .filter(GoalNode.run_id == run_id)
            .scalar()
            or 0
        )

    def create_root(
        self,
        *,
        title: str,
        agent_profile: str,
        input_data: dict[str, Any],
        tool_call_budget: int = 0,
        tool_repeat_limit: int = 0,
        model_provider: str = "",
        model_name: str = "",
    ) -> tuple[GoalNode, list[RunEvent]]:
        if tool_repeat_limit < 0:
            raise ValueError("tool_repeat_limit cannot be negative")
        node = GoalNode(
            run_id=self.run_id,
            title=title[:512],
            kind="root",
            status="pending",
            agent_profile=agent_profile,
            tool_call_budget=tool_call_budget,
            tool_repeat_limit=tool_repeat_limit,
            model_provider=model_provider,
            model_name=model_name,
            sequence=0,
            input_json=json.dumps(input_data, ensure_ascii=False),
        )
        self.db.add(node)
        self.db.flush()
        created = self._record("goal_created", node)
        started = self.transition(node, "running", commit=False)
        self.db.commit()
        return node, [created, started]

    def create_child(
        self,
        *,
        parent: GoalNode,
        title: str,
        kind: str,
        agent_profile: str,
        input_data: dict[str, Any],
        dependencies: list[str] | None = None,
        max_attempts: int = 1,
        tool_call_budget: int = 0,
        tool_repeat_limit: int = 0,
        model_provider: str = "",
        model_name: str = "",
    ) -> tuple[GoalNode, list[RunEvent]]:
        if parent.run_id != self.run_id:
            raise ValueError("Parent goal belongs to a different run")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if tool_repeat_limit < 0:
            raise ValueError("tool_repeat_limit cannot be negative")
        self._node_sequence += 1
        node = GoalNode(
            run_id=self.run_id,
            parent_id=parent.id,
            title=title[:512],
            kind=kind,
            status="pending",
            agent_profile=agent_profile,
            tool_call_budget=tool_call_budget,
            tool_repeat_limit=tool_repeat_limit,
            model_provider=model_provider,
            model_name=model_name,
            sequence=self._node_sequence,
            attempt=1,
            max_attempts=max_attempts,
            dependencies_json=json.dumps(dependencies or []),
            input_json=json.dumps(input_data, ensure_ascii=False),
        )
        self.db.add(node)
        self.db.flush()
        created = self._record("goal_created", node)
        started = self.transition(node, "running", commit=False)
        self.db.commit()
        return node, [created, started]

    def transition(
        self,
        node: GoalNode,
        status: GoalStatus,
        *,
        output: dict[str, Any] | None = None,
        error_message: str | None = None,
        commit: bool = True,
    ) -> RunEvent:
        if status not in _ALLOWED_TRANSITIONS.get(node.status, set()):
            raise ValueError(f"Invalid goal transition: {node.status} -> {status}")

        now = datetime.now(timezone.utc)
        node.status = status
        if status == "running":
            node.started_at = now
        if status in {"completed", "failed", "cancelled"}:
            node.completed_at = now
        if output is not None:
            node.output_json = json.dumps(output, ensure_ascii=False)
        node.error_message = error_message
        event = self._record(f"goal_{status}", node)
        if commit:
            self.db.commit()
        return event

    def retry(self, node: GoalNode, error_message: str) -> RunEvent:
        """Record another bounded attempt without leaving the running state."""
        if node.status != "running":
            raise ValueError(f"Cannot retry goal in {node.status} state")
        if node.attempt >= node.max_attempts:
            raise ValueError("Goal retry budget exhausted")

        node.attempt += 1
        node.error_message = error_message
        event = self._record(
            "goal_retrying",
            node,
            extra={"previous_error": error_message},
        )
        self.db.commit()
        return event

    def record_runtime_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        node_id: str | None = None,
    ) -> RunEvent:
        """Persist non-lifecycle Agent telemetry in the ordered run event stream."""
        self._sequence += 1
        event = RunEvent(
            run_id=self.run_id,
            node_id=node_id,
            sequence=self._sequence,
            event_type=event_type,
            payload_json=json.dumps(payload, ensure_ascii=False),
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(event)
        self.db.commit()
        return event

    def _record(
        self,
        event_type: str,
        node: GoalNode,
        *,
        extra: dict[str, Any] | None = None,
    ) -> RunEvent:
        self._sequence += 1
        payload = {"goal": serialize_goal(node), **(extra or {})}
        event = RunEvent(
            run_id=self.run_id,
            node_id=node.id,
            sequence=self._sequence,
            event_type=event_type,
            payload_json=json.dumps(payload, ensure_ascii=False),
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(event)
        self.db.flush()
        return event
