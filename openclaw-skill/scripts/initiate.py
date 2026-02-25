#!/usr/bin/env python3
"""
initiate.py — 发起一场新的 AIMP 会议协商

输出: JSON line {"type":"initiated", "session_id":..., "topic":..., "participants":[...]}

用法:
  python3 initiate.py --config ~/.aimp/config.yaml --topic "Q1复盘" --participants "Bob,Carol"
"""
import argparse
import logging
import os
import sys

# 将 aimp/ 根目录加入 path，复用 lib/
_script_dir = os.path.dirname(os.path.abspath(__file__))
_aimp_root = os.path.abspath(os.path.join(_script_dir, "..", ".."))
sys.path.insert(0, _aimp_root)

from agent import AIMPAgent  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="发起 AIMP 会议协商")
    parser.add_argument("--config", required=True, help="YAML 配置文件路径")
    parser.add_argument("--topic", required=True, help="会议主题")
    parser.add_argument("--participants", required=True, help="参与者名称，逗号分隔")
    parser.add_argument("--db-path", default="~/.aimp/sessions.db", help="SQLite 路径")
    args = parser.parse_args()

    # 静默日志，只输出 JSON 到 stdout
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    participant_names = [n.strip() for n in args.participants.split(",") if n.strip()]

    agent = AIMPAgent(
        config_path=args.config,
        notify_mode="stdout",
        db_path=args.db_path,
    )
    session_id = agent.initiate_meeting(args.topic, participant_names)
    # initiate_meeting 已经通过 emit_event 输出了 "initiated" 事件


if __name__ == "__main__":
    main()
