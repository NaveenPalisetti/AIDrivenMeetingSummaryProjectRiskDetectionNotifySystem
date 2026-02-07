import uuid
import datetime
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any


class PartType(Enum):
    TEXT = "text/plain"
    JSON = "application/json"
    # Semantic part types used by agents/tools
    MEETING_ID = "meeting_id"
    SUMMARY = "summary"
    TASK = "task"
    ACTION_ITEM = "action_item"
    PROGRESS = "progress"
    RESULT = "result"
    RISK = "risk"


@dataclass
class AgentCapability:
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCard:
    agent_id: str
    name: str
    description: str
    version: str
    base_url: str = ""
    capabilities: List[AgentCapability] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "base_url": self.base_url,
            "capabilities": [
                {"name": c.name, "description": c.description, "parameters": c.parameters}
                for c in self.capabilities
            ]
        }


@dataclass
class MessagePart:
    part_id: str
    content_type: PartType
    content: Any

    def to_dict(self) -> Dict[str, Any]:
        return {"part_id": self.part_id, "content_type": self.content_type.value, "content": self.content}
    
    # Compatibility: allow dict-like access via .get("type") and .get("content") used across codebase
    def get(self, key: str, default: Any = None) -> Any:
        if key in ("type", "content_type"):
            return self.content_type
        if key == "content":
            return self.content
        if key == "part_id":
            return self.part_id
        return default
    
    # Compatibility: allow subscription access like part["content"] used elsewhere
    def __getitem__(self, key: str) -> Any:
        val = self.get(key, None)
        # If asking for 'type' return the enum value or its raw value to preserve older checks
        if key == "type":
            return val
        return val


@dataclass
class A2AMessage:
    message_id: str
    role: str
    parts: List[MessagePart] = field(default_factory=list)

    def __post_init__(self):
        # Normalize parts: allow callers to pass dicts like {"type": PartType.X, "content": ...}
        normalized: List[MessagePart] = []
        for p in list(self.parts or []):
            if isinstance(p, MessagePart):
                normalized.append(p)
                continue
            # dict-like part accepted
            if isinstance(p, dict):
                pid = p.get("part_id") or str(uuid.uuid4())
                # content type may be provided under 'content_type' or 'type'
                ctype = p.get("content_type") if "content_type" in p else p.get("type")
                # If ctype is already a PartType enum, keep it; if it's a string, try to convert
                if isinstance(ctype, PartType):
                    content_type = ctype
                else:
                    try:
                        content_type = PartType(ctype)
                    except Exception:
                        # Fallback: if ctype is None or unknown, default to TEXT
                        content_type = PartType.TEXT
                content = p.get("content")
                normalized.append(MessagePart(pid, content_type, content))
                continue
            # Any other type: coerce to text part
            pid = str(uuid.uuid4())
            normalized.append(MessagePart(pid, PartType.TEXT, str(p)))

        self.parts = normalized

    def add_text_part(self, text: str) -> str:
        pid = str(uuid.uuid4())
        self.parts.append(MessagePart(pid, PartType.TEXT, text))
        return pid

    def add_json_part(self, data: Dict[str, Any]) -> str:
        pid = str(uuid.uuid4())
        self.parts.append(MessagePart(pid, PartType.JSON, data))
        return pid

    def to_dict(self) -> Dict[str, Any]:
        return {"message_id": self.message_id, "role": self.role, "parts": [p.to_dict() for p in self.parts]}


class TaskState(Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class A2ATask:
    task_id: str
    state: TaskState
    messages: List[A2AMessage] = field(default_factory=list)

    def add_message(self, message: A2AMessage) -> None:
        self.messages.append(message)
