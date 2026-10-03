# hltv-bot

HLTV 赛程和赛事页（`curl_cffi`）+ Telegram 提醒。时间 **UTC+8**。通知发到已授权群，默认无声。

完整 Chrome 记分板在分支 `archive/chrome-full`，主线不启动它。Cookie 仍用 `/cookie` 贴到 `data/session.json`。

## 文档

| 文档 | |
|---|---|
| [docs/hltv-api.md](docs/hltv-api.md) | 非官方 HLTV 接口：列表 HTML、详情 meta、Scorebot Engine.IO、事件字段 |
| [docs/scorebot-data.md](docs/scorebot-data.md) | Scorebot / snapshot / log 归一化数据结构（全面） |
| [docs/cloudflare.md](docs/cloudflare.md) | Cookie / Chrome keeper / curl 退路 |
| [docs/scorebot-transport.md](docs/scorebot-transport.md) | 传输方案技术总结（页内 WebSocket，以及否掉的方案） |
| [docs/rich-message.md](docs/rich-message.md) | Telegram Rich Message 原生表格设计（已归档至分支 `archive/chrome-full`） |
| [docs/chrome-gateway.md](docs/chrome-gateway.md) | 方案评估（历史；现行传输见上一篇） |
| [docs/chrome-keeper-step1.md](docs/chrome-keeper-step1.md) | keeper 续 cookie 的设计记录 |
| [deploy/chrome-session/README.md](deploy/chrome-session/README.md) | VPS 常驻 Chrome + Xvfb（bot 只 attach `:9222`） |

## 安装

```bash
cd hltv-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

依赖：`curl_cffi`、`python-dotenv`、`pillow`、`weasyprint`、`pypdfium2`、`websocket-client`（CDP）。Telegram 仍用标准库 urllib。

## Cookie（从本机 Chrome / MCP）

细节见 [docs/cloudflare.md](docs/cloudflare.md)。VPS 上 keeper 会把 Chrome cookie 导出到 `data/session.json`。人手粘贴只在 keeper 挂了、或本机没有 Chrome 时用。HttpOnly 的 `cf_clearance`、`__cf_bm` **不能** `document.cookie`。DevTools → Network 点 `www.hltv.org`，复制 Cookie 整行：

```bash
cp data/session.example.json data/session.json
python3 -m hltv_bot import-cookie -o data/session.json
# 粘贴 Cookie: ... 然后 Ctrl-D
```

`data/session.json` 已 gitignore。`__cf_bm` 大约 30 分钟级，由 keeper 页自己续，不必按这个周期人手贴。

## GitHub Actions 部署

推到 `main` 会在 Actions 里 **checkout + rsync（SSH）** 到 **191.96.243.105:/opt/hltv-bot**，再 `uv sync` 并 **只** 重启 `hltv-bot`。VPS **不需要 git**。  
`.env` / `data/session.json` 已存在则不覆盖。Chrome keeper（`hltv-chrome.service`）不跟 bot 重启；bootstrap 见 [deploy/chrome-session/README.md](deploy/chrome-session/README.md)。

本机生成部署密钥并写入 GitHub Secret（**私钥不要进仓库**）：

```bash
ssh-keygen -t ed25519 -C "github-hltv-bot-deploy" -f ./hltv-bot-deploy -N ""
ssh-copy-id -i ./hltv-bot-deploy.pub -p 2233 root@191.96.243.105
gh secret set DEPLOY_SSH_KEY --repo woq/hltv-bot < ./hltv-bot-deploy
shred -u ./hltv-bot-deploy
# 公钥可留着：./hltv-bot-deploy.pub
```

Secret 名必须是 `DEPLOY_SSH_KEY`。VPS 上 `uv` 需在 `/root/.local/bin/uv`。

## 持久化（VPS + uv）

用 **systemd**，别用 tmux。

```bash
git clone https://github.com/woq/hltv-bot.git /opt/hltv-bot
cd /opt/hltv-bot
uv sync
cp .env.example .env          # 填 token
cp data/session.example.json data/session.json

