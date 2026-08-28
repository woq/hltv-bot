from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hltv_bot.format import format_telegram
from hltv_bot.scorebot import probe_scorebot, ready_for_match_payload
from hltv_bot.session import load_session, save_cookie
from hltv_bot.snapshot import EXTRACT_JS, snapshot_fingerprint


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="HLTV live snapshot / scorebot / telegram")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("extract-js", help="print Chrome MCP evaluate_script source")

    fmt = sub.add_parser("format", help="JSON snapshot stdin -> Telegram text")
    fmt.add_argument("--log-limit", type=int, default=12)

    sub.add_parser("fingerprint", help="JSON snapshot stdin -> change key")

    pr = sub.add_parser("probe-scorebot", help="bare urllib handshake (no impersonate)")
    pr.add_argument("--url", default="https://scorebot-lb.hltv.org")

    rm = sub.add_parser("ready-payload", help="print readyForMatch JSON")
    rm.add_argument("list_id")

    imp = sub.add_parser("import-cookie", help="stdin Cookie 头写入 session.json")
    imp.add_argument("-o", "--out", default="data/session.json")

    st = sub.add_parser("status", help="show session impersonate + cookie names")
    st.add_argument("-s", "--session", default="data/session.json")

    ls = sub.add_parser("matches", help="fetch match list with impersonate+cookie")
    ls.add_argument("-s", "--session", default="data/session.json")

    sub.add_parser("bot", help="run Telegram long-poll bot")

    args = p.parse_args(argv)

    if args.cmd == "extract-js":
        sys.stdout.write(EXTRACT_JS)
        return 0
    if args.cmd == "format":
        snap = json.load(sys.stdin)
        sys.stdout.write(format_telegram(snap, log_limit=args.log_limit))
        return 0
    if args.cmd == "fingerprint":
        snap = json.load(sys.stdin)
        sys.stdout.write(snapshot_fingerprint(snap) + "\n")
        return 0
    if args.cmd == "probe-scorebot":
        json.dump(probe_scorebot(args.url), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if args.cmd == "ready-payload":
        sys.stdout.write(ready_for_match_payload(args.list_id) + "\n")
        return 0
    if args.cmd == "import-cookie":
        raw = sys.stdin.read()
        save_cookie(args.out, raw)
        sess = load_session(args.out)
        print(f"wrote {args.out} impersonate={sess.impersonate} cookies={sess.cookie_names()}")
        return 0
    if args.cmd == "status":
        if not Path(args.session).exists():
            print(f"missing {args.session}", file=sys.stderr)
            return 1
        sess = load_session(args.session)
        print("impersonate", sess.impersonate)
        print("cf_clearance", sess.has_clearance())
        print("cookies", sess.cookie_names())
        return 0
    if args.cmd == "matches":
        from hltv_bot.matches import fetch_matches

        sess = load_session(args.session)
        for row in fetch_matches(sess):
            print(("LIVE " if row["live"] == "1" else "     ") + row["id"], row["title"])
        return 0
    if args.cmd == "bot":
        import logging
        import sys

        from hltv_bot.bot import bot_from_env

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            stream=sys.stdout,
            force=True,
        )
        bot_from_env().run()
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
