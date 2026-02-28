"""
protocol.py — AIMP/0.1 Protocol Data Model and State Management / AIMP/0.1 协议数据模型与状态管理
"""
from __future__ import annotations
import copy
import time
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────────────────
# Constants / 常量
# ──────────────────────────────────────────────────────
PROTOCOL_VERSION = "AIMP/0.1"
MAX_ROUNDS = 5

VALID_ACTIONS = {"propose", "accept", "counter", "confirm", "escalate"}

# Phase 2 Room actions / Phase 2 Room 动作
ROOM_ACTIONS = {"PROPOSE", "AMEND", "ACCEPT", "REJECT"}


# ──────────────────────────────────────────────────────
# Data Structures / 数据结构
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
    """Voting status for a single agenda item (e.g., time or location) / 单个议题（如 time 或 location）的投票状态"""
    options: list[str] = field(default_factory=list)
    votes: dict[str, Optional[str]] = field(default_factory=dict)  # agent_email -> choice | None

    def add_option(self, option: str):
        """Add a new option / 添加新选项"""
        if option not in self.options:
            self.options.append(option)

    def vote(self, voter: str, choice: str):
        """Record a vote / 记录投票"""
        if choice not in self.options:
            raise ValueError(f"Option '{choice}' not in options / 选项 '{choice}' 不在 options 中: {self.options}")
        self.votes[voter] = choice

    def clear_vote(self, voter: str):
        """Clear a vote / 清除投票"""
        self.votes[voter] = None

    def check_consensus(self) -> Optional[str]:
        """
        Return the option if all participants voted for the same one, otherwise return None /
        若所有参与者都投了同一个选项，返回该选项；否则返回 None
        """
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
# Main Class / 主类
# ──────────────────────────────────────────────────────
class AIMPSession:
    def __init__(self, session_id: str, topic: str, participants: list[str],
                 initiator: str = ""):
        """
        Initialize AIMP Session / 初始化 AIMP 会话
        Args:
            session_id: Unique session ID / 唯一会话 ID
            topic: Meeting topic / 会议主题
            participants: List of participant emails / 参与者邮箱列表
            initiator: Initiator's email / 发起者邮箱
        """
        self.session_id = session_id
        self.topic = topic
        self.participants: list[str] = list(participants)
        self.initiator = initiator or (participants[0] if participants else "")
        self._version: int = 0
        self.proposals: dict[str, ProposalItem] = {}
        self.history: list[HistoryEntry] = []
        self.status: str = "negotiating"  # negotiating | confirmed | escalated
        self.created_at: float = time.time()
        self.current_round: int = 1
        self.round_respondents: list[str] = []

        # Initialize voting slots for each participant / 初始化每个参与者的投票槽
        for item_name in ("time", "location"):
            self.proposals[item_name] = ProposalItem(
                options=[],
                votes={p: None for p in self.participants},
            )

    # ── Version Management / 版本管理 ──────────────────────────────────────

    @property
    def version(self) -> int:
        return self._version

    def next_version(self) -> int:
        return self._version + 1

    def bump_version(self):
        self._version += 1

    # ── Participant Management / 参与者管理 ────────────────────────────────────

    def ensure_participant(self, email: str):
        """Ensure participant has a voting slot in all agenda items / 确保参与者在所有议题中都有投票槽"""
        if email not in self.participants:
            self.participants.append(email)
        for item in self.proposals.values():
            if email not in item.votes:
                item.votes[email] = None

    # ── Agenda Operations / 议题操作 ──────────────────────────────────────

    def add_option(self, item: str, option: str):
        """Add a new option (used during 'counter') / 添加新选项（counter 时用）"""
        if item not in self.proposals:
            self.proposals[item] = ProposalItem(
                votes={p: None for p in self.participants}
            )
        self.proposals[item].add_option(option)

    def apply_vote(self, voter: str, item: str, choice: str):
        """Record a vote / 记录投票"""
        self.ensure_participant(voter)
        if item not in self.proposals:
            raise KeyError(f"Agenda item '{item}' does not exist / 议题 '{item}' 不存在")
        self.proposals[item].vote(voter, choice)

    def apply_votes(self, voter: str, votes: dict[str, Optional[str]]):
        """Batch record votes, votes = {item: choice | None} / 批量投票，votes = {item: choice | None}"""
        self.ensure_participant(voter)
        for item, choice in votes.items():
            if choice is not None:
                self.apply_vote(voter, item, choice)

    # ── Consensus Check / 共识检查 ──────────────────────────────────────

    def check_consensus(self) -> dict[str, Optional[str]]:
        """Return {item: resolved_value | None} / 返回 {item: resolved_value | None}"""
        return {name: item.check_consensus() for name, item in self.proposals.items()}

    def is_fully_resolved(self) -> bool:
        """Check if all agenda items have reached consensus / 所有议题是否都已达成共识"""
        consensus = self.check_consensus()
        return all(v is not None for v in consensus.values())

    def round_count(self) -> int:
        """Current number of negotiation rounds (history length) / 当前协商轮数（history 长度）"""
        return len(self.history)

    def is_stalled(self) -> bool:
        """Check if negotiation has exceeded maximum rounds / 检查协商是否超过最大轮数"""
        return self.round_count() >= MAX_ROUNDS

    # ── Round Protocol / 轮次协议 ──────────────────────────────────────

    def record_round_reply(self, from_email: str):
        """Record a respondent for the current round (deduped) / 记录本轮回复者（去重）"""
        if from_email not in self.round_respondents:
            self.round_respondents.append(from_email)

    def is_round_complete(self) -> bool:
        """
        Round 1: only non-initiators need to reply (initiator already spoke in Round 0).
        Round 2+: all participants (incl. initiator) must reply.
        第 1 轮：只需非发起方回复（发起方已在 Round 0 发出初始提案）。
        第 2 轮起：所有参与者（含发起方）均需回复。
        """
        if self.current_round == 1:
            expected = [p for p in self.participants if p != self.initiator]
        else:
            expected = list(self.participants)
        return bool(expected) and all(e in self.round_respondents for e in expected)

    def advance_round(self):
        """Advance to the next round / 进入下一轮：轮次 +1，清空本轮回复者列表"""
        self.current_round += 1
        self.round_respondents = []

    # ── History Tracking / 历史记录 ──────────────────────────────────────

    def add_history(self, from_agent: str, action: str, summary: str):
        """Add an entry to the session history / 添加一条历史记录"""
        entry = HistoryEntry(
            version=self._version,
            from_agent=from_agent,
            action=action,
            summary=summary,
        )
        self.history.append(entry)

    # ── Serialization / 序列化 ────────────────────────────────────────

    def to_json(self) -> dict:
        """Convert session to JSON dictionary / 将会话转换为 JSON 字典"""
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
            "current_round": self.current_round,
            "round_respondents": list(self.round_respondents),
        }

    @classmethod
    def from_json(cls, data: dict) -> "AIMPSession":
        """Load session from JSON dictionary / 从 JSON 字典加载会话"""
        obj = cls.__new__(cls)
        obj.session_id = data["session_id"]
        obj.topic = data.get("topic", "")
        obj.participants = list(data.get("participants", []))
        obj.initiator = data.get("from", obj.participants[0] if obj.participants else "")
        obj._version = data.get("version", 0)
        obj.status = data.get("status", "negotiating")
        obj.history = [HistoryEntry.from_dict(h) for h in data.get("history", [])]
        obj.created_at = time.time()
        obj.current_round = data.get("current_round", 1)
        obj.round_respondents = data.get("round_respondents", [])

        raw_proposals = data.get("proposals", {})
        obj.proposals = {}
        for name, raw in raw_proposals.items():
            obj.proposals[name] = ProposalItem.from_dict(raw)

        # Ensure time/location agenda items exist / 确保 time/location 议题存在
        for item_name in ("time", "location"):
            if item_name not in obj.proposals:
                obj.proposals[item_name] = ProposalItem(
                    votes={p: None for p in obj.participants}
                )

        return obj

    def clone(self) -> "AIMPSession":
        """Clone the current session / 克隆当前会话"""
        return AIMPSession.from_json(copy.deepcopy(self.to_json()))

    def __repr__(self):
        return (
            f"AIMPSession(id={self.session_id!r}, topic={self.topic!r}, "
            f"v={self._version}, status={self.status!r})"
        )


