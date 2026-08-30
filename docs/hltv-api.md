# HLTV 接口（非官方）

HLTV **没有**公开的 REST / Game log API。本项目用两层非官方入口：

| 层 | 端点 | 用途 |
|---|---|---|
| HTML | `https://www.hltv.org/matches` | 今日/即将开始的比赛列表 |
| HTML | `https://www.hltv.org/matches/{id}/{slug}` | 详情页 meta（scorebot id / url / 队名） |
| Engine.IO | `https://scorebot-lb.hltv.org/socket.io/` | 实时记分板 + Game log |

实现：`hltv_bot/matches.py`、`hltv_bot/scorebot.py`、`hltv_bot/eio.py`、`hltv_bot/live.py`。  
过 Cloudflare 的 Cookie / TLS 伪装见 [cloudflare.md](cloudflare.md)。

---

## 访问条件

三条缺一，HTML 和 Scorebot 都会 403：

1. 本机 Chrome 烤出来的 Cookie 整行（必须含 HttpOnly `cf_clearance`，最好有 `__cf_bm`）
2. `curl_cffi` TLS `impersonate`（不要用普通 urllib / curl）
3. 出口 IP 与烤 Cookie 的浏览器一致

请求头顺序与 Chrome 134 抓包对齐，见 `hltv_bot/profile.py`。

列表页缓存 45s（进程内 `_MATCH_CACHE`）。

---

## 1. 比赛列表

```
GET https://www.hltv.org/matches
Accept: text/html
sec-fetch-dest: document
sec-fetch-mode: navigate
sec-fetch-site: none
```

返回 HTML。解析 `href="/matches/{id}/{slug}"`，再从链接附近抽取队名、赛事、星级、开赛时间。

### 解析结果（每场）

| 字段 | 含义 |
|---|---|
| `id` | 比赛数字 id，后面也当 `listId` |
| `url` | 绝对地址 |
| `team1` / `team2` | 队名（优先 HTML，退回 slug） |
| `event` | 赛事名 |
| `title` | `{team1} vs {team2}` |
| `live` | `"1"` / `"0"`（看前面是 `liveMatch` 还是 `upcomingMatch`） |
| `stars` | 0–5 |
| `unix` | `data-unix`（毫秒或秒） |
| `time` | 转 CST：当天 `HH:MM`，跨天 `MM/DD HH:MM`，直播无时间则 `LIVE` |

排序：直播在前，再按星级降序。默认最多 40 场。

### 代码

```python
from hltv_bot.matches import fetch_matches
from hltv_bot.session import load_session

rows = fetch_matches(load_session("data/session.json"))
```

CLI：`python3 -m hltv_bot matches`

---

## 2. 比赛详情（Scorebot meta）

```
GET https://www.hltv.org/matches/{id}/{slug}
# 只给数字 id 时本项目会拼成 /matches/{id}/x
```

页面 `#scoreboardElement` 上的 dataset：

```html
<div id="scoreboardElement"
     data-scorebot-id="2396932"
     data-scorebot-url="https://scorebot-lb.hltv.org"
     data-team1-name="G2"
     data-team2-name="Spirit">
```

| 字段 | 来源 |
|---|---|
| `scorebotId` | `data-scorebot-id`，连 Scorebot 用的 `listId` |
| `scorebotUrl` | `data-scorebot-url`；可能是逗号分隔多个，取最后一个 |
| `team1` / `team2` | `data-team1-name` / `data-team2-name` |
| `url` | 请求地址 |

未开打或没有记分板时，`scorebotId` 可能为空。Bot 会退回 URL 里的数字。

```python
from hltv_bot.matches import fetch_match_meta
meta = fetch_match_meta(sess, "2396932")
# meta["scorebotId"], meta["scorebotUrl"]
```

DOM 全量抽取（Chrome MCP / evaluate）见 `hltv_bot/extract.js`：`python3 -m hltv_bot extract-js`。

---

## 3. Scorebot（Engine.IO v3 → WebSocket）

