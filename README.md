# hltv-bot

HLTV 赛程和赛事页（`curl_cffi`）+ Telegram 提醒。时间 **UTC+8**。通知发到已授权群，默认无声。

完整 Chrome 记分板在分支 `archive/chrome-full`，主线不启动它。Cookie 仍用 `/cookie` 贴到 `data/session.json`。

## 文档

| 文档 | |
|---|---|
| [docs/rich-message.md](docs/rich-message.md) | Rich 只用在 `/watch`；`/matches` 等普通消息；官方它解决什么 |
| [docs/hltv-api.md](docs/hltv-api.md) | 非官方 HLTV 接口：列表 HTML、详情 meta、Scorebot Engine.IO、事件字段 |
| [docs/scorebot-data.md](docs/scorebot-data.md) | Scorebot / snapshot / log 归一化数据结构（全面） |
| [docs/cloudflare.md](docs/cloudflare.md) | Cookie / Chrome keeper / curl 退路 |
| [docs/scorebot-transport.md](docs/scorebot-transport.md) | 现行页内 WebSocket，以及否掉的 poll / Lightpanda / WebKit |
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

| 命令 | |
|---|---|
| `/matches` | 比赛列表。`t2` / `t3` / `all` 放宽筛选 |
| `/events` | Major / T1 赛事 |
| `/groups` | 通知群 |
| `/ignore 比赛id` | 这场不再推比分 |
| `/unignore 比赛id` | 恢复这场。不补发当前比分 |
| `/stop` | 暂停全部比分推送。赛事提醒还在 |
| `/watch` | 恢复比分推送 |
| `/allow` | 把本群加入通知 |
| `/deny` | 移出通知 |
| `/window 7 6` | 赛事提醒：开赛前 7 天，直到前 6 小时 |
| `/stars 1` | 比赛提醒最低星级 |
| `/silent` | 无声开关，默认开 |
| `/cookie` | 更新 Cookie |
| `/status` | 状态 |

默认管理员 Telegram user id：`1442477170`（`.env` 里 `TELEGRAM_ADMIN_IDS`，逗号分隔可加多个）。

把 bot 拉进群后，用管理员账号发 `/allow`。开赛、比分、赛事提醒只发这些群，默认无声。比赛要至少 1 星，并且赛事是 Major 或 T1。比分看赛程总页，每 3–5 秒一次，同时打的 BO1/BO3/BO5 都在这一页上。LIVE 只是直播位；还没在比赛页 live log 里看到 start 之前，才会抽空打开那场页面，看到之后就不再进。赛事页只在启动时拉一次，之后按固定开赛时间本地提醒。一方比分连续单边上涨满 5 分，消息里会多一行标记。`/ignore`、`/stop`、`/watch` 和其它管理命令只给管理员。

命令回复 30 秒后自动删。提醒消息留着。

## 建议跑在哪

启动时会调用 Telegram `setMyCommands`。若群里 bot 收不到命令，去 @BotFather → /setprivacy → Disable。

限流：`/matches`、`/events` 8 秒；列表缓存 45 秒；提醒大约每 90 秒看一次页面。

Bot 默认 `HLTV_LOG=DEBUG`。改成 INFO：`HLTV_LOG=INFO python3 -m hltv_bot bot`。

提交或 push 前跑 `AGENTS.md` 里那条 pytest。
