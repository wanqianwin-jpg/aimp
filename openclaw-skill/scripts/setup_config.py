#!/usr/bin/env python3
"""
setup_config.py — 生成 AIMP agent 配置文件

支持两种模式：
  standalone：1 人 1 Agent（原始模式，向后兼容）
  hub：       1 个 Hub 服务多人（Hub 模式，推荐家庭/小团队）

用法（独立模式，非交互）:
  python3 setup_config.py \
    --output ~/.aimp/config.yaml \
    --agent-email "agent@gmail.com" \
    --imap-server "imap.gmail.com" \
    --smtp-server "smtp.gmail.com" \
    --password "app-password-here" \
    --owner-name "Alice" \
    --owner-email "alice@gmail.com" \
    --preferred-times "2026-03-01T10:00,2026-03-02T14:00" \
    --preferred-locations "Zoom,腾讯会议"

用法（交互向导）:
  python3 setup_config.py --interactive
  python3 setup_config.py --interactive --hub   # 直接进 Hub 向导
"""
import argparse
import json
import os
import sys

import yaml


def get_input(prompt, default=None, allow_empty=False):
    if default is not None:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    else:
        while True:
            user_input = input(f"{prompt}: ").strip()
            if user_input or allow_empty:
                return user_input


def split_list(s: str) -> list:
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


def ask_llm_config():
    """交互式询问 LLM 配置，返回 (provider, model, api_key_env, base_url)"""
    print("\n--- LLM 智能配置 (Agent 的'大脑') ---")
    print("AIMP 作为后台运行的 Agent，需要自己的 LLM 来解析邮件并做决策。")

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if anthropic_key:
        print("  ✓ 检测到环境变量 ANTHROPIC_API_KEY")
    if openai_key:
        print("  ✓ 检测到环境变量 OPENAI_API_KEY")

    choice = get_input("选择 LLM 类型 (1=Anthropic, 2=OpenAI, 3=本地 Ollama/LM Studio)", "1")

    base_url = None
    if choice == "3":
        provider = "local"
        base_url = get_input("本地 API 地址 (Base URL)", "http://localhost:11434/v1")
        model = get_input("本地模型名称", "llama3")
        api_key_env = "LOCAL_API_KEY"
    elif choice == "2":
        provider = "openai"
        api_key_env = "OPENAI_API_KEY"
        model = "gpt-4o"
    else:
        provider = "anthropic"
        api_key_env = "ANTHROPIC_API_KEY"
        model = "claude-sonnet-4-5-20250514"

    return provider, model, api_key_env, base_url


def ask_email_config(label="Agent"):
    """交互式询问邮箱配置，返回 (email, imap, smtp, imap_port, smtp_port, password)"""
    print(f"\n--- {label} 邮箱配置 ---")
    email = get_input(f"{label} 邮箱地址")

    default_imap, default_smtp = "imap.gmail.com", "smtp.gmail.com"
    default_imap_port, default_smtp_port = 993, 465
    is_outlook = False

    if "@outlook.com" in email or "@hotmail.com" in email or "@live.com" in email:
        is_outlook = True
        # Outlook personal: IMAP=outlook.office365.com:993/SSL, SMTP=smtp-mail.outlook.com:587/STARTTLS
        default_imap, default_smtp = "outlook.office365.com", "smtp-mail.outlook.com"
        default_imap_port, default_smtp_port = 993, 587
        print("\n[❌ Outlook/Hotmail 强烈不推荐]")
        print("  微软已于2022年10月彻底关闭 IMAP 的 Basic Auth（含 App Password）。")
        print("  Outlook 个人邮箱现在只支持 OAuth2，配置需要在 Azure 注册应用，流程复杂。")
        print("  强烈建议改用 QQ/163/Gmail 作为 Agent 专用邮箱，5分钟配好。")
        print("  如果你坚持用 Outlook，请使用 OAuth2 模式（需手动编辑 config.yaml）。")
    elif "@yahoo.com" in email:
        default_imap, default_smtp = "imap.mail.yahoo.com", "smtp.mail.yahoo.com"
        default_imap_port, default_smtp_port = 993, 465
    elif "@qq.com" in email:
        default_imap, default_smtp = "imap.qq.com", "smtp.qq.com"
        default_imap_port, default_smtp_port = 993, 465
        print("\n[QQ 邮箱用户注意]")
        print("  需要开启 SMTP/IMAP 服务并使用授权码（非登录密码）作为密码。")
        print("  开启方法：QQ邮箱网页版 -> 设置 -> 账户 -> POP3/IMAP/SMTP服务 -> 开启")
    elif "@163.com" in email or "@126.com" in email:
        default_imap, default_smtp = "imap.163.com", "smtp.163.com"
        default_imap_port, default_smtp_port = 993, 465
        print("\n[网易邮箱用户注意]")
        print("  需要开启 SMTP/IMAP 服务并使用授权码。")
        print("  开启方法：163邮箱 -> 设置 -> POP3/SMTP/IMAP -> 开启服务")
    elif "@gmail.com" in email:
        print("\n[Gmail 用户注意]")
        print("  需要开启两步验证，然后生成应用专用密码 (App Password)。")
        print("  App Password 生成: Google 账户 -> 安全性 -> 两步验证 -> 应用专用密码")

    imap_server = get_input("IMAP 服务器", default_imap)
    smtp_server = get_input("SMTP 服务器", default_smtp)
    imap_port = int(get_input("IMAP 端口", str(default_imap_port)))
    smtp_port = int(get_input("SMTP 端口", str(default_smtp_port)))
    password = get_input("邮箱密码 (或应用专用密码，留空跳过)", "", allow_empty=True)

    return email, imap_server, smtp_server, imap_port, smtp_port, password


