#!/usr/bin/env python3
"""
setup_config.py — 生成 AIMP agent 配置文件

用法:
  python3 setup_config.py \
    --output ~/.aimp/config.yaml \
    --agent-email "agent@gmail.com" \
    --imap-server "imap.gmail.com" \
    --smtp-server "smtp.gmail.com" \
    --password "app-password-here" \
    --owner-name "Alice" \
    --owner-email "alice@gmail.com" \
    --preferred-times "2026-03-01T10:00,2026-03-02T14:00" \
    --preferred-locations "Zoom,腾讯会议" \
    --contacts '[{"name":"Bob","agent_email":"bob-agent@gmail.com","human_email":"bob@gmail.com","has_agent":true}]'
"""
import argparse
import json
import os
import sys

import yaml


def get_input(prompt, default=None):
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    else:
        while True:
            user_input = input(f"{prompt}: ").strip()
            if user_input:
                return user_input


def interactive_mode():
    print("\n=== AIMP Agent Configuration Wizard ===\n")
    print("此向导将帮助您生成 config.yaml 配置文件。")
    print("您需要准备一个开启了 IMAP/SMTP 的邮箱（推荐使用 Gmail + 应用专用密码）。\n")

    owner_name = get_input("您的姓名 (Owner Name)", "User")
    owner_email = get_input("您的个人邮箱 (用于接收通知)")

    print("\n--- Agent 邮箱配置 ---")
    agent_email = get_input("Agent 邮箱地址")

    # 自动推断 Gmail/Outlook 配置
    default_imap = "imap.gmail.com"
    default_smtp = "smtp.gmail.com"
    if "@outlook.com" in agent_email or "@hotmail.com" in agent_email:
        default_imap = "outlook.office365.com"
        default_smtp = "smtp.office365.com"
    elif "@yahoo.com" in agent_email:
        default_imap = "imap.mail.yahoo.com"
        default_smtp = "smtp.mail.yahoo.com"

    imap_server = get_input("IMAP 服务器", default_imap)
    smtp_server = get_input("SMTP 服务器", default_smtp)
    password = get_input("邮箱密码 (或应用专用密码)", "")

    print("\n--- 会议偏好 ---")
    preferred_times = get_input("偏好时间 (逗号分隔)", "Mon 10:00, Tue 14:00")
    preferred_locations = get_input("偏好地点 (逗号分隔)", "Zoom, 腾讯会议")

    print("\n--- LLM 配置 ---")
    llm_provider = get_input("LLM 提供商 (anthropic/openai)", "anthropic")
    api_key_env = get_input("API Key 环境变量名", "ANTHROPIC_API_KEY")

    return {
        "output": os.path.expanduser("~/.aimp/config.yaml"),
        "agent_email": agent_email,
        "imap_server": imap_server,
        "smtp_server": smtp_server,
        "imap_port": 993,
        "smtp_port": 465,
        "password": password,
        "owner_name": owner_name,
        "owner_email": owner_email,
        "preferred_times": preferred_times,
        "blocked_times": "",
        "preferred_locations": preferred_locations,
        "contacts": "[]",
        "llm_provider": llm_provider,
        "llm_model": "claude-sonnet-4-5-20250514" if llm_provider == "anthropic" else "gpt-4o",
        "llm_api_key_env": api_key_env,
    }


def main():
    parser = argparse.ArgumentParser(description="生成 AIMP 配置文件")
    parser.add_argument("--interactive", action="store_true", help="运行交互式向导")
    parser.add_argument("--output", help="输出 YAML 路径")
    parser.add_argument("--agent-email", help="Agent 邮箱地址")
    parser.add_argument("--imap-server", default="imap.gmail.com", help="IMAP 服务器")
    parser.add_argument("--smtp-server", default="smtp.gmail.com", help="SMTP 服务器")
    parser.add_argument("--imap-port", type=int, default=993, help="IMAP 端口")
    parser.add_argument("--smtp-port", type=int, default=465, help="SMTP 端口")
    parser.add_argument("--password", default="", help="邮箱密码（或 $ENV_VAR 引用）")
    parser.add_argument("--owner-name", help="主人姓名")
    parser.add_argument("--owner-email", help="主人邮箱")
    parser.add_argument("--preferred-times", default="", help="偏好时间，逗号分隔")
    parser.add_argument("--blocked-times", default="", help="屏蔽时间，逗号分隔")
    parser.add_argument("--preferred-locations", default="", help="偏好地点，逗号分隔")
    parser.add_argument("--contacts", default="[]", help="联系人 JSON 数组")
    parser.add_argument("--llm-provider", default="anthropic", help="LLM provider")
    parser.add_argument("--llm-model", default="claude-sonnet-4-5-20250514", help="LLM model")
    parser.add_argument("--llm-api-key-env", default="ANTHROPIC_API_KEY", help="API key 环境变量名")
    args = parser.parse_args()

    # 如果没有提供参数或指定了 --interactive，进入交互模式
    if len(sys.argv) == 1 or args.interactive:
        config_data = interactive_mode()
        # 构造 args 对象
        class Args:
            pass
        args = Args()
        for k, v in config_data.items():
            setattr(args, k, v)
    else:
        # 非交互模式下检查必要参数
        if not all([args.output, args.agent_email, args.owner_name, args.owner_email]):
            parser.error("非交互模式下必须提供: --output, --agent-email, --owner-name, --owner-email")

    # 解析列表字段
    def split_list(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip()] if s else []

    # 解析联系人
    try:
        contacts_list = json.loads(args.contacts) if args.contacts else []
    except json.JSONDecodeError:
        print(f"联系人 JSON 解析失败: {args.contacts}", file=sys.stderr)
        sys.exit(1)

    contacts_dict = {}
    for c in contacts_list:
        name = c["name"]
        contacts_dict[name] = {
            "agent_email": c.get("agent_email", ""),
            "human_email": c.get("human_email", ""),
            "has_agent": c.get("has_agent", False),
        }

    config = {
        "agent": {
            "name": f"{args.owner_name}'s Assistant",
            "email": args.agent_email,
            "imap_server": args.imap_server,
            "smtp_server": args.smtp_server,
            "imap_port": args.imap_port,
            "smtp_port": args.smtp_port,
            "password": args.password,
        },
        "owner": {
            "name": args.owner_name,
            "email": args.owner_email,
        },
        "preferences": {
            "preferred_times": split_list(args.preferred_times),
            "blocked_times": split_list(args.blocked_times),
            "preferred_locations": split_list(args.preferred_locations),
            "auto_accept": True,
        },
        "contacts": contacts_dict,
        "llm": {
            "provider": args.llm_provider,
            "model": args.llm_model,
            "api_key_env": args.llm_api_key_env,
        },
    }

    output_path = os.path.expanduser(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(json.dumps({
        "type": "config_created",
        "path": output_path,
        "agent_email": args.agent_email,
        "owner_name": args.owner_name,
    }))


if __name__ == "__main__":
    main()
