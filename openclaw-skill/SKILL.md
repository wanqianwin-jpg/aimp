---
name: aimp-meeting
version: "0.2.0"
description: "AI 会议义体管理员：部署并操控 AIMP Hub 后台进程，通过 Email 协议自动协商会议。"
emoji: "🦾"
metadata:
  openclaw:
    requires:
      bins: ["python3"]
    primaryEnv: "ANTHROPIC_API_KEY"
    os: ["darwin", "linux"]
---

# AIMP 管理员 Skill

## 你是谁（必读）

**你是 Hub 的管理员 Agent，不是 Hub 本身。**

```
┌─────────────────────────────────────────────────────────┐
│  你（OpenClaw 管理员 Agent）                             │
│    · 负责：配置 Hub / 启停 Hub 进程 / 管理邀请码         │
│    · 同时也是 Hub 的普通成员之一（有自己的邮箱）         │
│    · 与 Hub 通信的唯一方式：给 Hub 邮箱发邮件            │
├─────────────────────────────────────────────────────────┤
│  Hub 守护进程（独立的后台 Python 进程）                  │
│    · 启动命令：python3 hub_agent.py ~/.aimp/config.yaml  │
│    · 独立于 OpenClaw 运行，不随会话结束而停止            │
│    · 持续轮询 Hub 邮箱，自动处理成员请求                 │
├─────────────────────────────────────────────────────────┤
│  成员（人类 / 其他 Agent）                               │
│    · 只通过给 Hub 邮箱发邮件与系统交互                   │
│    · 注册：发带邀请码的邮件                              │
│    · 约会议：发自然语言邮件                              │
└─────────────────────────────────────────────────────────┘
```

**你能做的**：编辑 config.yaml、启停 Hub 进程、生成邀请码、查看状态日志、以普通成员身份给 Hub 发邮件。

**你不能做的**：直接操作 Hub 数据库、替代 Hub 处理邮件、绕过邮件协议直接发起会议。

---

## 一、安装为 OpenClaw Skill

用户从 GitHub 拉取代码后，需要将 `openclaw-skill/` 目录注册为 OpenClaw Skill：

**方式 1（推荐）：clawhub 安装**
```bash
clawhub install https://github.com/user/aimp
```

**方式 2：手动放置**
```bash
# 复制到 OpenClaw skills 目录
cp -r /path/to/aimp/openclaw-skill ~/.openclaw/skills/aimp-meeting
# 或放到当前 workspace 的 skills 子目录
cp -r /path/to/aimp/openclaw-skill <workspace>/skills/aimp-meeting
```

`{baseDir}` 解析为 `openclaw-skill/` 目录的绝对路径。

---

## 二、首次部署清单（7 步）

### Step 1：准备 Hub 专用邮箱

Hub 必须有一个**独立邮箱**，不能是任何成员的个人邮箱。推荐 QQ / 163 / Gmail。

- QQ 邮箱：设置 → 账户 → 开启 IMAP 服务 → 生成授权码（不是登录密码）
- Gmail：开启两步验证 → Google 账号 → 安全 → 应用专用密码
- **不推荐 Outlook**：Basic Auth 已关闭，OAuth2 配置复杂

| 邮箱后缀 | IMAP 服务器 | SMTP 服务器 | 端口 |
|---|---|---|---|
| @gmail.com | imap.gmail.com | smtp.gmail.com | 993 / 465 |
| @qq.com | imap.qq.com | smtp.qq.com | 993 / 465 |
| @163.com / @126.com | imap.163.com | smtp.163.com | 993 / 465 |

### Step 2：安装依赖

```bash
python3 {baseDir}/scripts/install.py
```

### Step 3：生成配置文件

询问用户：
1. Hub 专用邮箱地址和授权码
2. 你（管理员）的名字和个人邮箱（作为第一个成员）
3. LLM 选择（Anthropic / OpenAI / 本地 Ollama）

然后生成配置：

```bash
python3 {baseDir}/scripts/setup_config.py \
  --output ~/.aimp/config.yaml \
  --agent-email "<hub邮箱>" \
  --password "<授权码>" \
  --imap-server "<自动推断>" \
  --smtp-server "<自动推断>" \
  --imap-port 993 \
  --smtp-port 465 \
  --owner-name "<管理员名字>" \
  --owner-email "<管理员邮箱>" \
  --mode "hub"
```

### Step 4：配置 LLM

编辑 `~/.aimp/config.yaml`，确认 `llm` 段正确：

```yaml
llm:
  provider: "anthropic"          # anthropic / openai / local
  model: "claude-sonnet-4-6"
  api_key_env: "ANTHROPIC_API_KEY"
```

