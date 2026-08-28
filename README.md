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

## Telegram

```bash
cp .env.example .env
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=   # 可选，限制群
python3 -m hltv_bot bot
```

| 命令 | |
|---|---|
| `/matches` | 列表 |
| `/watch <id>` | 发一条 LIVE 消息并持续 edit |
| `/bump` | **新发一条**，之后 edit 新消息 |
| `/stop` | 停 |
| `/status` | impersonate / cookie 名 |
| `/cookie` | 下一条消息贴 Cookie 头，写入 session 并尽量删除原消息 |

`HLTV_BUMP_SECONDS=300` 可定时自动 bump（默认 0，只手动 `/bump`）。

## 建议跑在哪

采集和 bot **跑在和 Chrome 同一出口 IP 的 PC** 上。手机只开 Telegram。MCP 只用来烤 cookie / 调试，不要当 24h 进程。
