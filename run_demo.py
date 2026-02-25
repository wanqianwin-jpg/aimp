"""
run_demo.py — 一键启动 3 个 Agent 演示 AIMP 协商流程

用法：
  1. 填写 config/agent_a.yaml, agent_b.yaml, agent_c.yaml（邮箱信息）
  2. 设置环境变量：
       export ANTHROPIC_API_KEY="sk-ant-..."
       export AGENT_A_PASSWORD="gmail应用专用密码"
       export AGENT_B_PASSWORD="..."
       export AGENT_C_PASSWORD="..."
  3. python run_demo.py

流程：
  - 启动 3 个 Agent（3 个线程）
  - Agent-A 自动发起「Q1 复盘会」提议
  - 观察终端输出，看协商过程
  - 达成共识后，各自主人收到确认邮件
"""
import logging
import sys
import threading
import time
import os

# 确保从 aimp 目录运行
sys.path.insert(0, os.path.dirname(__file__))

from agent import AIMPAgent


# ──────────────────────────────────────────────────────
# 日志配置（彩色输出，区分不同 Agent）
# ──────────────────────────────────────────────────────
COLORS = {
    "Alice": "\033[94m",  # 蓝
    "Bob":   "\033[92m",  # 绿
    "Carol": "\033[95m",  # 紫
    "RESET": "\033[0m",
}


class ColorFormatter(logging.Formatter):
    def __init__(self, color: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.color = color
        self.reset = COLORS["RESET"]

    def format(self, record):
        msg = super().format(record)
        return f"{self.color}{msg}{self.reset}"


def setup_logger(agent_name: str, color: str):
    logger = logging.getLogger()
    if logger.handlers:
        return  # 已配置

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorFormatter(
        color=color,
        fmt="%(asctime)s [%(threadName)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ──────────────────────────────────────────────────────
# 线程工厂
# ──────────────────────────────────────────────────────
def agent_thread(config_path: str, poll_interval: int = 15,
                 initiate: tuple = None):
    """Agent 线程入口"""
    try:
        agent = AIMPAgent(config_path)
        logger = logging.getLogger(agent.agent_name)
        logger.info(f"Agent 初始化成功: {agent.agent_name} <{agent.agent_email}>")

        if initiate:
            topic, participants = initiate
            logger.info(f"发起会议提议: topic={topic!r}, participants={participants}")
            session_id = agent.initiate_meeting(topic, participants)
            logger.info(f"会议已发起，session_id={session_id}")

        agent.run(poll_interval=poll_interval)

    except Exception as e:
        logging.error(f"Agent 线程异常: {e}", exc_info=True)


# ──────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────
def main():
    # 初始化日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(threadName)-12s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    base_dir = os.path.dirname(__file__)
    config_a = os.path.join(base_dir, "config", "agent_a.yaml")
    config_b = os.path.join(base_dir, "config", "agent_b.yaml")
    config_c = os.path.join(base_dir, "config", "agent_c.yaml")

    # 验证配置文件存在
    for path in [config_a, config_b, config_c]:
        if not os.path.exists(path):
            print(f"配置文件不存在: {path}")
            print("请先填写 config/ 目录下的 YAML 配置文件")
            sys.exit(1)

    # 验证必要环境变量
    required_env = ["ANTHROPIC_API_KEY", "AGENT_A_PASSWORD", "AGENT_B_PASSWORD", "AGENT_C_PASSWORD"]
    missing = [k for k in required_env if not os.environ.get(k)]
    if missing:
        print(f"缺少环境变量: {', '.join(missing)}")
        print("请先设置以上环境变量后重试")
        sys.exit(1)

    poll_interval = int(os.environ.get("AIMP_POLL_INTERVAL", "15"))

    print("=" * 60)
    print("AIMP Demo — 3 个 AI Agent 协商会议")
    print("=" * 60)
    print(f"轮询间隔: {poll_interval}s")
    print()

    threads = [
        threading.Thread(
            target=agent_thread,
            name="Alice-Agent",
            kwargs={
                "config_path": config_a,
                "poll_interval": poll_interval,
                "initiate": ("Q1 复盘会", ["Bob", "Carol"]),
            },
            daemon=True,
        ),
        threading.Thread(
            target=agent_thread,
            name="Bob-Agent",
            kwargs={
                "config_path": config_b,
                "poll_interval": poll_interval,
            },
            daemon=True,
        ),
        threading.Thread(
            target=agent_thread,
            name="Carol-Agent",
            kwargs={
                "config_path": config_c,
                "poll_interval": poll_interval,
            },
            daemon=True,
        ),
    ]

    print("正在启动 3 个 Agent...")
    # Agent-B/C 先启动，稍等后 Agent-A 再发起提议（确保其他 Agent 已就绪）
    threads[1].start()
    threads[2].start()
    time.sleep(2)
    threads[0].start()

    print("所有 Agent 已启动！")
    print("观察终端输出，追踪协商过程...")
    print("按 Ctrl+C 退出")
    print()

    try:
        while True:
            alive = [t for t in threads if t.is_alive()]
            if not alive:
                print("所有 Agent 线程已退出")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n演示结束，感谢使用 AIMP！")


if __name__ == "__main__":
    main()
