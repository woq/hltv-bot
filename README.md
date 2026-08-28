# hltv-bot

HLTV **比赛列表 / 详情 / Scorebot 长连接（Game log）** + Telegram：先发一条消息再 `editMessageText`；讨论把消息刷下去时用 `/bump` 再发一条新的继续 edit。

TLS 按 MCP 里 Chrome 134 的头伪装（`curl_cffi` impersonate + 抄来的 `sec-ch-ua` / UA / cookie）。

## 安装

```bash
cd hltv-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

只要：`curl_cffi`、`python-dotenv`（标准库 urllib 调 Telegram）。

## Cookie（从本机 Chrome / MCP）

HttpOnly 的 `cf_clearance`、`__cf_bm` **不能** `document.cookie`。在 DevTools → Network 点一条 `scorebot-lb.hltv.org` 或 `www.hltv.org` 请求，复制 **Cookie** 整行：

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
| `/matches` | 按赛事分组，组内按 HLTV 星级排序；LIVE 标 🔴；HTML 富文本，每条 `/watch id` |
| `/watch <id>` | 发一条 LIVE 消息并持续 edit |
| `/bump` | **新发一条**，之后 edit 新消息 |
| `/stop` | 停 |
| `/status` | impersonate / cookie 名 |
| `/cookie` | 下一条消息贴 Cookie 头（仅管理员） |
| `/allow` | 管理员：把**当前群**加入推送名单 |
| `/deny` | 管理员：去掉当前群或 `/deny chat_id` |
| `/groups` | 管理员：列出已授权群 |

默认管理员 Telegram user id：`1442477170`（`.env` 里 `TELEGRAM_ADMIN_IDS`，逗号分隔可加多个）。

把 bot 拉进私有群后，用该账号发 `/allow`。直播命令只在已授权群生效；`/allow` `/deny` `/groups` `/cookie` `/status` 仅管理员。

`HLTV_BUMP_SECONDS=300` 可定时自动 bump（默认 0，只手动 `/bump`）。

## 建议跑在哪

采集和 bot **跑在和 Chrome 同一出口 IP 的 PC** 上。手机只开 Telegram。MCP 只用来烤 cookie / 调试，不要当 24h 进程。
