from datetime import date

import pytest

from thuchi.debts import Debt
from thuchi.money import parse_amount
from thuchi.splits import SplitError, SplitMismatch
from thuchi.store import Ledger, LedgerError, UnknownCategory, UnknownPerson, normalize_name

NOV = date(2026, 11, 20)


@pytest.fixture
def ledger():
    lg = Ledger(":memory:")
    yield lg
    lg.close()


@pytest.fixture
def people(ledger):
    return {
        "nam": ledger.add_person("Nam"),
        "lan": ledger.add_person("Lan"),
        "hung": ledger.add_person("Hùng"),
        "mai": ledger.add_person("Mai"),
    }


def _names(debts):
    return [(d.debtor.name, d.creditor.name, d.amount) for d in debts]


# ---------------------------------------------------------------- tên người


@pytest.mark.parametrize(
    "raw, expected",
    [("Nam", "nam"), ("anh Nam", "nam"), ("  NAM ", "nam"), ("chị Mai", "mai"), ("c Mai", "mai"), ("Lân", "lân")],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_aliases_resolve_to_same_person(ledger):
    nam = ledger.add_person("Nam")
    assert ledger.resolve("anh Nam") == nam
    assert ledger.resolve("nam") == nam
    assert ledger.find_person("Lân") is None  # khác dấu là người khác


def test_self_words_resolve_to_me(ledger):
    for w in ("tôi", "Tôi", "mình", "tớ"):
        assert ledger.resolve(w).is_me


def test_unknown_person_raises_for_bot_to_ask(ledger):
    with pytest.raises(UnknownPerson) as exc:
        ledger.resolve("Tuấn")
    assert exc.value.name == "Tuấn"


def test_add_alias_and_conflict(ledger):
    nam = ledger.add_person("Nam")
    lan = ledger.add_person("Lan")
    ledger.add_alias(nam, "Nam béo")
    assert ledger.resolve("nam béo") == nam
    with pytest.raises(LedgerError):
        ledger.add_alias(lan, "Nam")
    with pytest.raises(LedgerError):
        ledger.add_person("anh Nam")  # đã có


# ---------------------------------------------------------------- nhóm


def test_categories_seeded(ledger):
    assert ledger.categories("chi")[0] == "Ăn uống"
    assert "Hiếu hỉ" in ledger.categories("chi")
    assert ledger.categories("thu") == ["Thu nhập"]


def test_unknown_category(ledger):
    with pytest.raises(UnknownCategory):
        ledger.add_expense(100_000, "Du hành vũ trụ")
    with pytest.raises(UnknownCategory):
        ledger.add_expense(100_000, "Thu nhập")  # nhóm thu không dùng cho chi


def test_category_match_ignores_case(ledger):
    tx = ledger.add_expense(50_000, "ăn uống", on=NOV)
    assert tx.category == "Ăn uống"


# ---------------------------------------------------------------- chia tiền


def test_shared_equal(ledger, people):
    me = ledger.me
    tx = ledger.add_shared_equal(600_000, "Ăn uống", me, [me, people["nam"], people["lan"]], "lẩu", on=NOV)
    assert tx.splits == {me.id: 200_000, people["nam"].id: 200_000, people["lan"].id: 200_000}
    assert ledger.balance_with_me(people["nam"]) == 200_000
    assert ledger.balance_with_me(people["lan"]) == 200_000


def test_shared_exact(ledger, people):
    me = ledger.me
    ledger.add_shared_exact(
        600_000, "Ăn uống", me, {people["nam"]: 250_000, people["lan"]: 250_000, me: 100_000}, on=NOV
    )
    assert ledger.balance_with_me(people["nam"]) == 250_000
    assert ledger.month_summary(2026, 11).expense_by_category == {"Ăn uống": 100_000}


def test_shared_exact_mismatch_writes_nothing(ledger, people):
    me = ledger.me
    with pytest.raises(SplitMismatch):
        ledger.add_shared_exact(600_000, "Ăn uống", me, {people["nam"]: 250_000, me: 100_000})
    assert ledger.transactions() == []


def test_shared_needs_someone_else(ledger):
    me = ledger.me
    with pytest.raises(SplitError):
        ledger.add_shared_equal(100_000, "Ăn uống", me, [me])


def test_other_person_pays_for_others(ledger, people):
    # Nam trả 300k cho Nam và Lan: Lan nợ Nam, tôi không liên quan.
    ledger.add_shared_equal(300_000, "Giải trí", people["nam"], [people["nam"], people["lan"]], on=NOV)
    assert _names(ledger.debts()) == [("Lan", "Nam", 150_000)]
    assert ledger.balance_with_me(people["nam"]) == 0
    assert ledger.month_summary(2026, 11).expense_by_category == {}


# ---------------------------------------------------------------- vay, trả


def test_loan_partial_and_full_repayment(ledger, people):
    me, hung = ledger.me, people["hung"]
    ledger.add_loan(me, hung, 2_000_000, on=NOV)
    assert ledger.balance_with_me(hung) == 2_000_000

    ledger.add_repayment(hung, me, 500_000, on=NOV)
    assert ledger.balance_with_me(hung) == 1_500_000

    ledger.add_repayment(hung, me, 1_500_000, on=NOV)
    assert ledger.balance_with_me(hung) == 0
    assert ledger.debts() == []


def test_borrow_and_repay(ledger, people):
    me, mai = ledger.me, people["mai"]
    ledger.add_loan(mai, me, 1_500_000, on=NOV)  # tôi vay chị Mai
    assert ledger.balance_with_me(mai) == -1_500_000
    ledger.add_repayment(me, mai, 1_000_000, on=NOV)
    assert ledger.balance_with_me(mai) == -500_000


def test_repayment_excess_detected(ledger, people):
    me, hung = ledger.me, people["hung"]
    ledger.add_loan(me, hung, 2_000_000)
    assert ledger.repayment_excess(hung, me, 500_000) == 0
    assert ledger.repayment_excess(hung, me, 2_500_000) == 500_000
    assert ledger.repayment_excess(people["nam"], me, 100_000) == 100_000  # Nam không nợ gì


def test_loans_not_counted_in_income_expense(ledger, people):
    me = ledger.me
    ledger.add_loan(me, people["hung"], 2_000_000, on=NOV)
    ledger.add_loan(people["mai"], me, 1_500_000, on=NOV)
    ledger.add_repayment(people["hung"], me, 500_000, on=NOV)
    s = ledger.month_summary(2026, 11)
    assert s.total_expense == 0 and s.total_income == 0


def test_invalid_amounts_rejected(ledger, people):
    with pytest.raises(LedgerError):
        ledger.add_expense(0, "Ăn uống")
    with pytest.raises(LedgerError):
        ledger.add_expense(1.5, "Ăn uống")  # không nhận float
    with pytest.raises(LedgerError):
        ledger.add_loan(ledger.me, ledger.me, 100_000)


# ---------------------------------------------------------------- xóa


def test_delete_last_reverts_debt(ledger, people):
    me, hung = ledger.me, people["hung"]
    ledger.add_loan(me, hung, 2_000_000)
    ledger.add_repayment(hung, me, 500_000)
    removed = ledger.delete_last()
    assert removed.kind == "tra_no"
    assert ledger.balance_with_me(hung) == 2_000_000
    assert ledger.last_transaction().kind == "vay"


def test_delete_last_on_empty(ledger):
    assert ledger.delete_last() is None


def test_data_persists_in_file(tmp_path):
    path = tmp_path / "thuchi.db"
    lg = Ledger(path)
    nam = lg.add_person("Nam")
    lg.add_shared_equal(100_000, "Đi lại", lg.me, [lg.me, nam])
    lg.close()

    lg2 = Ledger(path)
    assert lg2.balance_with_me(lg2.resolve("Nam")) == 50_000
    assert len(lg2.people()) == 2  # không tạo thêm "tôi" lần nữa
    lg2.close()


# ---------------------------------------------------------------- 7 câu mẫu


def record_seven_examples(lg: Ledger) -> dict:
    """Ghi 7 câu mẫu đúng như bot sẽ ghi sau khi AI hiểu câu và bạn xác nhận cách chia."""
    me = lg.me
    nam, lan, hung, mai = (lg.add_person(n) for n in ("Nam", "Lan", "Hùng", "Mai"))

    # 1. "ăn lẩu 600k, tôi trả, chia với Nam và Lan" -> bot hỏi, trả lời "ok" chia đều
    lg.add_shared_equal(parse_amount("600k"), "Ăn uống", me, [me, nam, lan], "ăn lẩu", on=NOV)
    # 2. "Nam trả tiền taxi 120k cho tôi với Nam" -> bot hỏi, trả lời "ok" chia đều
    lg.add_shared_equal(parse_amount("120k"), "Đi lại", nam, [me, nam], "taxi", on=NOV)
    # 3. "cho Hùng mượn 2tr"
    lg.add_loan(me, hung, parse_amount("2tr"), on=NOV)
    # 4. "Hùng trả 500k"
    lg.add_repayment(hung, me, parse_amount("500k"), on=NOV)
    # 5. "vay chị Mai 1tr5"
    lg.add_loan(lg.resolve("chị Mai"), me, parse_amount("1tr5"), on=NOV)
    # 6. "lương tháng 11 15tr"
    lg.add_income(parse_amount("15tr"), "Thu nhập", "lương tháng 11", on=NOV)
    # 7. "tiền điện 450k"
    lg.add_expense(parse_amount("450k"), "Nhà ở và điện nước", "tiền điện", on=NOV)
    return {"nam": nam, "lan": lan, "hung": hung, "mai": mai}


def test_seven_examples_debts(ledger):
    p = record_seven_examples(ledger)
    assert ledger.balance_with_me(p["nam"]) == 140_000
    assert ledger.balance_with_me(p["lan"]) == 200_000
    assert ledger.balance_with_me(p["hung"]) == 1_500_000
    assert ledger.balance_with_me(p["mai"]) == -1_500_000

    assert sorted(_names(ledger.debts())) == sorted(
        [
            ("Hùng", "Tôi", 1_500_000),
            ("Tôi", "Mai", 1_500_000),
            ("Lan", "Tôi", 200_000),
            ("Nam", "Tôi", 140_000),
        ]
    )


def test_seven_examples_simplified(ledger):
    record_seven_examples(ledger)
    simplified = ledger.simplified_debts()
    assert len(simplified) == 3
    assert sorted(_names(simplified)) == sorted(
        [("Hùng", "Mai", 1_500_000), ("Lan", "Tôi", 200_000), ("Nam", "Tôi", 140_000)]
    )


def test_seven_examples_month_summary(ledger):
    record_seven_examples(ledger)
    s = ledger.month_summary(2026, 11)
    assert s.expense_by_category == {"Ăn uống": 200_000, "Đi lại": 60_000, "Nhà ở và điện nước": 450_000}
    assert s.total_expense == 710_000
    assert s.income_by_category == {"Thu nhập": 15_000_000}
    assert s.net == 14_290_000
    # Tháng khác không có gì
    assert ledger.month_summary(2026, 10).total_expense == 0


def test_summary_total_matches_raw_rows(ledger):
    """Tổng kết khớp với dữ liệu thô: cộng lại phần của tôi từ bảng splits."""
    record_seven_examples(ledger)
    me = ledger.me.id
    raw = ledger.db.execute(
        """SELECT COALESCE(SUM(s.amount), 0) FROM splits s JOIN transactions t ON t.id = s.transaction_id
           WHERE s.person_id = ? AND t.kind IN ('chi', 'chi_chung') AND t.deleted_at IS NULL""",
        (me,),
    ).fetchone()[0]
    assert ledger.month_summary(2026, 11).total_expense == raw
