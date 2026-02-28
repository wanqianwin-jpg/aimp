---
name: aimp-meeting
version: "0.2.1"
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
│    · 同时也是 Hub 的普通成员之一（有自己的个人邮箱）     │
│    · 与 Hub 通信的唯一方式：用你的个人邮箱给 Hub 发邮件  │
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

**你能做的**：编辑 config.yaml、启停 Hub 进程、生成邀请码、查看状态日志、以普通成员身份给 Hub 发邮件、**在发信前把用户说的昵称/备注解析成真实邮件地址**。

**你不能做的**：直接操作 Hub 数据库、替代 Hub 处理邮件、绕过邮件协议直接发起会议。

---

## 一、首次部署清单（6 步）

### Step 1：准备两个邮箱

部署需要两类邮箱，**不能混用**：

| | 用途 | 谁用 |
|---|---|---|
| **Hub 专用邮箱** | Hub 进程收发所有协商邮件 | Hub 进程本身 |
| **你的个人邮箱** | 你给 Hub 发指令、Hub 给你发通知 | 你（管理员） |

你和 Hub 之间的所有交互，都通过**你的个人邮箱**发邮件到 **Hub 专用邮箱**完成。

Hub 专用邮箱需要开启 IMAP 服务并生成授权码（不是登录密码）：

- QQ 邮箱：设置 → 账户 → 开启 IMAP 服务 → 生成授权码
- Gmail：开启两步验证 → Google 账号 → 安全 → 应用专用密码
- **不推荐 Outlook**：Basic Auth 已关闭，OAuth2 配置复杂

| Hub 邮箱后缀 | IMAP 服务器 | SMTP 服务器 | 端口 |
|---|---|---|---|
| @gmail.com | imap.gmail.com | smtp.gmail.com | 993 / 465 |
| @qq.com | imap.qq.com | smtp.qq.com | 993 / 465 |
| @163.com / @126.com | imap.163.com | smtp.163.com | 993 / 465 |

### Step 2：安装依赖

```bash
python3 {baseDir}/scripts/install.py
```

### Step 3：生成配置文件

询问用户以下信息：

**Hub 专用邮箱（Hub 进程用）：**
- Hub 邮箱地址
- 授权码（IMAP/SMTP 密码）
- IMAP / SMTP 服务器（可按上表自动推断）

**你的管理员信息（你与 Hub 通信用）：**
- 你的名字
- 你的个人邮箱地址（这将是你给 Hub 发指令时的身份标识）

**LLM：** Anthropic / OpenAI / 本地 Ollama（详见第六节）

然后生成配置：

```bash
python3 {baseDir}/scripts/setup_config.py \
  --output ~/.aimp/config.yaml \
  --agent-email "<hub专用邮箱>" \
  --password "<授权码>" \
  --imap-server "<自动推断>" \
  --smtp-server "<自动推断>" \
  --imap-port 993 \
  --smtp-port 465 \
  --owner-name "<你的名字>" \
  --owner-email "<你的个人邮箱>" \
  --mode "hub"
```

生成后 `~/.aimp/config.yaml` 的 `members:` 段会包含你的条目，role 为 `admin`：

```yaml
members:
  admin_0:
    name: "<你的名字>"
    email: "<你实际发信用的邮箱>"   # 见下方说明
    role: "admin"
```

> **关于"你实际发信用的邮箱"**
>
> Hub 收到邮件后，用 `From:` 字段来识别发件人身份。因此这里填的必须是你给 Hub 发邮件时，邮件头里真实显示的发件地址：
>
> - 如果你**直接用个人邮箱**发邮件 → 填你的个人邮箱（如 `wanqianwin@gmail.com`）
> - 如果你**通过 OpenClaw agent 代发** → 填 agent 的邮箱地址（如 `wan@agentmail.to`）
>
> ⚠️ **这个地址绝对不能和 Hub 专用邮箱相同。** Hub 会自动丢弃所有 `From:` 等于自己地址的邮件（防止自响应死循环），导致你发的指令完全静默、没有任何错误提示。
>
> **你不需要通过邀请码注册**。管理员在 setup 时直接写入 `members:`，Hub 启动后立即识别该地址为 admin 身份。邀请码仅供后续邀请其他成员使用。

### Step 4：配置 LLM

编辑 `~/.aimp/config.yaml`，确认 `llm` 段正确：

```yaml
llm:
  provider: "anthropic"          # anthropic / openai / local
  model: "claude-sonnet-4-6"
  api_key_env: "ANTHROPIC_API_KEY"
```

详见第六节 LLM 配置。

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

### Step 6：启动并验证

