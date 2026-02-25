"""
output.py — 结构化 JSON stdout 输出，供 OpenClaw agent 解析

事件类型:
  initiated          — 会议已发起
  proposal_received  — 收到新提议
  consensus          — 达成共识
  escalation         — 需要主人介入
  reply_sent         — 已发送回复
  status             — 状态查询结果
  error              — 出错
"""
import json
import sys


def emit_event(event_type: str, **kwargs):
    """打印一行 JSON 到 stdout，供 OpenClaw agent 解析"""
    payload = {"type": event_type, **kwargs}
    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
