# hltv-bot

HLTV 比赛列表 / 详情 / Scorebot 长连接（Game log）+ Telegram：`/matches` 普通消息（好复制）；`/watch` 用 Rich Message 原地 `edit`；刷下去时 `/bump` 再发一条。

TLS 按 MCP 里 Chrome 134 的头伪装（`curl_cffi` impersonate + 抄来的 `sec-ch-ua` / UA / cookie）。

## 文档

| 文档 | |
|---|---|
| [docs/rich-message.md](docs/rich-message.md) | Rich 只用在 `/watch`；`/matches` 等普通消息；官方它解决什么 |
| [docs/hltv-api.md](docs/hltv-api.md) | 非官方 HLTV 接口：列表 HTML、详情 meta、Scorebot Engine.IO、事件字段 |
| [docs/scorebot-data.md](docs/scorebot-data.md) | Scorebot / snapshot / log 归一化数据结构（全面） |
| [docs/cloudflare.md](docs/cloudflare.md) | Cookie / TLS 伪装、403 处理、试过的方案 |
| [docs/scorebot-transport.md](docs/scorebot-transport.md) | 为什么停在 poll；WS 403、Lightpanda、WebKit 实验结论 |
| [deploy/chrome-session/README.md](deploy/chrome-session/README.md) | VPS 常驻真 Chrome（备用，内存要求高） |

## 安装

```bash
cd hltv-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

只要：`curl_cffi`、`python-dotenv`（标准库 urllib 调 Telegram）。

## Cookie（从本机 Chrome / MCP）

细节见 [docs/cloudflare.md](docs/cloudflare.md)。HttpOnly 的 `cf_clearance`、`__cf_bm` **不能** `document.cookie`。DevTools → Network 点 `www.hltv.org` 或 `scorebot-lb.hltv.org`，复制 Cookie 整行：

```bash
cp data/session.example.json data/session.json
python3 -m hltv_bot import-cookie -o data/session.json
# 粘贴 Cookie: ... 然后 Ctrl-D
```

`data/session.json` 已 gitignore。失效后（约 `__cf_bm` 30 分钟级）再贴一次。

## GitHub Actions 部署

推到 `main` 会在 Actions 里 **checkout + rsync（SSH）** 到 **154.83.86.212:/opt/hltv-bot**，再 `uv sync` 并重启服务。VPS **不需要 git**。  
`.env` / `data/session.json` 已存在则不覆盖。

本机生成部署密钥并写入 GitHub Secret（**私钥不要进仓库**）：

```bash
ssh-keygen -t ed25519 -C "github-hltv-bot-deploy" -f ./hltv-bot-deploy -N ""
ssh-copy-id -i ./hltv-bot-deploy.pub root@154.83.86.212
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

| 命令 | |
|---|---|
| `/matches` | 今日比赛 |
| `/watch` | 本群观赛；已有场次发 `/watch` 加入 |
| `/bump` | 顶到最新 |
| `/stop` | 本群退出；`/stop all` 停全部 |
| `/allow` | 授权本群 |
| `/deny` | 取消授权 |
| `/groups` | 已授权群 |
| `/cookie` | 更新 Cookie |
| `/status` | 状态 |

默认管理员 Telegram user id：`1442477170`（`.env` 里 `TELEGRAM_ADMIN_IDS`，逗号分隔可加多个）。

把 bot 拉进私有群后，用该账号发 `/allow`。直播命令只在已授权群生效；`/allow` `/deny` `/groups` `/cookie` `/status` 仅管理员。

Watch **全局一场** Scorebot。默认**只给发了 `/watch` 的群**发卡片；其它群自己 `/watch`（可无 id）加入。新卡片只有该群手动 `/bump`。`/stop` 退出本群，`/stop all` 停全部。

普通回复和用户命令（**除 `/watch`**）30 秒后自动删，避免刷屏；观赛卡片一直留着。

## 建议跑在哪

启动时会调用 Telegram `setMyCommands`：群里是 matches/watch/bump/stop，私聊管理员额外有 allow/deny/groups/cookie/status。点输入框 `/` 就能看到。若群里 bot 收不到命令，去 @BotFather → /setprivacy → Disable。

限流：`/matches` 8s、`/watch` 6s、`/bump` 4s；live **edit 最少间隔 1.8s**（3K/ACE/Round over 立刻推）；HLTV 列表缓存 45s；Telegram 429 会按 `retry_after` 重试一次。

采集和 bot **跑在和 Chrome 同一出口 IP 的 PC** 上。手机只开 Telegram。MCP 只用来烤 cookie / 调试，不要当 24h 进程。

Bot 默认 `HLTV_LOG=DEBUG`，Scorebot / Telegram / HTTP 都会打到 stdout。改成 INFO：`HLTV_LOG=INFO python3 -m hltv_bot bot`。

提交或 push 前：`python3 -m pytest tests/test_rich_message.py tests/test_format.py tests/test_watch_flush.py tests/test_gaps.py -q`（见 [docs/rich-message.md](docs/rich-message.md)）。