详见第七节 LLM 配置。

### Step 5：设置环境变量

```bash
# Hub 邮箱密码（授权码）
export HUB_PASSWORD="your_auth_code_here"

# LLM API Key（按实际使用的提供商）
export ANTHROPIC_API_KEY="sk-ant-..."
# 或
export OPENAI_API_KEY="sk-..."
```

在 `~/.aimp/config.yaml` 的密码字段写 `"$HUB_PASSWORD"`，Hub 启动时自动读取。

### Step 6：启动 Hub 守护进程

```bash
nohup python3 {baseDir}/../hub_agent.py ~/.aimp/config.yaml 30 > ~/.aimp/hub.log 2>&1 &
echo $! > ~/.aimp/hub.pid
echo "Hub 启动，PID: $(cat ~/.aimp/hub.pid)"
```

**重要**：Hub 进程独立于 OpenClaw 运行，OpenClaw 会话结束后 Hub 继续工作。

### Step 7：验证 Hub 在线

以管理员身份给 Hub 发一封注册邮件（你自己也需要注册）：

- 先在 config.yaml 里添加一个邀请码（见第四节）
- 给 Hub 邮箱发邮件，主题：`[AIMP-INVITE:你设的邀请码]`
- 等 30 秒后查看日志：`tail -f ~/.aimp/hub.log`
- 收到 Hub 的欢迎回复 → 部署成功 ✅

---

## 三、Hub 进程生命周期

**每次 OpenClaw 启动时，先检查 Hub 是否在运行：**

```bash
# 检查状态
kill -0 $(cat ~/.aimp/hub.pid 2>/dev/null) 2>/dev/null && echo "Hub 运行中 ✅" || echo "Hub 已停止 ❌"

# 查看日志（最近 20 行）
tail -20 ~/.aimp/hub.log
```

**启动**：
```bash
nohup python3 {baseDir}/../hub_agent.py ~/.aimp/config.yaml 30 > ~/.aimp/hub.log 2>&1 &
echo $! > ~/.aimp/hub.pid
```

**重启**（修改 config 后）：
```bash
kill $(cat ~/.aimp/hub.pid) 2>/dev/null
sleep 2
nohup python3 {baseDir}/../hub_agent.py ~/.aimp/config.yaml 30 > ~/.aimp/hub.log 2>&1 &
echo $! > ~/.aimp/hub.pid
```

**停止**：
```bash
kill $(cat ~/.aimp/hub.pid)
```

**关键说明**：
- Hub 进程**不是** OpenClaw 管理的 background process
- OpenClaw session 结束后 Hub 继续运行 ✅
- Hub 进程意外停止时需要手动重启（见第八节故障排查）

---

## 四、管理员日常操作

| 用户说的 | 你做的 | 具体方法 |
|---|---|---|
| "给 Bob 一个邀请码" | 在 config 添加邀请码 | 编辑 `~/.aimp/config.yaml`，在 `invite_codes` 下加一条；重启 Hub；把邀请码告诉用户（附注册说明） |
| "约 Bob 开会" | **以成员身份**给 Hub 邮箱发邮件 | 见第五节邮件模板 5.2 |
| "发起一个协商室" | **以成员身份**给 Hub 邮箱发邮件 | 见第五节邮件模板 5.3 |
| "现在什么情况" / "状态" | 查状态 + 日志 | `status.py` + `tail hub.log` |
| "加联系人 Dave" | 编辑 config | 直接编辑 `~/.aimp/config.yaml`，在 `contacts` 下添加 |
| "重启 Hub" | 重启后台进程 | 第三节重启命令 |
| "Hub 没反应" | 排查 | 见第八节故障排查 |

### 生成邀请码

在 `~/.aimp/config.yaml` 的 `invite_codes` 段添加：

```yaml
invite_codes:
  - code: "welcome-2026"
    expires: "2026-12-31"
    max_uses: 5
    used: 0
```

重启 Hub 使配置生效。告诉用户：
> "邀请码是 `welcome-2026`。让 Bob 给 Hub 邮箱（hub@example.com）发一封邮件，主题写 `[AIMP-INVITE:welcome-2026]`，正文随意，Hub 会自动回复欢迎邮件完成注册。"

---

## 五、邮件交互模板

所有与 Hub 的交互都通过给 **Hub 邮箱** 发邮件完成。

### 5.1 注册邮件（成员发给 Hub）

```
收件人: hub@example.com
主题:   [AIMP-INVITE:邀请码]
正文:   （任意，或留空）
```

### 5.2 约会议（成员发给 Hub）