# ──────────────────────────────────────────────────────
# Phase 2 Data Structures / Phase 2 数据结构
# ──────────────────────────────────────────────────────

@dataclass
class Artifact:
    """A content artifact submitted to a Room negotiation / Room 协商中提交的内容产物"""
    name: str               # e.g. "budget_v1.txt"
    content_type: str       # "text/plain" | "application/pdf"
    body_text: str          # text content (PDF converted to text) / 文本内容（PDF 转文本）
    author: str             # submitter email / 提交者邮箱
    timestamp: float        # submission time / 提交时间

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "content_type": self.content_type,
            "body_text": self.body_text,
            "author": self.author,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Artifact":
        return cls(
            name=d["name"],
            content_type=d.get("content_type", "text/plain"),
            body_text=d.get("body_text", ""),
            author=d.get("author", ""),
            timestamp=d.get("timestamp", 0.0),
        )


@dataclass
class AIMPRoom:
    """
    Phase 2 Room: async content negotiation bounded by a deadline. /
    Phase 2 Room：有截止时间的异步内容协商。

    Status flow: open → locked → finalized
    """
    room_id: str
    topic: str
    deadline: float                             # Unix timestamp / Unix 时间戳
    participants: list[str]
    initiator: str
    artifacts: dict[str, Artifact] = field(default_factory=dict)       # {name: Artifact}
    transcript: list[HistoryEntry] = field(default_factory=list)        # discussion log / 讨论记录
    status: str = "open"                        # open → locked → finalized
    created_at: float = field(default_factory=time.time)
    resolution_rules: str = "majority"          # "majority" | "consensus" | "initiator_decides"
    accepted_by: list[str] = field(default_factory=list)                # emails that sent ACCEPT
    current_round: int = 1
    round_respondents: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "room_id": self.room_id,
            "topic": self.topic,
            "deadline": self.deadline,
            "participants": list(self.participants),
            "initiator": self.initiator,
            "artifacts": {name: a.to_dict() for name, a in self.artifacts.items()},
            "transcript": [h.to_dict() for h in self.transcript],
            "status": self.status,
            "created_at": self.created_at,
            "resolution_rules": self.resolution_rules,
            "accepted_by": list(self.accepted_by),
            "current_round": self.current_round,
            "round_respondents": list(self.round_respondents),
        }

    @classmethod
    def from_json(cls, data: dict) -> "AIMPRoom":
        room = cls.__new__(cls)
        room.room_id = data["room_id"]
        room.topic = data.get("topic", "")
        room.deadline = data.get("deadline", 0.0)
        room.participants = list(data.get("participants", []))
        room.initiator = data.get("initiator", "")
        room.artifacts = {
            name: Artifact.from_dict(a)
            for name, a in data.get("artifacts", {}).items()
        }
        room.transcript = [HistoryEntry.from_dict(h) for h in data.get("transcript", [])]
        room.status = data.get("status", "open")
        room.created_at = data.get("created_at", time.time())
        room.resolution_rules = data.get("resolution_rules", "majority")
        room.accepted_by = list(data.get("accepted_by", []))
        room.current_round = data.get("current_round", 1)
        room.round_respondents = data.get("round_respondents", [])
        return room

    def is_past_deadline(self) -> bool:
        """Check if the negotiation deadline has passed / 检查协商截止时间是否已过"""
        return time.time() > self.deadline

    def all_accepted(self) -> bool:
        """Check if all participants have sent ACCEPT / 检查所有参与者是否都已发出 ACCEPT"""
        if not self.participants:
            return False
        return all(p in self.accepted_by for p in self.participants)

    def add_to_transcript(self, from_agent: str, action: str, summary: str):
        """Append an entry to the discussion transcript / 向讨论记录追加一条"""
        version = len(self.transcript) + 1
        entry = HistoryEntry(
            version=version,
            from_agent=from_agent,
            action=action,
            summary=summary,
        )
        self.transcript.append(entry)

    # ── Round Protocol / 轮次协议 ──────────────────────────────────────

    def record_round_reply(self, from_email: str):
        """Record a respondent for the current round (deduped) / 记录本轮回复者（去重）"""
        if from_email not in self.round_respondents:
            self.round_respondents.append(from_email)

    def is_round_complete(self) -> bool:
        """
        Round 1: only non-initiators need to reply (initiator already spoke in Round 0).
        Round 2+: all participants (incl. initiator) must reply.
        """
        if self.current_round == 1:
            expected = [p for p in self.participants if p != self.initiator]
        else:
            expected = list(self.participants)
        return bool(expected) and all(e in self.round_respondents for e in expected)

    def advance_round(self):
        """Advance to the next round / 进入下一轮：轮次 +1，清空本轮回复者列表"""
        self.current_round += 1
        self.round_respondents = []

    def __repr__(self):
        return (
            f"AIMPRoom(id={self.room_id!r}, topic={self.topic!r}, "
            f"status={self.status!r}, participants={len(self.participants)})"
        )
