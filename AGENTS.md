# Agent notes

## Telegram 输出

分流，不要把所有出站都做成 Rich。细则：`docs/rich-message.md`。

- **`/watch` / `/bump`**：Rich Message。全局只 watch 一场。卡片只发给发过 `/watch` 的群（已有场次本群 `/watch` 加入）；不要默认广播所有授权群。新卡片只有该群 `/bump`。`/stop` 退本群并删除该群观赛卡片，`/stop all` 停全部并删掉所有观赛卡片。换比赛不要删旧卡片，原地 edit。
- **`/matches` 和其余通知**：`/matches` 默认渲染深色图片（`sendPhoto`，支持 `T1`/`T2`/`T3` 评级筛选，附快捷 `/watch` 命令）并支持 `text` 纯文本回退；其余通知普通 `sendMessage` + HTML。好复制，**不用**按 Rich 规范检查。30s 后自动删（用户命令也删；若群组未授予 Bot 删消息管理员权限则跳过，**`/watch` 命令和观赛卡片不删**）。
- 记分板为**单条** Rich：比分表 + 回合史 + 名单简表 + log + 链接状态整合在同一条消息内。不要 h3/ul/footer 文章壳。log 文案全英语。最小编辑间隔 1.5s，并受每分钟最多 20 次的滑动窗口限流保护，超出时合并（coalesce）延迟更新，彻底避免 429。
- 拿不到数据时改成 DEBUG 痕迹；恢复后再 edit 回记分板。有过比分后链路断开则结算（LIVE→SCORE），不拆卡片。

## 提交 / push 前

```bash
python3 -m pytest tests/test_rich_message.py tests/test_format.py tests/test_watch_flush.py tests/test_gaps.py tests/test_cdp_cookies.py tests/test_cdp_client.py tests/test_keeper.py tests/test_scorebot_cookie_refresh.py tests/test_cookie_cmd.py tests/test_http_chrome.py tests/test_scorebot_chrome.py -q
```

不要用「源码里禁止 sendMessage」这种检查。`test_gaps.py` 核对出站间隔有没有漏（HTML 3s、poll、握手退避、WS 重试、Telegram edit / 429 / getUpdates）。

## 部署与服务器

- **主部署服务器**：`191.96.243.105`（通过系统 proxy 连接 / SSH `root@191.96.243.105`）。
- 代码 push 到 GitHub `main` 分支后会自动部署到该服务器。

## 其它文档

- `docs/hltv-api.md` — HLTV 非官方接口
- `docs/scorebot-data.md` — Scorebot / snapshot / 归一化 log 字段
- `docs/cloudflare.md` — Cookie / TLS
- `docs/scorebot-transport.md` — 传输层试过什么、为什么停在 poll
- `docs/chrome-gateway.md` — 常驻 Chrome 过 CF 网关：方案评估与落地顺序
- `docs/chrome-keeper-step1.md` — Step 1 实现设计（keeper 保 poll；三 PR）

