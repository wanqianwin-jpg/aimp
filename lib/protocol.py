"""
protocol.py — AIMP/0.1 协议数据模型与状态管理
"""
from __future__ import annotations
import copy
import time
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────
PROTOCOL_VERSION = "AIMP/0.1"
MAX_ROUNDS = 5

VALID_ACTIONS = {"propose", "accept", "counter", "confirm", "escalate"}


# ──────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────
@dataclass
class HistoryEntry:
    version: int
    from_agent: str
    action: str
    summary: str

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "from": self.from_agent,
            "action": self.action,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HistoryEntry":
        return cls(
            version=d["version"],
            from_agent=d["from"],
            action=d["action"],
            summary=d.get("summary", ""),
        )


@dataclass
class ProposalItem:
    """单个议题（如 time 或 location）的投票状态"""
    options: list[str] = field(default_factory=list)
    votes: dict[str, Optional[str]] = field(default_factory=dict)  # agent_email -> choice | None

    def add_option(self, option: str):
        if option not in self.options:
            self.options.append(option)

    def vote(self, voter: str, choice: str):
        if choice not in self.options:
            raise ValueError(f"选项 '{choice}' 不在 options 中: {self.options}")
        self.votes[voter] = choice

    def clear_vote(self, voter: str):
        self.votes[voter] = None

    def check_consensus(self) -> Optional[str]:
        """若所有参与者都投了同一个选项，返回该选项；否则返回 None"""
        actual_votes = [v for v in self.votes.values() if v is not None]
        if not actual_votes:
            return None
        if len(actual_votes) == len(self.votes) and len(set(actual_votes)) == 1:
            return actual_votes[0]
        return None

    def to_dict(self) -> dict:
        return {
            "options": list(self.options),
            "votes": dict(self.votes),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProposalItem":
        obj = cls(options=list(d.get("options", [])))
        obj.votes = dict(d.get("votes", {}))
        return obj


# ──────────────────────────────────────────────────────
# 主类
# ──────────────────────────────────────────────────────
class AIMPSession:
    def __init__(self, session_id: str, topic: str, participants: list[str],
                 initiator: str = ""):
        self.session_id = session_id
        self.topic = topic
        self.participants: list[str] = list(participants)
        self.initiator = initiator or (participants[0] if participants else "")
        self._version: int = 0
        self.proposals: dict[str, ProposalItem] = {}
        self.history: list[HistoryEntry] = []
        self.status: str = "negotiating"  # negotiating | confirmed | escalated
        self.created_at: float = time.time()

        # 初始化每个参与者的投票槽
        for item_name in ("time", "location"):
            self.proposals[item_name] = ProposalItem(
                options=[],
                votes={p: None for p in self.participants},
            )

    # ── 版本管理 ──────────────────────────────────────

    @property
    def version(self) -> int:
        return self._version

    def next_version(self) -> int:
        return self._version + 1

    def bump_version(self):
        self._version += 1

    # ── 参与者管理 ────────────────────────────────────

    def ensure_participant(self, email: str):
        """确保参与者在所有议题中都有投票槽"""
        if email not in self.participants:
            self.participants.append(email)
        for item in self.proposals.values():
            if email not in item.votes:
                item.votes[email] = None

    # ── 议题操作 ──────────────────────────────────────

    def add_option(self, item: str, option: str):
        """添加新选项（counter 时用）"""
        if item not in self.proposals:
            self.proposals[item] = ProposalItem(
                votes={p: None for p in self.participants}
            )
        self.proposals[item].add_option(option)

    def apply_vote(self, voter: str, item: str, choice: str):
        """记录投票"""
        self.ensure_participant(voter)
        if item not in self.proposals:
            raise KeyError(f"议题 '{item}' 不存在")
        self.proposals[item].vote(voter, choice)

    def apply_votes(self, voter: str, votes: dict[str, Optional[str]]):
        """批量投票，votes = {item: choice | None}"""
        self.ensure_participant(voter)
        for item, choice in votes.items():
            if choice is not None:
                self.apply_vote(voter, item, choice)

    # ── 共识检查 ──────────────────────────────────────

    def check_consensus(self) -> dict[str, Optional[str]]:
        """返回 {item: resolved_value | None}"""
        return {name: item.check_consensus() for name, item in self.proposals.items()}

    def is_fully_resolved(self) -> bool:
        """所有议题是否都已达成共识"""
        consensus = self.check_consensus()
        return all(v is not None for v in consensus.values())

    def round_count(self) -> int:
        """当前协商轮数（history 长度）"""
        return len(self.history)

    def is_stalled(self) -> bool:
        return self.round_count() >= MAX_ROUNDS

    # ── 历史记录 ──────────────────────────────────────

    def add_history(self, from_agent: str, action: str, summary: str):
        entry = HistoryEntry(
            version=self._version,
            from_agent=from_agent,
            action=action,
            summary=summary,
        )
        self.history.append(entry)

    # ── 序列化 ────────────────────────────────────────

    def to_json(self) -> dict:
        return {
            "protocol": PROTOCOL_VERSION,
            "session_id": self.session_id,
            "version": self._version,
            "topic": self.topic,
            "from": self.initiator,
            "participants": list(self.participants),
            "proposals": {name: item.to_dict() for name, item in self.proposals.items()},
            "status": self.status,
            "history": [h.to_dict() for h in self.history],
        }

    @classmethod
    def from_json(cls, data: dict) -> "AIMPSession":
        obj = cls.__new__(cls)
        obj.session_id = data["session_id"]
        obj.topic = data.get("topic", "")
        obj.participants = list(data.get("participants", []))
        obj.initiator = data.get("from", obj.participants[0] if obj.participants else "")
        obj._version = data.get("version", 0)
        obj.status = data.get("status", "negotiating")
        obj.history = [HistoryEntry.from_dict(h) for h in data.get("history", [])]
        obj.created_at = time.time()

        raw_proposals = data.get("proposals", {})
        obj.proposals = {}
        for name, raw in raw_proposals.items():
            obj.proposals[name] = ProposalItem.from_dict(raw)

        # 确保 time/location 议题存在
        for item_name in ("time", "location"):
            if item_name not in obj.proposals:
                obj.proposals[item_name] = ProposalItem(
                    votes={p: None for p in obj.participants}
                )

        return obj

    def clone(self) -> "AIMPSession":
        return AIMPSession.from_json(copy.deepcopy(self.to_json()))

    def __repr__(self):
        return (
            f"AIMPSession(id={self.session_id!r}, topic={self.topic!r}, "
            f"v={self._version}, status={self.status!r})"
        )
