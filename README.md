# hltv-bot

HLTV 赛程/赛事提醒 + 赛程总页比分监控。时间 **UTC+8**。通知发到已授权群，默认无声。

默认 **headed Chrome + Xvfb**（`hltv-chrome`）续 cookie，`HLTV_HTTP=chrome` 在 keeper tab 里拉 HTML。`HLTV_HTTP=curl` 或 `HLTV_CDP_URL=off` 可退回。旧单场页内 Scorebot Rich 记分板在分支 `archive/chrome-full`（已冻结，勿整支合并）。

## 文档

| 文档 | |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 现行 `main` 架构速查 |
| [docs/hltv-api.md](docs/hltv-api.md) | 非官方 HLTV 接口：列表 HTML、详情 meta、Scorebot Engine.IO、事件字段 |
| [docs/scorebot-data.md](docs/scorebot-data.md) | Scorebot / snapshot / log 归一化数据结构（全面） |
| [docs/cloudflare.md](docs/cloudflare.md) | Cookie / Chrome keeper / curl 退路 |
| [docs/scorebot-transport.md](docs/scorebot-transport.md) | Scorebot 模块 / archive 页内 WS（`main` 比分跟赛程页） |
| [docs/browser-alternatives.md](docs/browser-alternatives.md) | 长期会话浏览器备选调研 |
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

推到 `main` 会在 Actions 里 **checkout + rsync（SSH）** 到 **<YOUR_VPS_IP>:/opt/hltv-bot**，再 `uv sync` 并 **只** 重启 `hltv-bot`。VPS **不需要 git**。  
`.env` / `data/session.json` 已存在则不覆盖。Chrome keeper（`hltv-chrome.service`）不跟 bot 重启；bootstrap 见 [deploy/chrome-session/README.md](deploy/chrome-session/README.md)。

本机生成部署密钥并写入 GitHub Secret（**私钥不要进仓库**）：

```bash
ssh-keygen -t ed25519 -C "github-hltv-bot-deploy" -f ./hltv-bot-deploy -N ""
ssh-copy-id -i ./hltv-bot-deploy.pub -p 2233 root@<YOUR_VPS_IP>
gh secret set DEPLOY_SSH_KEY --repo <username>/hltv-bot < ./hltv-bot-deploy
shred -u ./hltv-bot-deploy
# 公钥可留着：./hltv-bot-deploy.pub
```

Secret 名必须是 `DEPLOY_SSH_KEY`。VPS 上 `uv` 需在 `/root/.local/bin/uv`。

## 持久化（VPS + uv）

用 **systemd**，别用 tmux。

```bash
git clone https://github.com/<username>/hltv-bot.git /opt/hltv-bot
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

权限：已授权群成员 / 本群群管 / owner（`TELEGRAM_ADMIN_IDS`）。详见 `/hltv`。

| 类别 | 命令 | 说明 |
|---|---|---|
| **公开（已授权群）** | `/matches` `/events` `/bump` `/hltv` | 列表默认图片；`text` 纯文本；`/bump` 置顶比分卡 |
| **本群群管** | `/watch` `/watch off` `/stop` | 本群多场比分开/关；`/stop` **只关本群比分** |
| | `/follow` `/unfollow` | 本群单场通道（不带比赛 id） |
| | `/allow` `/deny` | 本群加入/移出通知白名单（远程 `-100…` 仅 owner） |
| **仅 owner** | `/reminder` `/track` `/untrack` | 赛事预览；全局赛程/赛事提醒 |
| | `/follow id` `/ignore` `/cover` … | 全局名单 |
| | `/stars` `/digest` `/window` `/silent` | 全局配置 |
| | `/cookie` `/status` `/groups` `/debug` | Cookie / 运维 |

owner Telegram user id 通过 `.env` 里 `TELEGRAM_ADMIN_IDS` 设置（逗号分隔）。

### 核心工作流与功耗机制

- **群组白名单与静音**：拉进群后由本群群管或 owner 发 `/allow`。开赛、比分、赛事提醒只发这些群，默认无声（owner `/silent off` 响铃）。
- **自然比赛日周期**：UTC+8 10:00 → 次日 10:00。
- **比分监控**：跟赛程总页 HTML（不是页内 Scorebot）。进入 LIVE 发卡并提速；Map/Match winner 等按列表变化推；打完后拉长间隔。
- **自适应反爬**：LIVE 高频；遇 CF/频控阶梯退避后回落。
- **消息**：`/matches` `/events` 等交互约 30s 自删；比分/提醒卡保留。
- **权限**：群管管本群开关；Cookie / 全局配置 / 名单仅 owner。

## 建议跑在哪

启动时会调用 Telegram `setMyCommands`。若群里 bot 收不到命令，去 @BotFather → /setprivacy → Disable。

限流：`/matches`、`/events` 8 秒；列表缓存 45 秒；提醒大约每 90 秒看一次页面。

Bot 默认 `HLTV_LOG=DEBUG`。改成 INFO：`HLTV_LOG=INFO python3 -m hltv_bot bot`。

提交或 push 前跑 `AGENTS.md` 里那条 pytest。
