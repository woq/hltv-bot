# Agent notes

## 主线

主线在 `main`：赛程/赛事提醒 + 赛程总页比分监控。常驻 **headed Chrome + Xvfb**（`hltv-chrome`）续 cookie；bot `run()` 里起 keeper 线程（只 attach `:9222`）。**不要** `--headless`，**不要** deploy 时 `systemctl start/restart hltv-chrome`。

分支 `archive/chrome-full` 是旧产品面（单场页内 Scorebot Rich 记分板），已落后 `main`，**不要整支合并回来**。Scorebot 模块仍留在树里作退路/对照。

- 抓取默认 `HLTV_HTTP=chrome`（keeper tab 内 `fetch`）。`HLTV_HTTP=curl` 才改 `curl_cffi` + `data/session.json`。关 keeper：`HLTV_CDP_URL=off`。
- 通知只发 `data/chats.json` 里的群，默认 `disable_notification`（`/silent off` 才响）。
- 权限：本群 Telegram 群管可 `/watch` `/stop` `/follow`（本群开关）`/allow`（本群）等；已授权群成员可 `/bump`；**仅** `TELEGRAM_ADMIN_IDS`（owner）可 `/cookie` `/silent` `/stars` `/track` `/ignore` 及全局名单、远程 `/allow -100…`。
- 时间一律 **UTC+8**。
- 比赛与比分监控（`/watch`）：
  - 范围与星级：星级达到 `/stars`（默认 1）**并且** 赛事名是 Major/T1，或通过 owner `/follow id`、`/cover` 特别关注。
  - 自然比赛日：以每日 UTC+8 10:00 至次日 10:00 为一个比赛日周期（`digest_morning` 默认 10），涵盖国外跨午夜全部赛事。
  - 开赛与更新流转：比分**只跟赛程总页** HTML（一份请求覆盖同时 LIVE 的 BO1/BO3/BO5），**不**走页内 Scorebot。进入 LIVE 发预告/记分卡并提速；之后 Map winner / Match winner / 半场等按列表变化推送；从列表消失时终局结算。开赛前约 45 分钟起加快轮询；**没有**单独的「开赛前 15 分钟」推送。
  - 低功耗与自适应反爬：无 LIVE 且无临近铃时拉长间隔（赛事提醒开着时轮询最长约 1 小时，否则可到约 6 小时）；LIVE 期间 3–5s；遇网络/CF/频控阶梯退避，恢复后回落。
  - 控制指令：`/watch` 打开本群多场并输出至次日 10:00 赛程摘要（进程首次成功轮询只记账不刷屏），`/watch off` 关本群多场，`/stop` **只关本群比分**（全局赛程/赛事提醒用 owner `/untrack`），`/ignore id`（owner）丢掉一场。
- 赛事：只要 Major / T1。窗口是开赛前 N 天到前 N 小时（`/window`，默认 7 天 → 6 小时）。窗口里每天 UTC+8 09:00 和 18:00 各推一次。第一次记下钟点时只发给管理员。之后错过的最近两档补发到通知群。`/reminder`（owner）把当前赛事卡发到本对话，不记账。
- `/matches`、`/events` 默认发图片卡片（带 `text`/`txt` 发纯文本），30 秒后删。`/watch` 本身是文字摘要，不是图片卡。

## 提交 / push 前

```bash
python3 -m pytest tests/test_rich_message.py tests/test_format.py tests/test_watch_flush.py tests/test_watch_feed.py tests/test_live.py tests/test_snapshot.py tests/test_gaps.py tests/test_cdp_cookies.py tests/test_cdp_client.py tests/test_keeper.py tests/test_scorebot_cookie_refresh.py tests/test_cookie_cmd.py tests/test_http_chrome.py tests/test_scorebot_chrome.py tests/test_cmd_perms.py tests/test_reminders.py tests/test_chats.py -q
```

不要用「源码里禁止 sendMessage」这种检查。`test_gaps.py` 核对出站间隔有没有漏（HTML 3s、poll、握手退避、WS 重试、Telegram edit / 429 / getUpdates）。

## 部署与服务器

- **主部署服务器**：`191.96.243.105`（SSH `hytron`，port 2233）。
- 代码 push 到 GitHub `main` 分支后会自动部署到该服务器（只 `restart hltv-bot`，不动 Chrome）。

## 其它文档

- `docs/architecture.md` — 现行架构速查（`main`）
- `docs/hltv-api.md` — HLTV 非官方接口
- `docs/scorebot-data.md` — Scorebot 字段（模块 / archive）
- `docs/cloudflare.md` — Cookie / TLS / keeper
- `docs/scorebot-transport.md` — Scorebot 传输（非 main `/watch`）
- `docs/chrome-gateway.md` — 常驻 Chrome 方案评估（历史）
- `docs/chrome-keeper-step1.md` — keeper 设计记录
- `docs/browser-alternatives.md` — 长期会话浏览器备选
- `deploy/chrome-session/README.md` — VPS headed Chrome + Xvfb + noVNC

