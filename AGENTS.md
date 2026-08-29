# Agent notes

## Telegram 输出

分流，不要把所有出站都做成 Rich。细则：`docs/rich-message.md`。

- **`/watch` / `/bump`**：Rich Message。只 edit 同一条；新卡片只有 `/bump`。
- **`/matches` 和其余通知**：普通 `sendMessage` + HTML。好复制，**不用**按 Rich 规范检查。
- 记分板：比分表 + 名单表 + log 表，不要 h3/ul/footer 文章壳。

## 提交 / push 前

```bash
python3 -m pytest tests/test_rich_message.py tests/test_format.py tests/test_watch_flush.py -q
```

不要用「源码里禁止 sendMessage」这种检查。

## 其它文档

- `docs/hltv-api.md` — HLTV 非官方接口
- `docs/cloudflare.md` — Cookie / TLS
