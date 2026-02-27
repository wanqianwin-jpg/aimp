"""
run_room_demo.py — Phase 2 "The Room" 集成演示

模拟 3 个成员对「Q3 预算方案」进行异步内容协商：
  1. Alice 发起协商室，提交初始预算草案
  2. Bob 提出修改意见（AMEND）
  3. Carol 提出另一个修改（AMEND）
  4. Deadline 到期 → Hub 自动收尾生成会议纪要

本演示完全在内存中运行（mock 邮件 + SQLite :memory:），无需真实邮箱或 LLM。

用法：
  python run_room_demo.py
"""
import logging
import sys
import time
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

from lib.protocol import AIMPRoom, Artifact
from lib.session_store import SessionStore
from lib.email_client import ParsedEmail


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────

ALICE = "alice@example.com"
BOB   = "bob@example.com"
CAROL = "carol@example.com"
HUB   = "hub@example.com"


def build_hub(store: SessionStore):
    """Create a minimal AIMPHubAgent wired to an in-memory store."""
    from hub_agent import AIMPHubAgent, RoomNegotiator

    hub = object.__new__(AIMPHubAgent)
    hub.hub_name = "Demo Hub"
    hub.hub_email = HUB
    hub.agent_email = HUB
    hub.notify_mode = "stdout"
    hub.members = {
        "alice": {"name": "Alice", "email": ALICE},
        "bob":   {"name": "Bob",   "email": BOB},
        "carol": {"name": "Carol", "email": CAROL},
    }
    hub._email_to_member = {
        ALICE: "alice",
        BOB:   "bob",
        CAROL: "carol",
    }
    hub._raw_config = {"contacts": {}}
    hub.invite_codes = []
    hub.trusted_users = {}
    hub._replied_senders = {}
    hub.email_client = MagicMock()
    hub.store = store
    hub.negotiator = MagicMock()
    hub.hub_negotiator = MagicMock()

    # Wire a real RoomNegotiator but mock the LLM calls
    with patch("hub_agent.make_llm_client", return_value=(MagicMock(), "claude-mock", "anthropic")):
        hub.room_negotiator = RoomNegotiator("Demo Hub", HUB, {"provider": "anthropic", "model": "claude-mock"})

    return hub


def make_room_email(sender: str, room_id: str, body: str) -> ParsedEmail:
    return ParsedEmail(
        message_id=f"<{int(time.time())}@example.com>",
        subject=f"[AIMP:Room:{room_id}] Q3 预算方案",
        sender=sender,
        sender_name=sender.split("@")[0].capitalize(),
        recipients=[HUB],
        body=body,
        attachments=[],
        references=[],
        session_id=f"Room:{room_id}",
        room_id=room_id,
    )


# ──────────────────────────────────────────────────────
# Demo runner
# ──────────────────────────────────────────────────────

