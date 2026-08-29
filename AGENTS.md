# Agent notes

## Telegram 输出

**所有用户可见消息必须是 Rich Message。** 细则：`docs/rich-message.md`。

- 发送：`sendRichMessage`（`Telegram.send_rich` / `send_message`）
- 编辑：`editMessageText` + `rich_message`（`Telegram.edit_rich`）
- 禁止 Bot API `sendMessage` 和 `parse_mode` 正文
- 记分板按 HLTV：CT / T 两张表，不要混排球员

## 提交 / push 前

在 `git commit` 或 `git push` 之前必须跑：

```bash
python3 -m pytest tests/test_rich_message.py tests/test_format.py -q
```

`tests/test_rich_message.py` 会扫描 `hltv_bot/` 里是否又写回了 `"sendMessage"`。不过这条就不要提交、不要推。

## 其它文档

- `docs/hltv-api.md` — HLTV 非官方接口
- `docs/cloudflare.md` — Cookie / TLS
