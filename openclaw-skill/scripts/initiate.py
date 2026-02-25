#!/usr/bin/env python3
"""
initiate.py — 发起一场新的 AIMP 会议协商

自动检测配置文件模式（hub/standalone），透明支持两种模式。

输出: JSON line {"type":"initiated"/"consensus"/"escalation", ...}

用法（独立模式）:
  python3 initiate.py --config ~/.aimp/config.yaml --topic "Q1复盘" --participants "Bob,Carol"

用法（Hub 模式）:
  python3 initiate.py --config ~/.aimp/config.yaml --topic "周会" --participants "bob,carol"
  python3 initiate.py --config ~/.aimp/config.yaml --topic "周会" --participants "bob,carol" --initiator alice
"""
import argparse
import logging
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_aimp_root = os.path.abspath(os.path.join(_script_dir, "..", ".."))
sys.path.insert(0, _aimp_root)

from hub_agent import create_agent  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="发起 AIMP 会议协商")
    parser.add_argument("--config", required=True, help="YAML 配置文件路径")
    parser.add_argument("--topic", required=True, help="会议主题")
    parser.add_argument("--participants", required=True, help="参与者名称或邮箱，逗号分隔")
    parser.add_argument("--initiator", default=None, help="[Hub 模式] 发起人的 member ID")
    parser.add_argument("--db-path", default="~/.aimp/sessions.db", help="SQLite 路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    participant_names = [n.strip() for n in args.participants.split(",") if n.strip()]

    agent = create_agent(
        config_path=args.config,
        notify_mode="stdout",
        db_path=args.db_path,
    )

    # Hub 模式：传 initiator_member_id；独立模式：忽略该参数
    from hub_agent import AIMPHubAgent
    if isinstance(agent, AIMPHubAgent):
        agent.initiate_meeting(args.topic, participant_names, initiator_member_id=args.initiator)
    else:
        agent.initiate_meeting(args.topic, participant_names)


if __name__ == "__main__":
    main()
