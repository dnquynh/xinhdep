"""Chạy thử chặng 1: ghi 7 câu mẫu rồi in công nợ và tổng kết tháng.

    python3 demo_chang1.py
"""

from tests.test_store import record_seven_examples
from thuchi.money import format_vnd
from thuchi.store import Ledger

EXAMPLES = [
    "ăn lẩu 600k, tôi trả, chia với Nam và Lan   (bot hỏi -> 'ok' chia đều)",
    "Nam trả tiền taxi 120k cho tôi với Nam      (bot hỏi -> 'ok' chia đều)",
    "cho Hùng mượn 2tr",
    "Hùng trả 500k",
    "vay chị Mai 1tr5",
    "lương tháng 11 15tr",
    "tiền điện 450k",
]


def main() -> None:
    lg = Ledger(":memory:")
    record_seven_examples(lg)

    print("Đã ghi:")
    for i, (text, tx) in enumerate(zip(EXAMPLES, lg.transactions()), 1):
        print(f"  {i}. {text}")
        print(f"     -> {tx.kind}, {format_vnd(tx.amount)}, nhóm: {tx.category or '-'}")

    print("\nCông nợ (ai nợ ai):")
    for d in lg.debts():
        print(f"  {d.debtor.name} nợ {d.creditor.name} {format_vnd(d.amount)}")

    print("\nGợi ý trả nợ ít lần chuyển nhất:")
    for d in lg.simplified_debts():
        print(f"  {d.debtor.name} chuyển cho {d.creditor.name} {format_vnd(d.amount)}")

    s = lg.month_summary(2026, 11)
    print(f"\nTổng kết tháng {s.month}/{s.year} (chỉ tính phần của bạn):")
    for name, amount in s.expense_by_category.items():
        print(f"  {name:<22}{format_vnd(amount):>14}")
    print(f"  {'Tổng chi':<22}{format_vnd(s.total_expense):>14}")
    print(f"  {'Tổng thu':<22}{format_vnd(s.total_income):>14}")
    print(f"  {'Còn lại':<22}{format_vnd(s.net):>14}")


if __name__ == "__main__":
    main()