**启动 Hub 守护进程：**

```bash
nohup python3 {baseDir}/../hub_agent.py ~/.aimp/config.yaml 30 > ~/.aimp/hub.log 2>&1 &
echo $! > ~/.aimp/hub.pid
echo "Hub 启动，PID: $(cat ~/.aimp/hub.pid)"
```

**从你的个人邮箱发一封测试邮件给 Hub 邮箱：**

```
收件人: <hub专用邮箱>
主题:   （任意）
正文:   帮我约 Bob 下周五下午开个 Q3 计划会
```

等 30 秒后：
- Hub 回复"找不到 Bob 的邮箱，请提供"或"需要补充信息" → Hub 正常运行 ✅
- 没有任何回复 → 查看日志排查：`tail -50 ~/.aimp/hub.log`

**重要**：Hub 进程独立于 OpenClaw 运行，OpenClaw 会话结束后 Hub 继续工作。

---

## 二、Hub 进程生命周期

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
- Hub 进程意外停止时需要手动重启（见第七节故障排查）
- **数据安全**：得益于 Store-First 架构，重启 Hub **不会丢失**任何未处理的邮件，它们会在启动后自动恢复处理。

---

## 三、管理员日常操作

| 用户说的 | 你做的 | 具体方法 |
|---|---|---|
| "给 Bob 一个邀请码" | 在 config 添加邀请码 | 编辑 `~/.aimp/config.yaml`，在 `invite_codes` 下加一条；重启 Hub；把邀请码告诉用户（附注册说明） |
| "约 Bob 开会" | 先解析 Bob 的邮件地址，再用你的邮箱给 Hub 发邮件 | 见第四节邮件模板 4.2；若不知道 Bob 邮箱，先问用户 |
| "发起一个协商室" | 先解析所有参与者的邮件地址，再用你的邮箱给 Hub 发邮件 | 见第四节邮件模板 4.3；若不知道邮箱，先问用户 |
| "现在什么情况" / "状态" | 查状态 + 日志 | `status.py` + `tail hub.log` |
| "加联系人 Dave" | 编辑 config | 直接编辑 `~/.aimp/config.yaml`，在 `contacts` 下添加 |
| "重启 Hub" | 重启后台进程 | 第二节重启命令 |
| "Hub 没反应" | 排查 | 见第七节故障排查 |

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

## 四、邮件交互模板

所有与 Hub 的交互都通过**你绑定的邮箱**发邮件给 **Hub 专用邮箱**完成。

**发信方式**：使用你（OpenClaw agent）原生的邮件发送能力，`From:` 必须是你自己绑定的邮箱地址（即 Step 3 配置的 `members:` 中的 `email:` 字段）。**不要调用任何 AIMP Python 脚本**（`initiate.py`、`respond.py` 等）来给 Hub 发指令——那些脚本使用 Hub 的 SMTP 凭据，`From:` 会变成 Hub 自己的地址，Hub 收到后会静默丢弃。

### 4.1 注册邮件（其他成员发给 Hub）

```
收件人: <hub专用邮箱>
主题:   [AIMP-INVITE:邀请码]
正文:   （任意，或留空）
```

> 管理员已在 config.yaml 中预注册，无需发此邮件。

### 4.2 约会议（你或其他成员发给 Hub）

```
收件人: <hub专用邮箱>
主题:   约会议
正文:   帮我约 bob@example.com 和 carol@example.com 下周五下午讨论 Q2 计划，Zoom 开会
```

Hub 会自动解析参与者、时间偏好、主题，发出邀请，协商完成后通知所有人。

> **必须包含完整邮件地址。** Hub 只认识自己 `contacts:` 里配置的联系人。用户说的昵称、备注（如"wan1"、"小明"）Hub 无法识别，你在发信**之前**必须查询用户通讯录，把昵称解析成真实邮件地址再写进正文。如果查不到某人的邮件地址，先向用户确认，再发给 Hub。

> **主题内容 Hub 不解析**，只用正文做 LLM 理解。主题随意写一个有意义的词即可，不要留空或写占位文字。

### 4.3 发起内容协商室（Phase 2）

```
收件人: <hub专用邮箱>
主题:   发起协商室
正文:   帮我发起一个协商室，和 bob@example.com 讨论 Q3 预算方案，3 天后截止。
        初始提案：研发 60 万，市场 25 万，运营 15 万。
```

> 同 4.2，参与者必须用真实邮件地址。

### 4.4 协商动作（回复 Hub 的 Room 邮件）

直接回复 Hub 发来的 `[AIMP:Room:xxx]` 邮件，正文写以下任意一种：

