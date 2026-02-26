"""
output.py — Structured JSON stdout output for OpenClaw agent parsing / 结构化 JSON stdout 输出，供 OpenClaw agent 解析

Event Types: / 事件类型:
  initiated          — Meeting initiated / 会议已发起
  proposal_received  — New proposal received / 收到新提议
  consensus          — Consensus reached / 达成共识
  escalation         — Escalated to owner / 需要主人介入
  reply_sent         — Reply sent / 已发送回复
  status             — Status query result / 状态查询结果
  error              — Error occurred / 出错
"""
import json
import sys


def emit_event(event_type: str, **kwargs):
    """Print a single line of JSON to stdout for OpenClaw agent parsing / 打印一行 JSON 到 stdout，供 OpenClaw agent 解析"""
    payload = {"type": event_type, **kwargs}
    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
