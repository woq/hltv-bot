# 现行架构（`main`，2026-11）

以代码为准；本页是速查。细节命令见 `AGENTS.md` / `/hltv`。

```
Telegram 群/私聊
       ↕
hltv-bot（systemd，MemoryMax≈400M）
  ├─ keeper 线程 ──attach──► :9222 CDP
  ├─ HLTV_HTTP=chrome → keeper tab 内 fetch(HTML)
  │     退路 HLTV_HTTP=curl → curl_cffi + session.json
  └─ /watch 比分 ←── 赛程总页 HTML（reminders / fetch_matches）
                         不是页内 Scorebot

hltv-chrome（systemd，Restart=no，headed + Xvfb）
  └─ keeper tab https://www.hltv.org/matches
        自续 __cf_bm；人 VNC(6080) 过 Turnstile
```

| 面 | 现行 | 非现行 |
|---|---|---|
| Cookie | Chrome keeper CDP 导出 | 人手 `/cookie` 退路 |
| 列表/赛事 HTML | `HLTV_HTTP=chrome` | `curl` |
| `/watch` 比分 | 赛程总页轮询 | 页内 Scorebot WS（`archive/chrome-full`） |
| Scorebot 模块 | 树内保留，bot 主路径不调用 | `HLTV_SCOREBOT=chrome/curl` |
| 无头 Chrome | **不用** | — |

部署：push `main` → 只 `restart hltv-bot`，绝不 start/restart `hltv-chrome`。
