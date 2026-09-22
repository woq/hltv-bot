# Chrome 过 CF 网关：方案评估（2026-09）

> **这是落地前的评估，不是现行说明。** 下面写的「还没改代码」「先做 xhr-poll」「掉线回 poll」「页内先 polling 再带 sid 升级」都没有按原文上线。  
> 现行：`hltv-chrome` keeper 续 cookie；比赛页直接 `transport=websocket`（无 sid、不发 `2probe`）；Python 收 CDP 事件。curl 只在 CDP 不可用时握手再 Upgrade，不收 xhr 事件。见 [scorebot-transport.md](scorebot-transport.md)。

第三方建议把 Chrome 从「人手烤 cookie」改成「常驻过 CF 的网关」，Python 只收 JSON，不再自己 `Upgrade`。

根因与 [scorebot-transport.md](scorebot-transport.md) 一致：`curl_cffi` 抄 cookie 能 poll，WS Upgrade 被 CF 验「是不是刚才过完 JS 的那个真进程」。解法只有让 Engine.IO WS 跑在已经过 CF 的 page 里。

本页只记评估和落地顺序，**还没改代码**。现成 unit 仍在 `deploy/chrome-session/`。

## 约束（这台机）

- VPS 2G RAM，无 GPU，当时 `used ~208M` / Swap 0（应加 1G swapfile，`swappiness=10`）
- bot `MemoryMax=400M`；全局只 watch **一场**
- 成功标准：A 自动续 cookie 保 poll → B 真 WS → C 常驻内存适合 2G
- 第一次可人手 VNC；不能每 30 分钟点一次
- 已否：curl/urllib、每次 headless、无头+profile、Lightpanda、WPE、RFC 8441、Playwright 每次 launch

## 方案对照

| 方案 | 原理 | 内存（不含系统 ~208M） | 裁决 |
|---|---|---|---|
| **A 真 Chrome + Xvfb + 页内 WS** | keeper tab 保 clearance；match tab 里 `fetch` + `new WebSocket`；CDP 把 scoreboard/log 吐给 Python | Chrome 550–900M 目标；峰值开 tab +150M，靠 swap | **唯一全满足 A+B+C。采用。分两步落地。** |
| B MV3 extension 后台 WS | keeper 仍在；比赛 WS 放到 extension background，少开 match tab | 纸面 400–550M | **不当终态。** 后台 `WebSocket` 的 Origin 是 `chrome-extension://`，不是 `https://www.hltv.org`，很像现在的抄 cookie Upgrade。MV3 service worker 还会被杀。content script 打进 hltv.org 页 = 又回到 A，省不了 renderer。 |
| C 异地 Chrome，HK 只跑 Python | 远程机跑 A，本机收 JSON 或拉 `session.json` | HK ~150M | 只拉 cookie → 只有 A。真 WS 必须远端页内连、再中继 JSON，不是把 `wss` 拉回 HK 再 Upgrade。多一台运维，Kill 多 300–800ms。2G 实在扛不住 Chrome 再考虑。 |
| D FlareSolverr | 现成 Chrome+Xvfb 保 cookie；`/scorebot` 要二开 | 比手写 A 多一层 wrapper | 只做 cookie 不如直接用 `deploy/chrome-session/`。要 WS 等于重写 A。 |
| E Firefox / Camoufox headed | 同 A，换 Gecko | 纸面省 ~100M | CF 对 Firefox 更凶；BiDi 不如 CDP。不值。 |
| F 付费抓取 API | 列表走云，Kill 仍本地 | 本地 150M | Scorebot 无公开 log API。否。 |
| G 打码平台解 Turnstile | 买 token 续 clearance | 本地 150M | 只帮首次过验证，救不了 Upgrade 绑真进程。可当 A 的插件，不能独立。 |

排序（要真 WS）：**A ≫ C（远程版 A）> E**。B 从名单拿掉，除非能证明 extension 发出的 WS `Origin` 仍是 `https://www.hltv.org`（那就不是「后台 WS」）。

无 GPU：Turnstile 主要靠真 Chrome 的 JS 运行时，不靠独显。但 **WPE 是卡在 canvas/EGL 上的**，所以软件光栅不能关死。

## 采纳的架构（A，两步）

