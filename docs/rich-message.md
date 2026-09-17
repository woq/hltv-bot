# Telegram Rich Message

官方：<https://core.telegram.org/bots/api#rich-message-formatting-options>（Bot API 10.1，2026-06-11）

## 解决什么问题

普通 `sendMessage` 是**一条字符串 + 有限 entity**（粗体、链接、`pre`）。做不了表、标题层级、折叠块、公式、文内插图，也不能边生成边推草稿。

Rich Message 把一条消息当成**小文档**：标题、表格、列表、引用、脚注、数学、媒体块、地图、collage / slideshow。另有 `sendRichMessageDraft` + thinking 块，给 AI 流式打字。

本项目只用它做 **`/watch` 记分板**（要表、要原地 `edit`）。列表、命令、状态要能划选复制，走普通消息。

## 本仓库分流

| 场景 | 通道 | 原因 |
|---|---|---|
| `/watch` 记分板、`/bump` 新卡片 | Rich：`sendRichMessage` / `editMessageText` + `rich_message` | 原生表，一条消息反复改 |
| `/matches`、帮助、状态、错误、授权 | 普通：`sendMessage` + `parse_mode=HTML` | 好划选、好复制 `/watch id`；30s 后自动删 |
| 其它短通知 | 普通 `send_message` | 不强制 rich |

**不要检查普通消息是不是 Rich。** 提交前测试只约束 watch 路径：编辑失败不得改成连发新卡片。

Watch 规则不变：默认只 edit 同一条；`not modified` 当成功；新卡片只有 `/bump`。卡片只发给发过 `/watch` 的群，不广播全部授权群。普通消息和 rich **不能互相 edit 变形**。

## Watch 记分板怎么排

Rich **没有 CSS**。单元格只能行内标签。不要用 h3/ul/footer 文章壳。

每群 **两条** Rich（`/watch` / `/bump` 连发，`/stop` 两条都删）：

1. **战绩消息**：回合史 + 名单表 CT / T，默认展开（已拆成独立消息，不再包 `<details>`）。只在 K/A/D/ADR/回合史/地图分变时 edit，Kill 不碰这条。
2. **Log 消息**：比分条 `table bordered compact` → Log 表（两列：选手 / 事件；无 Who 表头；文案英语）→ 最下一行链接状态（手机约 68 字）：`connected · freeze · bomb · 3v5 · R19 · Inferno · 18:32:05`；异常时带 notice / next。

未出分用 `–`，不要 0-0。

拿不到可用记分板时（从未出分、或 60s 无 scorebot）**只把 log 那条**改成 DEBUG：`pre` 里最近运输层痕迹。战绩那条不动。瞬时 5xx 时有新数据就留记分板，只在底栏带 notice / next。有过比分后断开则 LIVE 改 SCORE 结算，不另发新消息。

限制（官方）：正文 ≤ 32768；块 ≤ 500；表 ≤ 20 列；嵌套 ≤ 16。
