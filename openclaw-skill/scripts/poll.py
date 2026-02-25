#!/usr/bin/env python3
"""
poll.py — 单次轮询：检查邮件、处理协商、输出事件

输出: 每行一个 JSON 事件 (consensus / escalation / reply_sent / error)
无新事件时无输出。

用法:
  python3 poll.py --config ~/.aimp/config.yaml
"""
import argparse
import json
import logging
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_aimp_root = os.path.abspath(os.path.join(_script_dir, "..", ".."))
sys.path.insert(0, _aimp_root)

from agent import AIMPAgent  # noqa: E402
from lib.output import emit_event  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="AIMP 单次轮询")
    parser.add_argument("--config", required=True, help="YAML 配置文件路径")
    parser.add_argument("--db-path", default="~/.aimp/sessions.db", help="SQLite 路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    try:
        agent = AIMPAgent(
            config_path=args.config,
            notify_mode="stdout",
            db_path=args.db_path,
        )
        events = agent.poll()
        # poll() 内部已通过 _escalate_to_owner / _notify_owner_confirmed 输出事件
        # 额外输出 reply_sent 事件（poll 返回的）
        for evt in events:
            if evt["type"] == "reply_sent":
                emit_event(**evt)
    except Exception as e:
        emit_event("error", message=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