# ──────────────────────────────────────────────────────
# Hub 模式交互向导
# ──────────────────────────────────────────────────────

def interactive_hub_mode():
    """Hub 模式交互向导，返回完整 config dict"""
    print("\n=== AIMP Hub 配置向导 ===\n")
    print("Hub 模式：一个 Agent 邮箱服务多名成员。")
    print("成员之间开会时，Hub 直接读取所有人偏好并自动协调（无需邮件往返）。\n")

    hub_name = get_input("Hub 名称 (如'家庭助理'或'团队助理')", "Family Hub")
    hub_email, imap_server, smtp_server, imap_port, smtp_port, password = ask_email_config("Hub Agent")

    provider, model, api_key_env, base_url = ask_llm_config()

    print("\n--- 成员配置 ---")
    print("每个成员需要姓名、邮箱和会议偏好。第一个成员默认为 admin。\n")

    members = {}
    member_count = int(get_input("成员数量", "2"))

    for i in range(member_count):
        print(f"\n-- 成员 {i+1} --")
        mid = get_input("成员 ID (字母/数字，如 alice)", f"member{i+1}")
        name = get_input("成员姓名", mid.capitalize())
        email = get_input("成员邮箱 (用于接收通知和发送指令)")
        role = "admin" if i == 0 else "member"

        print(f"  会议偏好（{name}）：")
        preferred_times = get_input(
            "  偏好时间 (逗号分隔)", "weekday mornings 9:00-12:00", allow_empty=True
        )
        blocked_times = get_input("  屏蔽时间 (逗号分隔，可留空)", "", allow_empty=True)
        preferred_locations = get_input(
            "  偏好地点 (逗号分隔)", "Zoom,腾讯会议", allow_empty=True
        )

        members[mid] = {
            "name": name,
            "email": email,
            "role": role,
            "preferences": {
                "preferred_times": split_list(preferred_times),
                "blocked_times": split_list(blocked_times),
                "preferred_locations": split_list(preferred_locations),
                "auto_accept": True,
            },
        }

    print("\n--- 外部联系人（可选，Hub 成员以外的人）---")
    contacts = {}
    if get_input("是否添加外部联系人？(y/n)", "n").lower() == "y":
        contact_count = int(get_input("外部联系人数量", "1"))
        for i in range(contact_count):
            print(f"\n-- 外部联系人 {i+1} --")
            cname = get_input("姓名")
            has_agent = get_input("对方是否有 AIMP Agent？(y/n)", "n").lower() == "y"
            human_email = get_input("对方邮箱")
            agent_email = get_input("对方的 Agent 邮箱", "", allow_empty=True) if has_agent else ""
            contacts[cname] = {
                "human_email": human_email,
                "agent_email": agent_email,
                "has_agent": has_agent,
            }

    config = {
        "mode": "hub",
        "hub": {
            "name": hub_name,
            "email": hub_email,
            "imap_server": imap_server,
            "smtp_server": smtp_server,
            "imap_port": imap_port,
            "smtp_port": smtp_port,
            "password": password,
        },
        "members": members,
        "contacts": contacts,
        "llm": {
            "provider": provider,
            "model": model,
            "api_key_env": api_key_env,
        },
    }
    if base_url:
        config["llm"]["base_url"] = base_url

    return config


# ──────────────────────────────────────────────────────
# 独立模式交互向导（原有逻辑）
# ──────────────────────────────────────────────────────

def interactive_standalone_mode():
    """独立模式交互向导，返回完整 config dict"""
    print("\n=== AIMP Agent 独立模式配置向导 ===\n")
    print("独立模式：1 人 1 Agent，各自配置和运行自己的 Agent。\n")

    owner_name = get_input("您的姓名 (Owner Name)", "User")
    owner_email = get_input("您的个人邮箱 (用于接收通知)")

    agent_email, imap_server, smtp_server, imap_port, smtp_port, password = ask_email_config("Agent")

    print("\n--- 会议偏好 ---")
    preferred_times = get_input("偏好时间 (逗号分隔)", "Mon 10:00, Tue 14:00")
    blocked_times = get_input("屏蔽时间 (逗号分隔，可留空)", "", allow_empty=True)
    preferred_locations = get_input("偏好地点 (逗号分隔)", "Zoom, 腾讯会议")

    provider, model, api_key_env, base_url = ask_llm_config()

    config = {
        "agent": {
            "name": f"{owner_name}'s Assistant",
            "email": agent_email,
            "imap_server": imap_server,
            "smtp_server": smtp_server,
            "imap_port": imap_port,
            "smtp_port": smtp_port,
            "password": password,
        },
        "owner": {
            "name": owner_name,
            "email": owner_email,
        },
        "preferences": {
            "preferred_times": split_list(preferred_times),
            "blocked_times": split_list(blocked_times),
            "preferred_locations": split_list(preferred_locations),
            "auto_accept": True,
        },
        "contacts": {},
        "llm": {
            "provider": provider,
            "model": model,
            "api_key_env": api_key_env,
        },
    }
    if base_url:
        config["llm"]["base_url"] = base_url

    return config