基址默认 `https://scorebot-lb.hltv.org`。和浏览器一样：polling **只用来握手拿 sid**，随后立刻升级到 **WebSocket**。事件、心跳、`readyForMatch` 都走 WS，不再长轮询 GET。

必须 **复用同一条 TLS 会话**（`curl_cffi` Session：握手 GET 的 `io` cookie 带到 WS upgrade）。

### 3.1 握手

```
GET {base}/socket.io/?EIO=3&transport=polling&t={ms}
Origin: https://www.hltv.org
```

响应是 Engine.IO payload。首包 `0{json}`：

```json
{
  "sid": "...",
  "upgrades": ["websocket"],
  "pingInterval": 25000,
  "pingTimeout": 60000
}
```

握手后先 **polling `readyForMatch`**（和浏览器一样），立刻尝试 WS 升级。403 则继续 poll，**每 30s 以及 poll 5xx 时再试升级**；成功就切到 WS，底部状态会显示 `ws` / `poll`。

```
wss://scorebot-lb.hltv.org/socket.io/?EIO=3&transport=websocket&sid={sid}
2probe  →  3probe  →  5
然后 WS 文本帧发 42["readyForMatch", "..."]
服务端 Engine.IO ping 是帧 `2`，回 `3`（不要跟 WS 协议层 ping 搞混）
```

WS 上每个帧一条 Engine.IO 包，**不要**再套 xhr 的 `\x00…\xff` 长度帧。

握手 GET 仍可能 502（CF 到源站）。那是一次性握手，不是每几秒一轮 poll。断线指数退避：≥15s，5xx 首次 ≥25s，到 180s。`www.hltv.org` HTML 两次至少 3s。Telegram edit 最少 1.8s。

403/429 仍停等 `/cookie`，不重连死磕。

### 3.2 订阅一场

客户端发 Socket.IO 事件 `readyForMatch`：

```json
{"token": "", "listId": "2396932"}
```

`token` 抓包里通常是空串。`listId` = 详情页 `data-scorebot-id`。

Socket.IO 事件（WS 文本帧，无 xhr 外壳）：

`42` + `JSON.stringify(["readyForMatch", "<上面那段 JSON 字符串>"])`

### 3.3 收事件

升级完成后 `ws.recv`。帧若匹配 `42[...]` 就是事件。事件名在数组第 0 项，第 1 项经常是 **再套一层 JSON 字符串**。

本项目 `iter_scorebot()` 还会 yield 内部状态（不是 HLTV 发的）：

| 事件 | 来源 | 含义 |
|---|---|---|
| `scoreboard` | 服务端 | 当前回合、比分、两侧球员 |
| `log` | 服务端 | Game log 增量 |
| `status` | 客户端 | `connecting` / `connected` / `idle` / `reconnect` / `disconnected` |
| `tick` | 客户端 | 一帧处理完，用来刷新 Telegram |

Cloudflare 403/429 直接抛 `CloudflareError`。

```python
from hltv_bot.scorebot import iter_scorebot, scorebot_base

for name, payload in iter_scorebot(sess, list_id, base=scorebot_base(meta["scorebotUrl"])):
    ...
```

探测（不带 impersonate）：`python3 -m hltv_bot probe-scorebot`  
打印 payload：`python3 -m hltv_bot ready-payload 2396932`

---

## 4. `scoreboard` 字段

服务端键名不固定，解析时多路兼容（`hltv_bot/live.py`）：

| 含义 | 尝试的键 |
|---|---|
| CT 队名 | `ctTeamName`, `ctName` |
| T 队名 | `tTeamName`, `terroristTeamName` |
| CT 分 | `ctScore`, `counterTerroristScore` |
| T 分 | `tScore`, `terroristScore` |
| 回合 | `currentRound`, `round` |
| 地图 | `mapName`, `map`（会去掉 `de_`） |
| CT 球员 | `ctTeam`, `ctPlayers`, `counterTerrorists`, `CT`, `ct` |
| T 球员 | `terroristTeam`, `tPlayers`, `terrorists`, `TERRORIST`, `t` |

