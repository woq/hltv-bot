# Scorebot 数据结构

HLTV 没有公开 schema。下面以 [gigobyte/HLTV `connectToScorebot.ts`](https://github.com/gigobyte/HLTV/blob/master/src/endpoints/connectToScorebot.ts) 和本仓库实测为准。实现：`hltv_bot/scorebot.py`（收包）、`hltv_bot/live.py`（归一化）、`hltv_bot/format.py`（Telegram）、`hltv_bot/bot.py`（watch）。

管线：

```
Engine.IO polling 握手 → WebSocket 升级
        42["scoreboard", obj] / 42["log", json字符串]
        ↓
iter_scorebot  yield ("scoreboard"|"log"|"status"|"tick", payload)
        ↓
merge_log / mark_new_round / mark_round_over / patch_board_from_log
        ↓
snapshot_from_scoreboard  →  snapshot dict
        ↓
format_rich_html  →  多群各自 edit 同一份 HTML
```

---

## 1. 传输层事件（`iter_scorebot`）

| `name` | 来源 | payload |
|---|---|---|
| `scoreboard` | 服务端 | 当前地图记分板 object（见 §2） |
| `log` | 服务端 | `{ "log": [ LogEvent, ... ] }`，或单条 object；常再套一层 JSON 字符串 |
| `fullLog` | 服务端 | 少见，本项目当普通 `log` 一样解析 |
| `status` | 客户端 | `{ "state", "detail?", "wait?" }` |
| `tick` | 客户端 | 一帧 WS 处理完，用来冲刷 deferred Telegram edit |

`status.state`：`connecting` | `connected` | `idle` | `reconnect` | `disconnected`。

`log` 包里的数组**不一定**最新在前。本项目 `merge_log` 把新行 `insert(0)`，snapshot 的 `log[0]` 永远是最新可见事件。

---

## 2. 原始 `scoreboard`

键名会变，解析时多路兼容（`snapshot_from_scoreboard`）。完整形态接近：

```json
{
  "TERRORIST": [ { "/* ScoreboardPlayer */": true } ],
  "CT": [ { "/* ScoreboardPlayer */": true } ],
  "ctMatchHistory": {
    "firstHalf": [ { "type": "CTs_Win", "roundOrdinal": 1, "survivingPlayers": 3 } ],
    "secondHalf": []
  },
  "terroristMatchHistory": {
    "firstHalf": [ { "type": "lost", "roundOrdinal": 1, "survivingPlayers": 0 } ],
    "secondHalf": []
  },
  "bombPlanted": false,
  "mapName": "de_mirage",
  "terroristTeamName": "G2",
  "ctTeamName": "Spirit",
  "currentRound": 20,
  "counterTerroristScore": 8,
  "terroristScore": 11,
  "ctTeamId": 7020,
  "tTeamId": 5995,
  "frozen": false,
  "live": true,
  "ctTeamScore": 8,
  "tTeamScore": 11,
  "startingCt": 7020,
  "startingT": 5995
}
```

### 2.1 字段（原始 → 我们怎么读）

| 含义 | 尝试的键 |
|---|---|
| CT 队名 | `ctTeamName`, `ctName` |
| T 队名 | `tTeamName`, `terroristTeamName` |
| 本图 CT 分 | `ctScore`, `counterTerroristScore`, `ctTeamScore` |
| 本图 T 分 | `tScore`, `terroristScore`, `tTeamScore`, `terroristTeamScore` |
| 回合号 | `currentRound`, `round` |
| 地图 | `mapName`, `map`（展示时去掉 `de_`） |
| CT 球员列表 | `CT`, `ctTeam`, `ctPlayers`, `counterTerrorists`, `ct` |
| T 球员列表 | `TERRORIST`, `terroristTeam`, `tPlayers`, `terrorists`, `t` |
| 回合史 | `ctMatchHistory` / `terroristMatchHistory`（`firstHalf` + `secondHalf`） |
| 拆包中 | `bombPlanted` |
| freeze | `frozen` |
| 是否直播 | `live` |

`ctTeamScore` / `tTeamScore` 在现网里经常就是**本图回合分**，不是 BO3 系列分。系列分 Scorebot **不保证**提供。

### 2.2 `ScoreboardPlayer`

| 字段 | 含义 |
|---|---|
| `nick` / `name` / `dbName` / `playerName` | 游戏名 |
| `score` / `kills` | 击杀（本图） |
| `assists` | 助攻 |
| `deaths` | 死亡 |
| `damagePrRound` / `adr` / `damage` | ADR |
| `alive` | 是否存活 |
| `hp` | 血量 |
| `money` | 经济 |
| `primaryWeapon` | 主武器内部名 |
| `kevlar` / `helmet` / `hasDefuseKit` | 护甲 / 拆弹钳 |
| `steamId` / `dbId` | 标识 |
| `advancedStats.kast` 等 | HLTV 进阶，本项目未展示 |

归一化球员：`{ nick, kills, assists, deaths, adr }`。

### 2.3 `ctMatchHistory` / `terroristMatchHistory`

每一回合在两侧各有一条：赢的一侧 `type` 是胜因，输的一侧是 `"lost"`。

```json
{ "type": "CTs_Win", "roundOrdinal": 7, "survivingPlayers": 3 }
```

| `type`（WinType） | 含义 | 展示 |
|---|---|---|
| `CTs_Win` | CT 歼灭 | `elim` |
| `Terrorists_Win` | T 歼灭 | `elim` |
| `Target_Bombed` | 包炸 | `bomb` |
| `Bomb_Defused` | 拆包 | `defuse` |
| `Target_Saved` | 时间结束（包没下） | `time` |
| `lost` | 本侧输掉这回合 | 不入 history |

`roundOrdinal` 是回合序号（1-based）。加时也会往 half 数组里继续堆，不要假设 firstHalf 只有 12 条。

归一化 `snapshot.history`：

```json
[ { "n": 1, "winner": "CT", "winType": "CTs_Win", "alive": 3 } ]
```

只保留赢的一侧，按 `n` 升序。Telegram 战绩折叠块用这一列。

---

## 3. 原始 `log` 事件

一个 packet：

```json
{
  "log": [
    { "Kill": { "...": true } },
    { "Assist": { "...": true } },
    { "BombPlanted": { "...": true } },
    { "RoundEnd": { "...": true } }
  ]
}
```

每条 LogEvent **恰好一个键**，键名就是类型。载荷字段如下。

### 3.1 `Kill`

```json
{
  "Kill": {
    "killerName": "Dmitry Sokolov",
    "killerNick": "sh1ro",
    "killerSide": "CT",
    "victimName": "...",
    "victimNick": "huNter-",
    "victimSide": "TERRORIST",
    "weapon": "awp",
    "headShot": true,
    "eventId": 1841,
    "victimX": 0, "victimY": 0,
    "killerX": 0, "killerY": 0,
    "killerId": 1, "victimId": 2,
    "flasherNick": "donk",
    "flasherSide": "CT"
  }
}
```

| 字段 | 用途 |
|---|---|
| `killerNick` / `killerName` | 击杀者 |
| `victimNick` / `victimName` | 死者 |
| `weapon` | CS 内部名（`awp`, `ak47`, `m4a1_silencer`…） |
| `headShot` | 爆头 |
| `eventId` | 本回合事件 id；半场/重连常重置 |
| `flasherNick` | 闪光助攻（未单独展示） |
| `*Side` | `CT` / `TERRORIST` / `SPECTATOR` |
| `*X` / `*Y` | 小地图坐标，忽略 |

归一化：

```json
{
  "type": "kill",
  "killer": "sh1ro",
  "victim": "huNter-",
  "text": "sh1ro huNter-",
  "weapon": "awp",
  "headshot": true,
  "assist": false,
  "assister": "donk",
  "event_id": "1841"
}
```

`assister` 在 merge 时由匹配的 `Assist` 填上（见 §3.2），不是 Kill 自带字段。

### 3.2 `Assist`

```json
{
  "Assist": {
    "assisterName": "...",
    "assisterNick": "donk",
    "assisterSide": "CT",
    "victimNick": "huNter-",
    "victimName": "...",
    "victimSide": "TERRORIST",
    "killEventId": 1841
  }
}
```

`killEventId` 对应那条 `Kill.eventId`。同一 packet 里经常是 Kill 紧跟 Assist。

处理：

1. 能对上 `eventId`（或本回合同一 victim）→ 写到击杀行 `assister`，**不再单独占一行**
2. 对不上 → 自己一行：`{ type: "assist", killer: 助攻者, victim, kill_event_id, detail: "assist victim" }`

展示：击杀行末尾 `+ donk`；落单助攻是左列 nick、右列 `assist victim`。不要用 `Who` / `·` 占位。

### 3.3 `BombPlanted` / `BombDefused`

```json
{ "BombPlanted": { "playerName": "...", "playerNick": "donk", "bombSite": "A", "ctPlayers": 3, "tPlayers": 5 } }
{ "BombDefused": { "playerName": "...", "playerNick": "sh1ro" } }
```

`bombSite` 现网有时没有。归一化 `type: "bomb"`，`detail`：`planted A` / `defused`。

### 3.4 `RoundStart` / `RoundStarted` / `Restart`

载荷经常是 `{}`。归一化：

```json
{ "type": "round_start", "killer": "Round", "text": "start", "detail": "start" }
```

不能用整段 JSON 当去重 key（每回合都是 `{}`）。`merge_log` 对 `round_start` 不做 `_raw` 去重。

scoreboard 的 `currentRound` 变化时，`mark_new_round` 也会在 feed 头插一条（半场换边、下一张图经常不发 RoundStart）。

### 3.5 `RoundEnd`（回合结束）

```json
{
  "RoundEnd": {
    "counterTerroristScore": 8,
    "terroristScore": 11,
    "winner": "TERRORIST",
    "winType": "Target_Bombed"
  }
}
```

| 字段 | 含义 |
|---|---|
| `winner` | `CT` / `TERRORIST`（偶发 `T`） |
| `winType` | 同 §2.3 |
| `counterTerroristScore` / `terroristScore` | **结束后**的本图比分 |

归一化：

```json
{
  "type": "round_over_ct",
  "killer": "Round",
  "text": "Round over · CT · elimination · 8-11",
  "detail": "Round over · CT · elimination · 8-11",
  "winner": "CT",
  "win_type": "CTs_Win",
  "ct_score": 8,
  "t_score": 11
}
```

T 胜则 `type` 为 `round_over_t`。

**为什么界面上会“没有回合结束”：**

1. 重连 / 半场 dump 被 `merge_log` 当成 replay 整包丢掉（包里夹带的 RoundEnd 一起没了）
2. 只来了 scoreboard 分变了，log 没发 RoundEnd
3. 旧 UI 用中文「回合结束」做 force-edit 匹配，英文化之后对不上就不会立刻推

对应处理：

- `mark_round_over`：本图分相对上一帧变了，且 feed 头还不是 `round_over_*`，就合成一条
- 之后若 log 来了真 RoundEnd（同分），**替换**合成行，保留胜因
- Telegram force-edit：看 `log[0].type` 是不是 `round_start` / `round_over_*`，不再扫中文

`patch_board_from_log` 用 RoundEnd 的两个 score 字段去改 board，避免记分板晚一拍。

### 3.6 其它原始键

| 键 | 归一化 | 展示 |
|---|---|---|
| `Suicide` | `{ type: "suicide", text: "{nick} suicide" }` | **不显示** |
| `PlayerJoin` / `PlayerQuit` | 丢弃 |  |
| `MatchStarted` / `MatchStart` | 丢弃（`{ map }`） |  |
| `MatchOver` | 丢弃 |  |
| `Reconnect` / `Disconnect` | 丢弃 |  |

未知单键 object：`{ type: "other", text: "{kind} {nick}" }`，左列用 nick 或 `Log`。

---

## 4. `merge_log` 去重规则

新事件插到列表头，最多 80 条。

| 规则 | 作用 |
|---|---|
| 本回合已见 `eventId` | 跳过 |
| 大包里所有 id 都在历史里 | 当重连回放，整包跳过 |
| ≥4 条 kill 且半数 semantic 已见 | 半场 dump，按 semantic 跳过 |
| 本回合同一 `killer→victim` | CS 一回合不可能再杀同一人，跳过 |
| `round_over_*` 与 feed 头合成行同分 | 用真 RoundEnd 覆盖 |
| Assist 对上 Kill | 不占新行 |

semantic key（忽略坐标 / flasher / eventId）：

- kill：`k|killer|victim|weapon|hs`
- bomb：`b|nick|detail`
- assist：`a|nick|victim|kill_event_id`
- round_over：`e|detail|ct_score|t_score`
- round_start：无（每回合都要留下）

`_this_round`：从 `log[0]` 往下走到第一个 `round_start` / `round_over_*` 之前，用来算 2K/3K/ACE。

---

## 5. Snapshot（给 Telegram 的归一化对象）

`snapshot_from_scoreboard(board, meta=, log=)` 再由 watch 循环补 `link` / `notice` / `next_at`。

```json
{
  "live": true,
  "url": "https://www.hltv.org/matches/2396932/x",
  "team1": { "name": "G2" },
  "team2": { "name": "Spirit" },
  "roundText": "19 - Dust2",
  "scoreText": "13-6",
  "ctScore": 13,
  "tScore": 6,
  "teams": [
    { "name": "Spirit", "players": [ { "nick": "donk", "kills": 10, "assists": 3, "deaths": 11, "adr": 65.0 } ] },
    { "name": "G2", "players": [] }
  ],
  "history": [ { "n": 1, "winner": "CT", "winType": "CTs_Win", "alive": 3 } ],
  "bombPlanted": false,
  "frozen": false,
  "log": [ { "type": "kill", "...": true } ],
  "link": "connected",
  "notice": "",
  "next_at": 0
}
```

注意：`teams[0]` 永远是 **CT**，`teams[1]` 是 **T**。`team1` / `team2` 按当前边：`team1` = T 名，`team2` = CT 名，和详情页 dataset 的 team1/team2 **不一定同序**。

`link` 不是 HLTV 字段，是本客户端连接状态。

指纹 `snapshot_fingerprint`：比分 + 回合字 + `log[0]` + 最近 history + K/D，用来跳过无变化的 edit。

---

## 6. Telegram 卡片怎么用这些字段

顺序（Rich HTML，无 h3/ul/footer）：

1. `<details>`（默认折叠）summary `Stats {ct}–{t}`
   - `history` → 一行 `R1 CT elim · R2 T bomb · …`
   - `teams` → 两张名单表（Player / K / A / D / ADR）
2. 比分表：CT 名、本图分、T 名；caption `LIVE · Map · R{n}`
3. log 表（最多 12 行，无表头）
   - 左列：选手 nick，或 `Round` / `Log`
   - 右列：`killed X · AWP HS 3K + assistNick` / `planted A` / `Round over · CT · elimination · 8-11` / `start`
4. 最后一行纯文字：`connected` / `reconnect · HTTP 502 · next 12:01:03`

未出分用 `–`，不要 `0-0`。

---

## 7. Watch 进程内状态

全局 **一场** 比赛、一条 Scorebot 线程。

```text
WatchState
  list_id, meta, text, fingerprint, last_snap
  link, notice, next_at, pending, stop
  cards: { chat_id: WatchCard(chat_id, message_id, sent_html) }
```

- `/watch id`：已在看同一场 → 该群还没有卡片就发一条；已经有则提示 `/bump`
- 换比赛：停旧线程，**复用**各群已有 `message_id` 原地 edit；没有卡片的授权群新发
- 之后每次 flush：同一份 HTML `edit` 所有 `cards`
- `/bump`：只给**当前群**发新消息，改这个群的 `message_id`
- `/stop`：停全局

授权群来自 `data/chats.json`。
