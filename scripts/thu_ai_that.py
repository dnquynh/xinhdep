"""Kiểm tra AI thật (Claude Haiku) hiểu đúng 7 câu mẫu. Cần ANTHROPIC_API_KEY.

    python3 scripts/thu_ai_that.py

So sánh từng trường AI trả về với kết quả mong đợi, in ĐÚNG/SAI từng câu.
Mỗi lần chạy tốn khoảng 7 lượt gọi Haiku (vài chục đồng).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from thuchi.ai_parser import AIUnavailable, ClaudeParser  # noqa: E402
from thuchi.cli import load_dotenv  # noqa: E402
from thuchi.money import parse_amount  # noqa: E402
from thuchi.store import normalize_name  # noqa: E402

# (câu, kind, số tiền, nhóm, người trả, người nhận, người cùng chia, cách chia)
CASES = [
    ("ăn lẩu 600k, tôi trả, chia với Nam và Lan", "chi_chung", 600_000, "Ăn uống", "tôi", None, {"tôi", "nam", "lan"}, "chua_noi"),
    ("Nam trả tiền taxi 120k cho tôi với Nam", "chi_chung", 120_000, "Đi lại", "nam", None, {"tôi", "nam"}, "chua_noi"),
    ("cho Hùng mượn 2tr", "cho_vay", 2_000_000, None, "tôi", "hùng", None, None),
    ("Hùng trả 500k", "tra_no", 500_000, None, "hùng", "tôi", None, None),
    ("vay chị Mai 1tr5", "di_vay", 1_500_000, None, "mai", "tôi", None, None),
    ("lương tháng 11 15tr", "thu", 15_000_000, "Thu nhập", None, None, None, None),
    ("tiền điện 450k", "chi", 450_000, "Nhà ở và điện nước", None, None, None, None),
    # thêm vài câu khó
    ("ăn lẩu 600k chia đều với Nam và Lan, tôi trả", "chi_chung", 600_000, "Ăn uống", "tôi", None, {"tôi", "nam", "lan"}, "chia_deu"),
    ("đi xem phim 240k, Nam 120k tôi 120k, tôi trả", "chi_chung", 240_000, "Giải trí", "tôi", None, {"tôi", "nam"}, "ghi_ro"),
    ("trả chị Mai 1tr", "tra_no", 1_000_000, None, "tôi", "mai", None, None),
]


def n(x):
    return normalize_name(x) if x else None


def main() -> int:
    load_dotenv()
    try:
        parser = ClaudeParser()
    except AIUnavailable as exc:
        print(f"Lỗi: {exc}")
        return 1

    ok_count = 0
    for text, kind, amount, cat, payer, receiver, participants, split in CASES:
        p = parser.parse(text)
        problems = []
        if p.kind != kind:
            problems.append(f"kind={p.kind} (cần {kind})")
        try:
            got = parse_amount(p.amount_text or "")
        except Exception:
            got = None
        if got != amount:
            problems.append(f"tiền={p.amount_text!r} (cần {amount})")
        if cat and p.category != cat:
            problems.append(f"nhóm={p.category} (cần {cat})")
        if payer and n(p.payer) != payer:
            problems.append(f"người trả={p.payer} (cần {payer})")
        if receiver and n(p.receiver) != receiver:
            problems.append(f"người nhận={p.receiver} (cần {receiver})")
        if participants is not None and {n(x) for x in p.participants} != participants:
            problems.append(f"cùng chia={p.participants} (cần {sorted(participants)})")
        if split and p.split_mode != split:
            problems.append(f"cách chia={p.split_mode} (cần {split})")
        status = "ĐÚNG" if not problems else "SAI "
        ok_count += not problems
        print(f"[{status}] {text}")
        for pr in problems:
            print(f"        - {pr}")
    print(f"\n{ok_count}/{len(CASES)} câu đúng")
    return 0 if ok_count == len(CASES) else 2


if __name__ == "__main__":
    raise SystemExit(main())
