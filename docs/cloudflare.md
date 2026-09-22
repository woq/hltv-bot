# Cloudflare 过验证

HLTV 列表页、详情页、Scorebot 都在 Cloudflare 后面。当前做法：

1. VPS 常驻 headed Chrome + Xvfb（`hltv-chrome`），keeper tab 挂在 `www.hltv.org`。idle 页自己续 `__cf_bm`，CDP 导出到 `data/session.json`。
2. `/matches`、详情 HTML 默认在这个 tab 里 `fetch`（`HLTV_HTTP=chrome`）。`HLTV_HTTP=curl` 才改用 `curl_cffi`。
3. Scorebot 默认在比赛页里开 WebSocket，不把 cookie 抄出去做 Upgrade。见 [scorebot-transport.md](scorebot-transport.md)。
4. 人手 `/cookie` 或 `import-cookie` 是 keeper 挂了、或本机没有 `:9222` 时的退路。

Cloudflare 拦的是无头 / 一次性环境，以及「不是刚过完 JS 的那个进程」发出的 WebSocket Upgrade。

`__cf_bm` 大约 30 分钟级，`cf_clearance` 更长。keeper 正常时不必按这个周期贴 cookie。

## Cookie

HttpOnly 的 `cf_clearance`、`__cf_bm` **不能** `document.cookie`。DevTools → Network，点一条 `www.hltv.org` 或 `scorebot-lb.hltv.org`，复制 **Cookie** 整行。

```bash
cp data/session.example.json data/session.json
python3 -m hltv_bot import-cookie -o data/session.json
# 粘贴 Cookie: ... 然后 Ctrl-D
```

`data/session.json` 已 gitignore。

`session.json` 字段：`impersonate`、`user_agent`、`sec_ch_ua`、`sec_ch_ua_mobile`、`sec_ch_ua_platform`、`accept_language`、`dnt`、`cookie`。其余头用 `hltv_bot/profile.py` 默认值。

运行时按 `curl_cffi` 里有的选最近的：`chrome136` / `chrome133` / `chrome131` / `chrome124` / `chrome120` / `chrome119` / `chrome116`。

## 从 Chrome 抄下来的头

顺序按抓到的 Scorebot 请求（不含 HTTP/2 伪头）：

1. `sec-ch-ua-platform: "Windows"`
2. `referer: https://www.hltv.org/`
3. `user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36`
4. `sec-ch-ua: "Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"`
5. `dnt: 1`
6. `sec-ch-ua-mobile: ?0`
7. `accept: */*`
8. `accept-encoding: gzip, deflate, br, zstd`
9. `accept-language: zh-CN,zh;q=0.9,zh-TW;q=0.8`
10. `origin: https://www.hltv.org`
11. `priority: u=1, i`
12. `sec-fetch-dest: empty`
13. `sec-fetch-mode: cors`
14. `sec-fetch-site: same-site`
15. `cookie:` DevTools 复制的整行

## 试过但不用的

1. 找公开 Game log API → 没有
2. Chrome MCP 拆协议 / 抽页面 → 协议清楚了，不能当 24h 采集
3. 普通 curl / urllib → 被拦或握不上
4. 每次 headless 开浏览器 → 过不了
5. 无头但保存 profile → 仍难点 JS challenge
6. 换更小浏览器 → JS challenge 还是要完整浏览器
7. 只抄 cookie + TLS 伪装去做 Scorebot Upgrade → poll 握手有时能过，Upgrade 经常 403。只作 `HLTV_SCOREBOT=curl` 退路
8. WebKitGTK / WPE 内容拦截 + 页内 WS → Turnstile 过不了（WebKit 指纹、无 GPU），已放弃

**在用的是** VPS 真 Chrome（`deploy/chrome-session/`）：keeper 续 cookie，比赛页内 WebSocket。评估原文见 [chrome-gateway.md](chrome-gateway.md)，以落地后的传输文档为准。

过程与日志级结论见 [scorebot-transport.md](scorebot-transport.md)。
