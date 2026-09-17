# Agent notes

## Telegram 输出

分流，不要把所有出站都做成 Rich。细则：`docs/rich-message.md`。

- **`/watch` / `/bump`**：Rich Message。全局只 watch 一场。卡片只发给发过 `/watch` 的群（已有场次本群 `/watch` 加入）；不要默认广播所有授权群。新卡片只有该群 `/bump`。`/stop` 退本群并删除该群观赛卡片，`/stop all` 停全部并删掉所有观赛卡片。换比赛不要删旧卡片，原地 edit。
- **`/matches` 和其余通知**：`/matches` 默认渲染深色图片（`sendPhoto`，支持 `T1`/`T2`/`T3` 评级筛选，附快捷 `/watch` 命令）并支持 `text` 纯文本回退；其余通知普通 `sendMessage` + HTML。好复制，**不用**按 Rich 规范检查。30s 后自动删（用户命令也删；若群组未授予 Bot 删消息管理员权限则跳过，**`/watch` 命令和观赛卡片不删**）。
- 记分板：折叠战绩（回合史 + 名单）在最上 → 比分表 → log 表 → 最下一行链接状态。不要 h3/ul/footer 文章壳。log 文案全英语。
- 拿不到数据时同一条 watch 卡片改成 DEBUG 痕迹；恢复后再 edit 回记分板。

## 提交 / push 前

```bash
python3 -m pytest tests/test_rich_message.py tests/test_format.py tests/test_watch_flush.py tests/test_gaps.py tests/test_cdp_cookies.py tests/test_cdp_client.py tests/test_keeper.py tests/test_scorebot_cookie_refresh.py tests/test_cookie_cmd.py tests/test_http_chrome.py tests/test_scorebot_chrome.py -q
```

不要用「源码里禁止 sendMessage」这种检查。`test_gaps.py` 核对出站间隔有没有漏（HTML 3s、poll、握手退避、WS 重试、Telegram edit / 429 / getUpdates）。

## 其它文档

- `docs/hltv-api.md` — HLTV 非官方接口
- `docs/scorebot-data.md` — Scorebot / snapshot / 归一化 log 字段
- `docs/cloudflare.md` — Cookie / TLS
- `docs/scorebot-transport.md` — 传输层试过什么、为什么停在 poll
- `docs/chrome-gateway.md` — 常驻 Chrome 过 CF 网关：方案评估与落地顺序
- `docs/chrome-keeper-step1.md` — Step 1 实现设计（keeper 保 poll；三 PR）
