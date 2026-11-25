"""Chat thử với bot ngay trên máy, không cần Zalo.

    python3 -m thuchi.cli                 # dùng file thuchi.db
    python3 -m thuchi.cli --db test.db
    python3 -m thuchi.cli --script cau.txt   # chạy lần lượt từng dòng trong file

Mặc định dùng bộ hiểu tin nhắn bằng quy tắc: miễn phí, không cần key.
Muốn dùng Claude thì đặt THUCHI_PARSER=claude và ANTHROPIC_API_KEY trong .env.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .ai_parser import AIUnavailable, ClaudeParser
from .bot import Bot
from .rule_parser import RuleParser
from .store import Ledger

CHAT_ID = "cli"


def load_dotenv(path: Path = Path(".env")) -> None:
    """Đọc file .env đơn giản (KEY=VALUE), không ghi đè biến đã có."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def make_bot(db_path: str) -> Bot | None:
    """Tạo bot với bộ hiểu tin nhắn theo cấu hình (mặc định: quy tắc, miễn phí)."""
    ledger = Ledger(db_path)
    if os.environ.get("THUCHI_PARSER", "rule").lower() == "claude":
        try:
            return Bot(ledger, ClaudeParser())
        except AIUnavailable as exc:
            print(f"Lỗi: {exc}. Thêm ANTHROPIC_API_KEY vào .env hoặc bỏ THUCHI_PARSER=claude.", file=sys.stderr)
            return None
    return Bot(ledger, RuleParser(ledger))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Chat thử bot thu chi")
    ap.add_argument("--db", default=os.environ.get("THUCHI_DB", "thuchi.db"))
    ap.add_argument("--script", help="file chứa các tin nhắn, mỗi dòng một tin")
    args = ap.parse_args(argv)

    load_dotenv()
    bot = make_bot(args.db)
    if bot is None:
        return 1

    if args.script:
        for line in Path(args.script).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                print(f"Bạn: {line}")
                print(f"Bot: {bot.handle(CHAT_ID, line)}\n")
        return 0

    print('Chat với bot thu chi. Gõ "help" để xem hướng dẫn, Ctrl+C để thoát.\n')
    try:
        while True:
            text = input("Bạn: ")
            reply = bot.handle(CHAT_ID, text)
            if reply:
                print(f"Bot: {reply}\n")
    except (KeyboardInterrupt, EOFError):
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