```
ACCEPT
```
同意当前提案，记录你的赞成票。

```
PROPOSE 新草案全文内容
```
提交新版本草案，完全替换当前版本。

```
AMEND 研发改为 70 万，市场改为 20 万
```
提出局部修改意见，不替换全文。

```
REJECT 预算总额超出公司限制
```
否决当前提案，并说明原因。阻断本轮收敛，需重新协商。

> **主题保持不变**：回复时不要修改 `[AIMP:Room:xxx]` 格式，系统靠此识别所属 Room。

### 4.5 否决流程（收到纪要后）

所有人 ACCEPT 或截止日期到达后，Hub 会发一封**会议纪要**邮件给所有参与者。收到后可以：

```
CONFIRM
```
确认接受纪要，完成流程。

```
REJECT 数字有误，请修正研发预算
```
否决纪要，Hub 会把原因通知发起人，由发起人决定是否重开协商室。

### 4.6 管理员自己约会议的完整流程

你（管理员）也是 Hub 的普通成员，约会议的方式和其他成员完全一样：

1. 用你的个人邮箱给 Hub 邮箱发邮件（4.2 格式）
2. Hub 解析请求，给参与者发邀请
3. 参与者回复 → Hub 协商 → 达成共识
4. Hub 通知所有人（包括你）最终结果

**你不需要直接调用 Python 脚本来发起会议。**

---

## 五、脚本参考（进阶操作）

直接调脚本仅用于调试或批量操作，日常请用邮件协议。

| 脚本 | 用途 | 示例 |
|---|---|---|
| `status.py` | 查看所有活跃协商 | `python3 {baseDir}/scripts/status.py --config ~/.aimp/config.yaml` |
| `status.py --session-id` | 查看特定协商详情 | `python3 {baseDir}/scripts/status.py --config ~/.aimp/config.yaml --session-id "meeting-001"` |
| `poll.py` | 手动触发一次轮询 | `python3 {baseDir}/scripts/poll.py --config ~/.aimp/config.yaml` |
| `respond.py` | 手动回复 escalation | `python3 {baseDir}/scripts/respond.py --config ~/.aimp/config.yaml --session-id "<id>" --response "<回复>"` |

---

## 六、LLM 配置

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

## 七、故障排查

| 现象 | 排查步骤 |
|---|---|
| Hub 没有回复邮件 | 1. 检查 Hub 是否在运行：`kill -0 $(cat ~/.aimp/hub.pid)` <br> 2. 查看日志：`tail -50 ~/.aimp/hub.log` <br> 3. 检查邮箱授权码是否正确 <br> 4. 确认邮箱已开启 IMAP 服务 |
| Hub 进程莫名停止 | 查看日志找错误原因；用 `nohup` 命令重启（第二节） |
| LLM 报错 | 检查 API Key 环境变量是否设置：`echo $ANTHROPIC_API_KEY` |
| 邮件连接失败 | QQ/163 邮箱用授权码（非登录密码）；Gmail 用应用专用密码；检查 IMAP 是否开启 |
| 成员注册失败 | 确认邀请码拼写正确；检查邀请码是否已过期或超出使用次数 |
| Hub 读不到新配置 | 修改 config.yaml 后必须重启 Hub 进程（第二节重启命令） |
| 发邮件给 Hub 没有识别我 | 确认发件邮箱与 config.yaml `members:` 中你的 `email:` 字段完全一致 |
| 发了邮件但 Hub 完全静默（日志也没有任何记录） | 发件地址（`From:`）与 Hub 专用邮箱相同，Hub 会静默丢弃自己发的邮件。检查 agent 实际使用的发件地址，确保它不等于 Hub 邮箱，并将该地址写入 `members:` |
| Hub 收件箱看起来"空的"，但手动打开能看到邮件（已读状态） | Hub 的 IMAP 轮询已经取走该邮件并标记为已读，之后才丢弃（发件地址等于 Hub 自身）。邮件已到达，问题在发件地址，不在收件。参考上一条排查 |

---

## 汇报规范

- **永远不要**把 JSON 原文丢给用户，翻译成自然语言
- **永远不要**提 session_id、IMAP、SMTP 等技术词汇
- **成功**：「搞定了！和 Bob 的会议定在周二上午 10 点，Zoom。」
- **等待中**：「邀请已经发给 Bob 了，他回复后 Hub 会处理，有结果我告诉你。」
- **冲突**：「Bob 周二不行，他说周三或周四可以。你选哪个？」
- **Hub 停了**：「Hub 进程已停止，我来帮你重启。」（直接执行重启命令，不要问确认）