1. **keeper 保 poll（先做）**  
   常驻 1 个 headed Chrome + Xvfb，只开 keeper tab 挂 `https://www.hltv.org/matches`。CDP `Network.getAllCookies` 写 `data/session.json`（或 `HLTV_SESSION`）。Python 继续现在的 `iter_scorebot` xhr-polling。人手 VNC 只第一次。

2. **页内 WS 中继（keeper 稳定后再做）**  
   每场 **一个** match tab（全局一场，不要 1–2 个）。页内：polling 握手拿 `sid` → `new WebSocket("wss://scorebot-lb.hltv.org/socket.io/?EIO=3&transport=websocket&sid=...")` → `2probe`/`40`/`42["readyForMatch",…]`，心跳 `2`/`3` 页内回。Python **只 attach CDP，不 launch**。事件用 `Runtime.addBinding` 或 `POST http://127.0.0.1:8765/ingest` 吐 `scoreboard`/`log`，接上现有 `iter_scorebot` 的 yield 形状。Telegram 不动。WS 掉了回 poll。

## 运维：听 / 改 / 已有

**听**

- Chrome **不要** `Restart=always`。现有 `deploy/chrome-session/hltv-chrome.service` 是 `Restart=always`，重启即掉 clearance。改成 `on-failure` + 限次数，或手动。
- 健康检查：标题含 `Just a moment`、cookie 没了 `cf_clearance`、页内 WS 连续失败 → CDP 截图告警 Telegram，**等人手 VNC，不要自动重启 Chrome**。
- 首次 VNC：x11vnc + websockify 只绑 localhost，SSH 隧道，过完关掉。现有 `x11vnc@.service` 已是 `-localhost`。
- systemd 拆：`xvfb` → `chrome`（`MemoryMax` 约 900M）→ `hltv-bot`。中继可单独 `hltv-bridge`（挂了可重启，不动 Chrome）。部署现在每次 push 都 `systemctl restart hltv-bot`，所以 Chrome 绝不能跟 bot 一个 unit。
- Chrome 默认拒绝 uid 0。这台专用 VPS 是 root 环境，unit 用 `--no-sandbox --disable-setuid-sandbox` 以 root 跑 headed Chrome（不要再加 `hltv` 用户）。

**改（第三方原文有坑）**

- **不要**同时加 `--disable-gpu` 和 `--disable-software-rasterizer`。现有 flags 只有 `--disable-gpu`。两个都关可能没 canvas，重复 WPE 的死法。软件光栅先留着，测过 Turnstile 再考虑关。
- **不要** keeper 每 20 分钟 `reload`。本机 Chrome 是靠页里持续打 `/cdn-cgi/challenge-platform/` 续 `__cf_bm` 的；reload 更容易重新出挑战。idle tab + 定时导出 cookie。
- `session.json` **不必**搬到 `/var/lib/hltv-bot/`。rsync 已 exclude `data/session.json`；bot 已读 `HLTV_SESSION`。profile 在 `/var/lib/hltv-chrome`，不在 rsync 源里，不必再 exclude。
- Xvfb `800x600x16` 可以试，现成是 `1920x1080x24`。先小分辨率，Turnstile 画不出再加大。
- `--renderer-process-limit=2` 与「1 keeper + 1 match」匹配；全局一场够用。
- 内存账 550–700M 当 **目标** 不是保证。先只跑 keeper，用 `smem` / `systemd-cgtop` 量，再决定要不要上 match tab。

**已有、别重复造**

- `deploy/chrome-session/`：Chrome + Xvfb + x11vnc + noVNC
- rsync exclude：`.env`、`data/session.json`、`data/chats.json`、`data/settings.json`
- `HLTV_SESSION`、`/cookie`、poll 5xx 底栏、WS 403 熔断改 poll

## 验收

- `curl -s 127.0.0.1:9222/json` 有 tab；cookie 有 `cf_clearance`
- 步 1：停人手 `/cookie` 后 poll 仍能出 Kill
- 步 2：页内 WS 101；卡片底栏 `ws`；Kill 延迟 <3s；掉线回 poll
- Chrome RSS 目标 <700M；整机 used <1.6G（含 1G swap 峰值）

## 不写的代码

不要按「B 终态」出 extension 包。下一步若动手，只做步 1：swap + 收紧现有 chrome-session flags + CDP 导出 cookie 覆盖 `data/session.json` + Chrome 禁止乱动重启。