# uv 路径：which uv
install -m 644 deploy/hltv-bot.service /etc/systemd/system/hltv-bot.service
# 若 uv 不在 /usr/local/bin/uv，改 unit 里 ExecStart
systemctl daemon-reload
systemctl enable --now hltv-bot
systemctl status hltv-bot
```

改代码后：`git pull && uv sync && systemctl restart hltv-bot`。

## Telegram

```bash
cp .env.example .env
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=   # 可选，限制群
python3 -m hltv_bot bot
```

### 命令分类速查

| 类别 | 命令 | 说明 |
|---|---|---|
| **赛程与赛事** | `/matches [t2/t3/all/text]` | 比赛列表。默认生成图片，加 `text` 发纯文本 |
| | `/events` | 近期 Major / T1 赛事列表与倒计时 |
| | `/reminder` | 立刻在当前会话生成赛事卡片预览（不计入定时提醒） |
| **实时比分与监控** | `/watch` | 开启本群比分监控（自动锁定至次日 10:00 比赛，开赛发卡片，变动更新，完结入低功耗） |
| | `/watch off` | 关闭本群多场比分监控 |
| | `/bump [比赛id]` | 将进行中的比分卡重新发送置顶到群聊最下方（旧卡自动删） |
| | `/stop` | 一键关闭本群全部比分、赛程与赛事提醒 |
| | `/follow [比赛id]` | 开启单场追踪（不带 id 开启本群，带 id 指定比赛） |
| | `/unfollow <比赛id>` | 取消单场比赛追踪 |
| | `/cover [赛事id]` | 批量开启整项赛事每个比赛日全部比赛追踪 |
| | `/uncover <赛事id>` | 关闭整项赛事追踪 |
| | `/ignore <比赛id>` | 屏蔽某场比赛的比分推送 |
| | `/unignore <比赛id>` | 恢复某场比赛的比分推送 |
| | `/track` / `/untrack` | 开启 / 关闭每日赛程日报与赛事倒计时 |
| **群组与配置** | `/allow` / `/deny` | 授权当前群 / 移出通知白名单 |
| | `/groups` | 查看已授权的通知群列表 |
| | `/stars [0-5]` | 默认比赛的最低星级门槛（默认 1） |
| | `/digest [上午点] [晚上点]` | 赛程日报推送钟点（默认 10 20，UTC+8） |
| | `/window [天数] [小时]` | 赛事提醒窗口（默认 7 6，开赛前 7 天至前 6 小时） |
| | `/silent [on/off]` | 通知静音开关（默认开，静音不打扰） |
| | `/cookie` | 在线热更新 Cloudflare Cookie |
| | `/status` | 查看 Bot 运行状态与心跳 |
| | `/hltv` | 显示用法分类完整指南 |

默认管理员 Telegram user id：`1442477170`（`.env` 里 `TELEGRAM_ADMIN_IDS`，逗号分隔可加多个）。

### 核心工作流与功耗机制

- **群组白名单与静音**：把 bot 拉进群后，用管理员账号发 `/allow`。开赛、比分、赛事提醒只发这些群，默认无声（`/silent off` 响铃）。
- **自然比赛日周期**：以每日 UTC+8 10:00 至次日 10:00 为一个完整比赛日，完美覆盖国外夜间打到凌晨的赛事。
- **比分监控与卡片**：比分看赛程总页（`/matches`），单次请求覆盖同时进行的 BO1/BO3/BO5。进入 LIVE 自动提速并发卡片；比赛中实时更新比分变动（Map winner / Match winner）；预期比赛全部打完后自动转入低功耗长休眠。
- **智能反爬与自适应上浮**：Live 期间高频采集，若遇到网络拥塞、Cloudflare 质询或频控拦截，系统自动阶梯上浮间隔并协同所有通知，安全恢复后自适应回落至高效速率。
- **消息自删与保留**：交互命令回复在 30 秒后自动删除（保持群聊整洁），提醒与比分消息永久留存。
- **权限安全**：管理与设置类命令只响应管理员。

## 建议跑在哪

启动时会调用 Telegram `setMyCommands`。若群里 bot 收不到命令，去 @BotFather → /setprivacy → Disable。

限流：`/matches`、`/events` 8 秒；列表缓存 45 秒；提醒大约每 90 秒看一次页面。

Bot 默认 `HLTV_LOG=DEBUG`。改成 INFO：`HLTV_LOG=INFO python3 -m hltv_bot bot`。

提交或 push 前跑 `AGENTS.md` 里那条 pytest。
