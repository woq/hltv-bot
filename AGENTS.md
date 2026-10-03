# Agent notes

## 主线

主线是 API 提醒，不启动完整 Chrome。完整 Chrome / 页内记分板在分支 `archive/chrome-full`。

- 抓取默认 `HLTV_HTTP=curl`（`curl_cffi` + `data/session.json`）。不要在 `run()` 里启动 keeper，也不要 `systemctl start hltv-chrome`。
- 通知只发 `data/chats.json` 里的群，默认 `disable_notification`（`/silent off` 才响）。
- 时间一律 **UTC+8**。
- 比赛与比分监控（`/watch`）：
  - 范围与星级：星级达到 `/stars`（默认 1）**并且** 赛事名是 Major/T1，或通过 `/follow`、`/cover` 特别关注。
  - 自然比赛日：以每日 UTC+8 10:00 至次日 10:00 为一个比赛日周期，涵盖国外跨午夜全部赛事。
  - 开赛与更新流转：开赛前 15 分钟一条预告。比分只跟赛程总页，一份请求覆盖同时进行的 BO1/BO3/BO5，开赛（进入 LIVE）即发记分卡片并提速追踪，实时更新比分变动（Map winner / Match winner）。从列表消失时终局结算一条。
  - 低功耗与自适应反爬：预期内比赛全部打完后自动转入低功耗休眠模式；LIVE 期间高频采集，若遇到网络拥塞、Cloudflare 质询或频控拦截，系统自动阶梯上浮间隔并协同所有通知，安全恢复后自适应回落至高效速率。
  - 控制指令：`/watch` 打开并输出至次日 10:00 预期比赛汇总（进程启动后首次成功轮询只记账），`/watch off` 关闭，`/ignore id` 丢掉一场，`/stop` 关闭全部比分、赛程和赛事提醒。
- 赛事：只要 Major / T1。窗口是开赛前 N 天到前 N 小时（`/window`，默认 7 天 → 6 小时）。窗口里每天 UTC+8 09:00 和 18:00 各推一次。第一次记下钟点时只发给管理员。之后错过的最近两档补发到通知群。赛事开启时轮询最长 1 小时。`/reminder` 把当前赛事卡发到本对话，不记账。说明只留赛事名、倒计时和链接。
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

