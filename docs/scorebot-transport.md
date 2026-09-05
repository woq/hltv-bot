# Scorebot 传输：试过什么、为什么停在 poll

HLTV 没有公开 Game log API。浏览器里是 Engine.IO v3：polling 握手拿 `sid`，再升 WebSocket，`readyForMatch` 之后收 `scoreboard` / `log`。

**线上现状（2026-08）：`curl_cffi` + 烤 cookie，事件走 xhr-polling。** WS Upgrade 经常 403。卡片底栏 `poll`。502/520 是源站抖动，底栏带 notice，有新分就不切 DEBUG。

下面按时间记结论，避免再走回头路。

---

## 1. 现在为什么 poll 能看、WS 经常不能

MCP 对着本机 Chrome 134 抓过一场 live：

- 列表 / 详情 / scorebot **HTTP/2 xhr-polling** 头齐（`sec-ch-ua`、Origin、Cookie）。
- 同一页一直跑 `www.hltv.org/cdn-cgi/challenge-platform/...`，`cf_clearance` / `__cf_bm` 会自己转。
- Cookie 集合：`io`、`_cfuvid`、`__cflb`、`cf_clearance`、`__cf_bm`、Optanon。
- `t=` 是 Engine.IO **yeast**，不是 unix 毫秒。
- `accept-encoding` 含 **zstd**。

`curl_cffi` 能把 **HTTP poll** 对齐到能握手、能出 Kill。  
WS 是另一条：**新 TCP + HTTP/1.1 `Connection: Upgrade`**。Cloudflare 对这类额外看「是不是刚过完 JS 的真 Chrome 进程」。烤出来的 cookie + 同 IP **过得了 basic HTTP，过不了 Upgrade** 是常态，不是漏了两个头。

对照实验：

| 信号 | 含义 |
|---|---|
| 握手 200、Kill 在更新、`Refused WebSocket upgrade: 403` | cookie 够 poll，WS 被 CF 拒 |
| `poll HTTP 520/502` | 边缘到源站抖，不是鉴权；等 30s |
| 卡片 DEBUG 里全是 `ct=1 t=2` / `feed 80->80` | 曾经误把 5xx 当断线；`80` 是 log 上限 |

部署 **不会** 自动刷新 cookie：rsync 排除 `data/session.json`。VPS 也没有会过 challenge 的 Chrome。

---

## 2. 协议层做过的对齐（保留）

这些对 poll 有用，WS 偶尔能在「完整 Chrome 烤的 clearance + 同 IP」下 `2probe→3probe`：

- `t=` 改 yeast（`hltv_bot/eio.py`）。
- HTTP `accept-encoding` 加 zstd。
- Cookie 顺序：`io` → `_cfuvid` → `__cflb` → `cf_clearance` → `__cf_bm`。
- **不要** 在 WS 上声明 `permessage-deflate`，也 **不要** 带 `Accept-Encoding`：`curl_cffi` 会 101 成功然后 `WS_RECV` 空包（curl 52）。
- 两种 `default_headers` 之间隔 1s；第一次就是 403 不再打第二次。

本机完整 cookie 时曾经 `PROBE_OK` 并收到 `42["log",…]`。VPS 上常见 cookie 只剩 `io,__cf_bm,__cflb`（没有 clearance），Upgrade 仍 403。不要把那一次成功理解成「Python 已经稳定过 CF WS」。

---

## 3. 否掉的方案

### Lightpanda

HTTP 和页面里的 WebSocket **都是 libcurl**。UA 禁止含 `Mozilla`，`Sec-Ch-Ua` 写死 Lightpanda。没有 TLS impersonate。对 WS 403 **没有提升，指纹还更差**。

### 真 Chrome 常驻（`deploy/chrome-session/`）

在已验证的 page 里连 scorebot，这是唯一稳的真 WS。大约 **1GB+** RAM。当前 bot `MemoryMax=400M`、机器无 Swap，没上。

### WebKitGTK / WPE + Content Blocker（已放弃）

想法：同一套 Safari JSON 过滤广告，页面里 `fetch` + `WebSocket` 用浏览器 TLS。

做过：

- `wpe_filter.json` 拦 Allstar/Stripe/GTM，放行 hltv / scorebot / cloudflare。
- 系统 Python + `gir1.2-webkit2-4.1`，`DISPLAY=:0`（不必 `xvfb@99`，那是未安装的 unit 模板）。
- 过滤规则不能用 `|`，WebKit 报 `Disjunctions are not supported`。
- 脚本打进 **ALL_FRAMES** 会进 Turnstile iframe（`about:blank` / `challenges.cloudflare.com`），点验证不跳转。改成只注入顶层后，空白 iframe 没了。
- 关掉 ITP、sandbox，UA 写成 Chrome 134，试 llvmpipe。

仍失败：

```
MESA: ZINK failed to choose pdev
egl: failed to create dri2 screen
title=Just a moment... cf=True
```

顶层卡在 Cloudflare 自动页，canvas/WebGL 没有 GPU，验证码算不出来就刷新。**不是点得不够。** 代码已全部撤掉，不留 `HLTV_WPE`。

### RFC 8441 (HTTP/2 WebSockets / Extended CONNECT)（实测不可行）

想法：既然 HTTP/2 poll 是通的，能否不降级到 HTTP/1.1 Upgrade，直接在 HTTP/2 上走 RFC 8441 打开 WebSocket。

实测结论：
1. **`curl_cffi` 库层限制**：`ws_connect(..., http_version=CurlHttpVersion.V2_0)` 时，`curl_cffi` / 底层 `libcurl-ws` 遇到 ws/wss scheme，在 TLS ALPN 阶段仍强制只 offer `http/1.1`（`ALPN: curl offers http/1.1`），不会向服务端协商 `h2`。
2. **服务端 / 协议层限制**：即使 ALPN 能协商到 H2，RFC 8441 需要服务端在 HTTP/2 SETTINGS 帧中显式声明 `SETTINGS_ENABLE_CONNECT_PROTOCOL = 1`。目前 Cloudflare 边缘节点对普通站点与 HLTV Scorebot 默认不启用该扩展能力，仍强制要求通过 HTTP/1.1 `Connection: Upgrade`。因此此路不通。

---

## 4. 现在怎么跑

- `/watch`：`iter_scorebot` → poll，WS 每 30s 再试，403 就继续 poll。
- 瞬时 poll 5xx：底栏 `poll HTTP 502 · next …`，有记分板不切 DEBUG。
- WS 连续失败：管理员私聊汇总（满 2 次、每 5 分钟一批）。
- Cookie：同出口 Chrome 烤整行，`/cookie`。过期再贴。
- 提交前：`pytest tests/test_rich_message.py tests/test_format.py tests/test_watch_flush.py tests/test_gaps.py -q`。

以后若要真 WS：给机器加内存，跑 `deploy/chrome-session/`，在**已打开的比赛页**里连，不要再抄 cookie 去 Upgrade，也不要再试 Lightpanda / WebKitGTK。

