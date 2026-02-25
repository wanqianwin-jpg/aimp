#!/usr/bin/env python3
"""
status.py — 查询 AIMP 会话状态

输出: JSON 事件 {"type":"status", "sessions":[...]}

用法:
  python3 status.py --config ~/.aimp/config.yaml
  python3 status.py --config ~/.aimp/config.yaml --session-id "meeting-xxx"
"""
import argparse
import json
import logging
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_aimp_root = os.path.abspath(os.path.join(_script_dir, "..", ".."))
sys.path.insert(0, _aimp_root)

from lib.session_store import SessionStore  # noqa: E402
from lib.output import emit_event  # noqa: E402


def session_summary(session) -> dict:
    consensus = session.check_consensus()
    return {
        "session_id": session.session_id,
        "topic": session.topic,
        "status": session.status,
        "version": session.version,
        "rounds": session.round_count(),
        "participants": session.participants,
        "consensus": consensus,
        "proposals": {
            item: {
                "options": p.options,
                "votes": p.votes,
                "resolved": consensus.get(item),
            }
            for item, p in session.proposals.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description="查询 AIMP 会话状态")
    parser.add_argument("--config", required=True, help="YAML 配置文件路径")
    parser.add_argument("--session-id", default=None, help="指定会话 ID（可选）")
    parser.add_argument("--db-path", default="~/.aimp/sessions.db", help="SQLite 路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    try:
        store = SessionStore(args.db_path)

        if args.session_id:
            session = store.load(args.session_id)
            if not session:
                emit_event("error", message=f"会话不存在: {args.session_id}")
                sys.exit(1)
            emit_event("status", sessions=[session_summary(session)])
        else:
            sessions = store.load_active()
            emit_event("status", sessions=[session_summary(s) for s in sessions])

    except Exception as e:
        emit_event("error", message=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