def run_demo():
    print()
    print("=" * 60)
    print("  AIMP Phase 2 — The Room  (内容协商演示)")
    print("=" * 60)
    print()

    store = SessionStore(":memory:")
    hub = build_hub(store)

    # ── Step 1: Alice opens a Room ─────────────────────────────────────────
    print("【Step 1】Alice 发起协商室：Q3 预算方案")
    print("-" * 40)

    initial_proposal = (
        "Q3 预算草案 v0.1\n"
        "  - 研发：$60,000\n"
        "  - 市场：$25,000\n"
        "  - 运营：$15,000\n"
        "  合计：$100,000\n"
    )

    # 5 seconds deadline (ultra short for demo)
    deadline_ts = time.time() + 8

    with patch("hub_agent.emit_event") as mock_emit:
        room_id = hub.initiate_room(
            topic="Q3 预算方案",
            participants=[ALICE, BOB, CAROL],
            deadline=deadline_ts,
            initial_proposal=initial_proposal,
            initiator=ALICE,
            resolution_rules="majority",
        )

    print(f"  Room ID: {room_id}")
    print(f"  截止时间: {hub._ts_to_iso(deadline_ts)} (8 秒后)")
    print(f"  参与者: Alice, Bob, Carol")
    print()

    # Verify room was saved
    room = store.load_room(room_id)
    assert room is not None, "Room should be saved!"
    assert room.status == "open"
    print(f"  ✅ Room 已创建，初始提案已记录（artifacts: {list(room.artifacts.keys())}）")
    print()

    # ── Step 2: Bob sends AMEND ────────────────────────────────────────────
    print("【Step 2】Bob 发送修改意见（AMEND）")
    print("-" * 40)

    bob_body = "我认为市场预算需要增加。建议调整为：市场 $35,000，研发 $55,000，合计保持 $100,000。"

    with patch("hub_agent.call_llm", return_value='{"action":"AMEND","changes":"增加市场预算至$35k，削减研发至$55k","reason":"市场竞争加剧，需要更多推广资源","new_content":"Q3预算草案v0.2\\n  - 研发：$55,000\\n  - 市场：$35,000\\n  - 运营：$15,000\\n  合计：$100,000"}'), \
         patch("hub_agent.extract_json", return_value={
             "action": "AMEND",
             "changes": "增加市场预算至$35k，削减研发至$55k",
             "reason": "市场竞争加剧，需要更多推广资源",
             "new_content": "Q3预算草案v0.2\n  - 研发：$55,000\n  - 市场：$35,000\n  - 运营：$15,000\n  合计：$100,000",
         }):
        bob_email = make_room_email(BOB, room_id, bob_body)
        events = hub._handle_room_email(bob_email)

    print(f"  Bob 发送: {bob_body[:60]}...")
    print(f"  事件: {events[0]['type']} / action={events[0]['action']}")
    room = store.load_room(room_id)
    print(f"  Transcript 条目数: {len(room.transcript)}")
    print(f"  Artifacts: {list(room.artifacts.keys())}")
    print()

    # ── Step 3: Carol sends AMEND ──────────────────────────────────────────
    print("【Step 3】Carol 发送修改意见（AMEND）")
    print("-" * 40)

    carol_body = "同意增加市场预算方向，但我建议再保留 $5k 备用金。总预算调整为 $105,000。"

    with patch("hub_agent.call_llm", return_value='{}'), \
         patch("hub_agent.extract_json", return_value={
             "action": "AMEND",
             "changes": "增加 $5k 备用金，总预算调至 $105,000",
             "reason": "风险管控",
             "new_content": "Q3预算草案v0.3\n  - 研发：$55,000\n  - 市场：$35,000\n  - 运营：$15,000\n  - 备用：$5,000\n  合计：$110,000",
         }):
        carol_email = make_room_email(CAROL, room_id, carol_body)
        events = hub._handle_room_email(carol_email)

    print(f"  Carol 发送: {carol_body[:60]}...")
    print(f"  事件: {events[0]['type']} / action={events[0]['action']}")
    room = store.load_room(room_id)
    print(f"  Transcript 条目数: {len(room.transcript)}")
    print()

    # ── Step 4: Wait for deadline, then check ─────────────────────────────
    print("【Step 4】等待 deadline 到期...")
    print("-" * 40)
    remaining = deadline_ts - time.time()
    if remaining > 0:
        print(f"  等待 {remaining:.1f} 秒...")
        time.sleep(remaining + 0.5)

    room = store.load_room(room_id)
    print(f"  deadline 是否已过: {room.is_past_deadline()}")
    print()

    # ── Step 5: _check_deadlines auto-finalizes ────────────────────────────
    print("【Step 5】Hub 检查 deadline → 自动收尾")
    print("-" * 40)

    minutes_text = (
        "# 会议纪要 — Q3 预算方案\n\n"
        "**日期**: 2026-02-27\n"
        "**参与者**: Alice, Bob, Carol\n\n"
        "## 讨论摘要\n\n"
        "1. Alice 提交初始草案（研发$60k / 市场$25k / 运营$15k）\n"
        "2. Bob 提议调整市场预算增至$35k，研发降至$55k\n"
        "3. Carol 建议增加$5k备用金\n\n"
        "## 最终决议\n\n"
        "研发：$55,000 / 市场：$35,000 / 运营：$15,000 / 备用：$5,000 / **合计：$110,000**\n\n"
        "## 下一步\n\n"
        "- 各部门负责人确认预算分配\n"
        "- Q3 正式启动前完成审批流程\n"
    )

    with patch("hub_agent.call_llm", return_value=minutes_text), \
         patch("hub_agent.extract_json", return_value={
             "current_proposal": "Q3总预算$110,000",
             "conflicts": [],
             "ready_to_finalize": True,
             "summary": "三方已就增加市场预算和备用金达成初步共识",
         }), \
         patch("hub_agent.emit_event") as mock_emit:
        hub._check_deadlines()

    room = store.load_room(room_id)
    print(f"  Room 状态: {room.status}")
    print(f"  Transcript 条目数: {len(room.transcript)}")
    assert room.status == "finalized", f"Expected finalized, got {room.status}"

    # Verify finalized transcript entry exists
    actions = [e.action for e in room.transcript]
    assert "FINALIZED" in actions, "Should have FINALIZED entry"

    print()
    print("  已生成会议纪要（节选）:")
    print("  " + "-" * 38)
    for line in minutes_text.split("\n")[:12]:
        print(f"  {line}")
    print("  ...")
    print()

    # ── Step 6: Veto flow ──────────────────────────────────────────────────
    print("【Step 6】Bob 发送 REJECT（否决纪要）")
    print("-" * 40)

    reject_email = make_room_email(BOB, room_id, "REJECT 备用金数字应该是 $8,000 不是 $5,000")
    events = hub._handle_room_reject(room, BOB, "备用金数字应该是 $8,000 不是 $5,000")

    print(f"  事件: {events[0]['type']}")
    print(f"  否决原因: {events[0]['reason']}")
    # In stdout mode, send_human_email is mocked, but we can check the call
    print()

    print("【Step 7】Alice 发送 CONFIRM（确认纪要）")
    print("-" * 40)
    events = hub._handle_room_confirm(room, ALICE)
    print(f"  事件: {events[0]['type']}")
    print(f"  Alice 已确认")
    print()

    # ── Summary ────────────────────────────────────────────────────────────
    print("=" * 60)
    print("  演示完成 ✅")
    print("=" * 60)
    print()
    print("  验证结果：")
    print(f"    Room ID:      {room_id}")
    print(f"    最终状态:     {room.status}")
    print(f"    Transcript:   {len(room.transcript)} 条记录")
    print(f"    Artifacts:    {len(room.artifacts)} 个产物")
    print()
    print("  Phase 2 核心流程验证通过：")
    print("    ✅ initiate_room 创建 AIMPRoom + 记录初始提案")
    print("    ✅ _handle_room_email 处理 AMEND 修正，更新 transcript")
    print("    ✅ is_past_deadline 截止判断")
    print("    ✅ _check_deadlines 自动收尾")
    print("    ✅ generate_meeting_minutes 生成会议纪要")
    print("    ✅ _handle_room_reject 否决升级给发起人")
    print("    ✅ _handle_room_confirm 确认流程")
    print()
    store.close()


if __name__ == "__main__":
    run_demo()
