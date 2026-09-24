# Agent notes

## 主线

主线是 API 提醒，不启动完整 Chrome。完整 Chrome / 页内记分板在分支 `archive/chrome-full`。

- 抓取默认 `HLTV_HTTP=curl`（`curl_cffi` + `data/session.json`）。不要在 `run()` 里启动 keeper，也不要 `systemctl start hltv-chrome`。
- 通知只发 `data/chats.json` 里的群，默认 `disable_notification`（`/silent off` 才响）。
- 时间一律 **UTC+8**。
- 比赛：星级达到 `/stars`（默认 1）**并且**赛事名是 Major/T1。开赛前 15 分钟一条。比分只跟赛程总页，一份请求覆盖同时进行的 BO1/BO3/BO5，间隔 3–5 秒。总页 LIVE 不发「已开赛」。真正开打才进比赛页看 live log 的 `start`，而且只在还没看到 start 时、每隔一次总页请求才打开一场；看到 start 后整场 BO 都不再进比赛页。比分单边连加到 ≥5 时加一行 `⚡`。从列表消失时结束一条。`/ignore id` 丢掉一场，`/stop` 暂停全部比分推送，`/watch` 恢复且不补发。进程起来后的第一次成功轮询只记账。
- 赛事：只要 Major / T1。启动时拉一次赛事页，开赛时间之后本地计时，不再请求赛事页。窗口是开赛前 N 天到前 N 小时（`/window`，默认 7 天 → 6 小时），阶段是「进入窗口 / 剩 1 天 / 到达 N 小时」。
- `/matches`、`/events` 默认发图片卡片（带 `text`/`txt` 发纯文本），30 秒后删。没有 `/watch` 卡片。

## 提交 / push 前

```bash
python3 -m pytest tests/test_rich_message.py tests/test_format.py tests/test_watch_flush.py tests/test_watch_feed.py tests/test_live.py tests/test_snapshot.py tests/test_gaps.py tests/test_cdp_cookies.py tests/test_cdp_client.py tests/test_keeper.py tests/test_scorebot_cookie_refresh.py tests/test_cookie_cmd.py tests/test_http_chrome.py tests/test_scorebot_chrome.py -q
```

不要用「源码里禁止 sendMessage」这种检查。`test_gaps.py` 核对出站间隔有没有漏（HTML 3s、poll、握手退避、WS 重试、Telegram edit / 429 / getUpdates）。

## 部署与服务器

- **主部署服务器**：`191.96.243.105`（通过系统 proxy 连接 / SSH `root@191.96.243.105`）。
- 代码 push 到 GitHub `main` 分支后会自动部署到该服务器。

## 其它文档

- `docs/hltv-api.md` — HLTV 非官方接口
- `docs/scorebot-data.md` — Scorebot / snapshot / 归一化 log 字段
- `docs/cloudflare.md` — Cookie / TLS
- `docs/scorebot-transport.md` — 现行传输：页内 WebSocket；curl 只作退路，不回落 xhr
- `docs/chrome-gateway.md` — 常驻 Chrome 方案评估（历史；落地结果以 transport 文档为准）
- `docs/chrome-keeper-step1.md` — Step 1 设计记录（keeper 续 cookie；页内 WS 已另落地）