```
收件人: hub@example.com
主题:   （任意）
正文:   帮我约 Bob 和 Carol 下周五下午讨论 Q2 计划，Zoom 开会
```

Hub 会自动解析参与者、时间偏好、主题，发出邀请，协商完成后通知所有人。

### 5.3 发起内容协商室（Phase 2）

```
收件人: hub@example.com
主题:   （任意）
正文:   帮我发起一个协商室，和 Bob 讨论 Q3 预算方案，3 天后截止。
        初始提案：研发 60 万，市场 25 万，运营 15 万。
```

### 5.4 投票 / 修改 / 接受（回复 Hub 的邮件）

```
收件人: hub@example.com（直接回复 Hub 发来的邮件）
主题:   保持原格式（[AIMP:session_id] 开头，系统自动）
正文:   ACCEPT
      —— 或 ——
        AMEND 研发改为 70 万，市场改为 20 万
      —— 或 ——
        REJECT 预算总额超出限制
```

### 5.5 管理员自己约会议的完整流程

你（管理员）也是 Hub 的普通成员，约会议的方式和其他成员完全一样：

1. 你给 Hub 邮箱发邮件（5.2 格式）
2. Hub 解析请求，给参与者发邀请
3. 参与者回复 → Hub 协商 → 达成共识
4. Hub 通知所有人（包括你）最终结果

**你不需要直接调用 Python 脚本来发起会议。**

---

## 六、脚本参考（进阶操作）

直接调脚本仅用于调试或批量操作，日常请用邮件协议。

| 脚本 | 用途 | 示例 |
|---|---|---|
| `status.py` | 查看所有活跃协商 | `python3 {baseDir}/scripts/status.py --config ~/.aimp/config.yaml` |
| `status.py --session-id` | 查看特定协商详情 | `python3 {baseDir}/scripts/status.py --config ~/.aimp/config.yaml --session-id "meeting-001"` |
| `poll.py` | 手动触发一次轮询 | `python3 {baseDir}/scripts/poll.py --config ~/.aimp/config.yaml` |
| `respond.py` | 手动回复 escalation | `python3 {baseDir}/scripts/respond.py --config ~/.aimp/config.yaml --session-id "<id>" --response "<回复>"` |

---

## 七、LLM 配置

Hub 有自己的 LLM（在 `~/.aimp/config.yaml` 的 `llm` 段），用于解析邮件内容和协商决策。

| 提供商 | 配置示例 |
|---|---|
| Anthropic（推荐） | `provider: anthropic`，`model: claude-sonnet-4-6`，`api_key_env: ANTHROPIC_API_KEY` |
| OpenAI | `provider: openai`，`model: gpt-4o`，`api_key_env: OPENAI_API_KEY` |
| 本地 Ollama | `provider: local`，`model: llama3`，`base_url: http://localhost:11434/v1` |

配置示例：
```yaml
llm:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
  api_key_env: "ANTHROPIC_API_KEY"
```

修改 LLM 配置后需要重启 Hub 进程。

---

## 八、故障排查

| 现象 | 排查步骤 |
|---|---|
| Hub 没有回复邮件 | 1. 检查 Hub 是否在运行：`kill -0 $(cat ~/.aimp/hub.pid)` <br> 2. 查看日志：`tail -50 ~/.aimp/hub.log` <br> 3. 检查邮箱授权码是否正确 <br> 4. 确认邮箱已开启 IMAP 服务 |
| Hub 进程莫名停止 | 查看日志找错误原因；用 `nohup` 命令重启（第三节） |
| LLM 报错 | 检查 API Key 环境变量是否设置：`echo $ANTHROPIC_API_KEY` |
| 邮件连接失败 | QQ/163 邮箱用授权码（非登录密码）；Gmail 用应用专用密码；检查 IMAP 是否开启 |
| 成员注册失败 | 确认邀请码拼写正确；检查邀请码是否已过期或超出使用次数 |
| Hub 读不到新配置 | 修改 config.yaml 后必须重启 Hub 进程（第三节重启命令） |

---

## 汇报规范

- **永远不要**把 JSON 原文丢给用户，翻译成自然语言
- **永远不要**提 session_id、IMAP、SMTP 等技术词汇
- **成功**：「搞定了！和 Bob 的会议定在周二上午 10 点，Zoom。」
- **等待中**：「邀请已经发给 Bob 了，他回复后 Hub 会处理，有结果我告诉你。」
- **冲突**：「Bob 周二不行，他说周三或周四可以。你选哪个？」
- **Hub 停了**：「Hub 进程已停止，我来帮你重启。」（直接执行重启命令，不要问确认）
