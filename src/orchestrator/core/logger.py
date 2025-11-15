"""JSONL logging for full system traceability."""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from ..models import LogEvent, EventType


class EventLogger:
    def __init__(self, log_path: Path = Path(".orchestrator/full_history.jsonl")):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.log_path.exists():
            self.log_path.touch()

    def log(
        self,
        event_type: EventType,
        actor: str,
        payload: Dict[str, Any],
        trace_id: str,
        parent_trace_id: Optional[str] = None,
        step: Optional[int] = None,
        version: Optional[str] = None
    ) -> None:
        """Append event to JSONL log."""
        event = LogEvent(
            timestamp=datetime.now(timezone.utc),
            step=step or 0,
            actor=actor,
            event=event_type,
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            payload=payload,
            version=version
        )

        with open(self.log_path, "a") as f:
            f.write(event.model_dump_json() + "\n")

    def query(self, **filters) -> List[LogEvent]:
        """Query events by filters."""
        events = []

        with open(self.log_path, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                event_dict = json.loads(line)

                match = all(
                    event_dict.get(key) == value
                    for key, value in filters.items()
                )

                if match:
                    events.append(LogEvent(**event_dict))

        return events