# ──────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="生成 AIMP 配置文件")
    parser.add_argument("--interactive", action="store_true", help="运行交互式向导")
    parser.add_argument("--hub", action="store_true", help="直接进入 Hub 模式向导")
    parser.add_argument("--output", default="~/.aimp/config.yaml", help="输出 YAML 路径")
    parser.add_argument("--mode", choices=["standalone", "hub"], default="standalone", help="配置模式 (非交互模式用)")

    # 独立模式/Hub基础参数
    parser.add_argument("--agent-email")
    parser.add_argument("--imap-server", default="imap.gmail.com")
    parser.add_argument("--smtp-server", default="smtp.gmail.com")
    parser.add_argument("--imap-port", type=int, default=993)
    parser.add_argument("--smtp-port", type=int, default=465)
    parser.add_argument("--password", default="")
    parser.add_argument("--owner-name", help="Standalone Owner Name 或 Hub Admin Name")
    parser.add_argument("--owner-email", help="Standalone Owner Email 或 Hub Admin Email")
    parser.add_argument("--preferred-times", default="")
    parser.add_argument("--blocked-times", default="")
    parser.add_argument("--preferred-locations", default="")
    parser.add_argument("--contacts", default="[]", help="联系人 JSON 数组")
    parser.add_argument("--llm-provider", default="anthropic")
    parser.add_argument("--llm-model", default="claude-sonnet-4-5-20250514")
    parser.add_argument("--llm-api-key-env", default="ANTHROPIC_API_KEY")
    parser.add_argument("--llm-base_url", default="", help="本地模型 Base URL（Ollama 等）")
    args = parser.parse_args()

    # 决定走哪条路
    if args.interactive:
        if args.hub:
            config = interactive_hub_mode()
        else:
            print("\n选择配置模式：")
            print("  1. Hub 模式（推荐）：一个 Agent 服务多人，适合家庭/小团队")
            print("  2. 独立模式：每人一个 Agent，适合个人使用")
            mode_choice = get_input("请选择 (1/2)", "1")
            config = interactive_hub_mode() if mode_choice == "1" else interactive_standalone_mode()
    else:
        # 非交互模式
        if not all([args.agent_email, args.owner_name, args.owner_email]):
            parser.error("非交互模式下必须提供: --agent-email, --owner-name, --owner-email")

        try:
            contacts_list = json.loads(args.contacts) if args.contacts else []
        except json.JSONDecodeError:
            print(f"联系人 JSON 解析失败: {args.contacts}", file=sys.stderr)
            sys.exit(1)

        contacts_dict = {}
        for c in contacts_list:
            contacts_dict[c["name"]] = {
                "agent_email": c.get("agent_email", ""),
                "human_email": c.get("human_email", ""),
                "has_agent": c.get("has_agent", False),
            }

        agent_config = {
            "name": f"{args.owner_name}'s Assistant",
            "email": args.agent_email,
            "imap_server": args.imap_server,
            "smtp_server": args.smtp_server,
            "imap_port": args.imap_port,
            "smtp_port": args.smtp_port,
            "password": args.password,
        }
        
        llm_config = {
            "provider": args.llm_provider,
            "model": args.llm_model,
            "api_key_env": args.llm_api_key_env,
        }
        if args.llm_base_url:
            llm_config["base_url"] = args.llm_base_url

        if args.mode == "hub":
            # Hub 模式：将 owner 参数作为第一个管理员成员
            config = {
                "mode": "hub",
                "agent": agent_config,
                "hub": {
                    "owners": [
                        {
                            "name": args.owner_name,
                            "email": args.owner_email,
                            "preferences": {
                                "preferred_times": split_list(args.preferred_times),
                                "blocked_times": split_list(args.blocked_times),
                                "preferred_locations": split_list(args.preferred_locations),
                                "auto_accept": True,
                            }
                        }
                    ]
                },
                "contacts": contacts_dict,
                "llm": llm_config,
            }
        else:
            # Standalone 模式
            config = {
                "mode": "standalone",
                "agent": agent_config,
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
                "llm": llm_config,
            }

    # 写文件
    output_path = os.path.expanduser(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    mode = config.get("mode", "standalone")
    result = {"type": "config_created", "path": output_path, "mode": mode}
    if mode == "hub":
        result["hub_email"] = config["hub"]["email"]
        result["members"] = list(config.get("members", {}).keys())
    else:
        result["agent_email"] = config["agent"]["email"]
        result["owner_name"] = config["owner"]["name"]

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
