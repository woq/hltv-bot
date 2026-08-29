# Telegram Rich Message

用户可见的每条 Bot 输出都必须是 **Rich Message**（Bot API 10.1+）。  
禁止用 `sendMessage` / `parse_mode=HTML` 当主路径。

规范：<https://core.telegram.org/bots/api#rich-message-formatting-options>

## 硬规则

| 动作 | 方法 | payload |
|---|---|---|
| 新消息 | `sendRichMessage` | `rich_message.html` |
| 原地更新 | `editMessageText` | 同一个 `rich_message`（**不能**改成普通 `text`） |
| 顶上去 `/bump` | 再发一条 `sendRichMessage` | 内容仍是 rich html |

`hltv_bot/telegram_api.py` 里的 `send_message` / `edit_message` 只是封装，内部同样走上面两条。  
`plain_to_rich()` 会把无块级标签的短通知包成 `<p>` / `<br>`。

**不要：**

- 调 Bot API `sendMessage`
- 用 `parse_mode` 当正文格式
- 先发文字消息再想改成 rich（类型不同，改不了）
- 把 `\n` 当块级换行塞进 rich（规范是块标签；行内用 `<br>`）

## 本项目 HTML 子集

只用规范里有的标签。记分板 / 列表常用：

- 块：`<h3>` `<h4>` `<p>` `<ul>` `<li>` `<table bordered striped compact>` `<caption>` `<tr>` `<th>` `<td>` `<hr>` `<footer>` `<details>` `<summary>`
- 行内：`<b>` `<i>` `<code>` `<mark>` `<a href>` `<br>`
- 按钮：`<tg-button-row>` + `<tg-button type="url">`（不要 callback，除非加了 handler）

限制：正文 ≤ 32768；块（含表格行、列表项）≤ 500；表 ≤ 20 列；嵌套 ≤ 16。

`skip_entity_detection` 默认 **false**，让 `/watch` `/bump` 能被点。

## HLTV 记分板怎么排

对齐 HLTV 直播记分板，不要把两队球员揉成一张按 K 排序的表。

1. `<h3>`：`LIVE · 地图`（可链到比赛页）
2. `<p>`：`CT队 比分 – 比分 T队`，下一行 `R19` / 连接状态 `<mark>`
3. 两张表：caption `CT · 队名 · 分`、`T · 队名 · 分`；列 Player / K / A / D / ADR，队内按 K 降序
4. `<h4>Game log</h4>` + `<ul>`；击杀 `nick killed nick · AWP <mark>HS</mark> <mark>3K</mark>`
5. 更早的 log 放 `<details><summary>Earlier</summary>`
6. `<footer>/bump</footer>`，有 URL 再加 HLTV 按钮

Scorebot 还没吐 `scoreboard` 时只用 `format_connecting_html`（队名 + connecting），**不要**画 0-0 空表。

比赛列表：按赛事 `<h4>` + compact 表；LIVE 用 `<mark>LIVE</mark>`；`/watch {id}` 放在格子里（不要包 `<code>`，才能当命令点）。

## 提交 / push 前必查

每次 commit、push 之前跑：

```bash
python3 -m pytest tests/test_rich_message.py tests/test_format.py -q
```

这条测试会扫 `hltv_bot/`：源码里不能出现 Bot API 方法名 `"sendMessage"`。

改了任何 Telegram 出站路径，再人工过一遍：

- 新加的用户可见字符串是不是 rich html（或走 `send_message` → `plain_to_rich`）
- `/watch` 编辑仍是 `edit_rich`，失败也只许简化 html 再 `edit_rich` / `send_rich`
- 不要为了“兼容旧客户端”偷偷加回 `sendMessage`

提示词见仓库根目录 `AGENTS.md`。
