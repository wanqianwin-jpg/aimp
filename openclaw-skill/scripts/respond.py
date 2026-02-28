#!/usr/bin/env python3
"""
respond.py — 将主人的 IM 回复注入协商

输出: JSON 事件 (consensus / reply_sent / escalation / error)

用法:
  python3 respond.py --config ~/.aimp/config.yaml --session-id "meeting-xxx" --response "周三可以，Zoom"
"""
import argparse
import logging
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_aimp_root = os.path.abspath(os.path.join(_script_dir, "..", ".."))
sys.path.insert(0, _aimp_root)

from lib.transport import EmailTransport  # noqa: E402
from lib.negotiator import Negotiator  # noqa: E402
from lib.protocol import AIMPSession  # noqa: E402
from lib.session_store import SessionStore  # noqa: E402
from lib.output import emit_event  # noqa: E402

import yaml  # noqa: E402


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_password(agent_cfg: dict) -> str:
    pwd = agent_cfg.get("password", "")
    if pwd.startswith("$"):
        env_var = pwd[1:]
        val = os.environ.get(env_var)
        if not val:
            raise ValueError(f"环境变量 {env_var} 未设置")
        return val
    return pwd


def main():
    parser = argparse.ArgumentParser(description="注入主人回复到 AIMP 协商")
    parser.add_argument("--config", required=True, help="YAML 配置文件路径")
    parser.add_argument("--session-id", required=True, help="会话 ID")
    parser.add_argument("--response", required=True, help="主人的自然语言回复")
    parser.add_argument("--db-path", default="~/.aimp/sessions.db", help="SQLite 路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    try:
        config = load_yaml(args.config)
        # 兼容 hub 模式和独立模式
        if config.get("mode") == "hub" or "members" in config:
            hub_cfg = config["hub"]
            agent_email = hub_cfg["email"]
            agent_cfg = hub_cfg
            # Hub 模式：用第一个 admin member 的名字作为 owner
            members = config.get("members", {})
            owner_name = next(
                (m.get("name", mid) for mid, m in members.items() if m.get("role") == "admin"),
                "Hub"
            )
            prefs = {}
        else:
            agent_cfg = config["agent"]
            agent_email = agent_cfg["email"]
            owner_name = config["owner"]["name"]
            prefs = config.get("preferences", {})

        store = SessionStore(args.db_path)
        session = store.load(args.session_id)
        if not session:
            emit_event("error", message=f"会话不存在: {args.session_id}")
            sys.exit(1)

        negotiator = Negotiator(
            owner_name=owner_name,
            agent_email=agent_email,
            preferences=prefs,
            llm_config=config.get("llm", {}),
        )

        transport = EmailTransport(
            email_addr=agent_email,
            imap_server=agent_cfg["imap_server"],
            smtp_server=agent_cfg["smtp_server"],
            password=resolve_password(agent_cfg),
            imap_port=agent_cfg.get("imap_port", 993),
            smtp_port=agent_cfg.get("smtp_port", 465),
        )

        # 用 LLM 解析主人的自然语言回复
        action, details = negotiator.parse_human_reply(args.response, session)
        votes = details.get("votes", {})

        for item, choice in votes.items():
            if choice:
                try:
                    session.apply_vote(agent_email, item, choice)
                except ValueError:
                    # 选项不存在，先添加再投票
                    session.add_option(item, choice)
                    session.apply_vote(agent_email, item, choice)

        # 检查共识
        if session.is_fully_resolved():
            session.status = "confirmed"
            session.bump_version()
            session.add_history(agent_email, "confirm", "所有议题已达成共识")
            summary = negotiator.generate_confirm_summary(session)
            recipients = [p for p in session.participants if p != agent_email]
            refs = store.load_message_ids(session.session_id)

            msg_id = transport.send_aimp_email(
                to=recipients,
                session_id=session.session_id,
                version=session.version,
                subject_suffix=f"{session.topic} [已确认]",
                body_text=summary,
                protocol_json=session.to_json(),
                references=refs,
            )
            store.save_message_id(session.session_id, msg_id)
            store.save(session)

            consensus = session.check_consensus()
            emit_event(
                "consensus",
                session_id=session.session_id,
                topic=session.topic,
                rounds=session.round_count(),
                **consensus,
            )
        else:
            # 发送 counter/accept 回复
            session.bump_version()
            session.add_history(agent_email, action, details.get("reason", action))
            summary = negotiator.generate_human_readable_summary(session, action)
            recipients = [p for p in session.participants if p != agent_email]
            refs = store.load_message_ids(session.session_id)

            msg_id = transport.send_aimp_email(
                to=recipients,
                session_id=session.session_id,
                version=session.version,
                subject_suffix=session.topic,
                body_text=summary,
                protocol_json=session.to_json(),
                references=refs,
            )
            store.save_message_id(session.session_id, msg_id)

            # 恢复为 negotiating（之前可能是 escalated）
            session.status = "negotiating"
            store.save(session)

            emit_event(
                "reply_sent",
                session_id=session.session_id,
                action=action,
                version=session.version,
            )

    except Exception as e:
        emit_event("error", message=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