球员：`nick` / `name` / `dbName` / `playerName`；`kills` 或 `score`；`assists`；`deaths`；ADR 用 `damagePrRound` / `adr` / `damage`。

完整原始字段、归一化 log、snapshot、回合结束为何会丢，见 [scorebot-data.md](scorebot-data.md)。

归一化后的 snapshot（摘要）：

```json
{
  "live": true,
  "url": "...",
  "team1": {"name": "T 队"},
  "team2": {"name": "CT 队"},
  "roundText": "19 - Dust2",
  "scoreText": "13-6",
  "ctScore": 13,
  "tScore": 6,
  "teams": [
    {"name": "CT 队", "players": [{"nick": "...", "kills": 0, "assists": 0, "deaths": 0, "adr": 0}]},
    {"name": "T 队", "players": []}
  ],
  "log": []
}
```

`team1` 对应 T，`team2` 对应 CT（跟详情页 dataset 不一定同序，展示时按 CT/T）。

---

## 5. `log` 事件

常见形态：

```json
{
  "log": [
    {"Kill": {"killerNick": "sh1ro", "victimNick": "huNter-", "weapon": "awp", "headShot": true}},
    {"BombPlanted": {"playerNick": "donk", "bombSite": "A"}},
    {"RoundEnd": {"winner": "CT", "winType": "CTs_Win"}}
  ]
}
```

也可能是单条对象，或外层再包一层。新事件插到列表头，最多留 80 条。

| 原始键 | 归一化 `type` | 说明 |
|---|---|---|
| `Kill` | `kill` | `killer` / `victim` / `weapon` / `headshot`；助攻合并为 `assister` |
| `Assist` | 并入击杀，或 `assist` | `killEventId` → 击杀行 `+ nick` |
| `BombPlanted` | `bomb` | `planted A` |
| `BombDefused` | `bomb` | `defused` |
| `RoundStart` / `RoundStarted` | `round_start` | `Round` / `start`；scoreboard 换回合也会补 |
| `RoundEnd` | `round_over_ct` / `round_over_t` | `Round over · CT · elimination · 8-11`；分变了但没 log 时合成 |
| `Suicide` | `suicide` | 不展示 |
| `PlayerJoin` / `PlayerQuit` / `MatchStarted` / `MatchOver` / `Reconnect` / `Disconnect` | 忽略 | |

`RoundEnd.winType` 展示（英语）：

| 值 | 展示 |
|---|---|
| `Bomb_Defused` | defuse |
| `Target_Bombed` | bomb |
| `Target_Saved` | time |
| `CTs_Win` / `Terrorists_Win` | elimination |

`Kill.weapon` 是 CS 内部名（`awp`、`ak47`、`m4a1_silencer`…），展示层在 `hltv_bot/format.py` 映射。

---

## 6. Engine.IO 编解码备忘

`hltv_bot/eio.py`：

| 函数 | 作用 |
|---|---|
| `decode_payload(bytes)` | v3 二进制帧（`\x00`…`\xff`）或 v4 `\x1e` 分隔 |
| `encode_payload(str)` | 打成 v3 xhr 帧 |
| `parse_open` | 包以 `0` 开头 → handshake JSON |
| `parse_event` | `42[name, data]`，`data` 若是字符串再 `json.loads` 一次 |
| `encode_event(name, data)` | 生成 `42[...]` |

探测/联调用例如下（逻辑与 `iter_scorebot` 相同）：

```
handshake GET → sid
POST 42["readyForMatch","{\"token\":\"\",\"listId\":\"…\"}"]
循环 GET → 42["scoreboard", …] / 42["log", …]
```

---

## 7. 和 Bot 的对应

```
/matches  → GET /matches → parse_match_list
/watch id → GET /matches/{id}/x → data-scorebot-id
          → Engine.IO readyForMatch
          → scoreboard + log → snapshot → Telegram edit
```

无直播数据时，`hltv_bot/fixtures.py` 有静态列表和假 Scorebot 流，只给 UI 测 3K/ACE，不打 HLTV。
