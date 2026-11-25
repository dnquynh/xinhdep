"""Test bộ hiểu tin nhắn bằng quy tắc (miễn phí, không cần AI)."""

from datetime import date

import pytest

from thuchi.bot import Bot
from thuchi.money import parse_amount
from thuchi.rule_parser import RuleParser, find_amounts, guess_category
from thuchi.store import Ledger, normalize_name


@pytest.fixture
def ledger():
    lg = Ledger(":memory:")
    yield lg
    lg.close()


@pytest.fixture
def known(ledger):
    for n in ("Nam", "Lan", "Hùng"):
        ledger.add_person(n)
    return ledger


def n(x):
    return normalize_name(x) if x else None


# (câu, kind, số tiền, nhóm, người trả, người nhận, người cùng dùng, cách chia)
CASES = [
    # 7 câu mẫu
    ("ăn lẩu 600k, tôi trả, chia với Nam và Lan", "chi_chung", 600_000, "Ăn uống", "tôi", None, ["tôi", "nam", "lan"], "chua_noi"),
    ("Nam trả tiền taxi 120k cho tôi với Nam", "chi_chung", 120_000, "Đi lại", "nam", None, ["tôi", "nam"], "chua_noi"),
    ("cho Hùng mượn 2tr", "cho_vay", 2_000_000, None, "tôi", "hùng", [], None),
    ("Hùng trả 500k", "tra_no", 500_000, None, "hùng", "tôi", [], None),
    ("vay chị Mai 1tr5", "di_vay", 1_500_000, None, "mai", "tôi", [], None),
    ("lương tháng 11 15tr", "thu", 15_000_000, "Thu nhập", None, None, [], None),
    ("tiền điện 450k", "chi", 450_000, "Nhà ở và điện nước", "tôi", None, [], None),
    # chia tiền
    ("ăn lẩu 600k chia đều với Nam và Lan, tôi trả", "chi_chung", 600_000, "Ăn uống", "tôi", None, ["tôi", "nam", "lan"], "chia_deu"),
    ("cafe với Lan 60k chia đôi", "chi_chung", 60_000, "Ăn uống", None, None, ["tôi", "lan"], "chia_deu"),
    ("đi xem phim 240k, Nam 120k tôi 120k, tôi trả", "chi_chung", 240_000, "Giải trí", "tôi", None, ["tôi", "nam"], "ghi_ro"),
    ("Nam 250k, Lan 250k, tôi 100k tiền lẩu", "chi_chung", 600_000, "Ăn uống", None, None, ["tôi", "nam", "lan"], "ghi_ro"),
    ("Lan mua hộ tôi sách 80k", "chi_chung", 80_000, "Học tập", "lan", None, ["tôi"], "chua_noi"),
    ("Nam bao trà sữa 90k cho tôi với Lan", "chi_chung", 90_000, "Ăn uống", "nam", None, ["tôi", "lan"], "chua_noi"),
    ("ăn trưa 3 người 150k với Nam và Lan, Nam trả", "chi_chung", 150_000, "Ăn uống", "nam", None, ["tôi", "nam", "lan"], "chua_noi"),
    # tên viết thường nhưng đã có trong sổ
    ("ăn lẩu 600k với nam và lan", "chi_chung", 600_000, "Ăn uống", None, None, ["tôi", "nam", "lan"], "chua_noi"),
    ("cho nam vay 500k", "cho_vay", 500_000, None, "tôi", "nam", [], None),
    ("nam trả 200k", "tra_no", 200_000, None, "nam", "tôi", [], None),
    # vay, trả
    ("tôi trả nam 100k", "tra_no", 100_000, None, "tôi", "nam", [], None),
    ("trả chị Mai 1tr", "tra_no", 1_000_000, None, "tôi", "mai", [], None),
    ("mượn Hùng 300k", "di_vay", 300_000, None, "hùng", "tôi", [], None),
    ("Hùng cho tôi mượn 1tr", "di_vay", 1_000_000, None, "hùng", "tôi", [], None),
    # chi cá nhân, nhiều kiểu viết
    ("grab 85k", "chi", 85_000, "Đi lại", "tôi", None, [], None),
    ("450k tiền điện", "chi", 450_000, "Nhà ở và điện nước", "tôi", None, [], None),
    ("mua áo 350k", "chi", 350_000, "Mua sắm", "tôi", None, [], None),
    ("đám cưới bạn 500k", "chi", 500_000, "Hiếu hỉ", "tôi", None, [], None),
    ("đi siêu thị 1.250.000đ", "chi", 1_250_000, "Mua sắm", "tôi", None, [], None),
    ("tiền nhà tháng 12 3tr5", "chi", 3_500_000, "Nhà ở và điện nước", "tôi", None, [], None),
    ("khám răng 1tr2", "chi", 1_200_000, "Sức khỏe", "tôi", None, [], None),
    ("cafe 30k", "chi", 30_000, "Ăn uống", "tôi", None, [], None),
    # thu nhập
    ("thưởng tết 5tr", "thu", 5_000_000, "Thu nhập", None, None, [], None),
    ("nhận lương 12tr", "thu", 12_000_000, "Thu nhập", None, None, [], None),
]


@pytest.mark.parametrize("text, kind, amount, cat, payer, receiver, participants, split", CASES, ids=[c[0] for c in CASES])
def test_parse(known, text, kind, amount, cat, payer, receiver, participants, split):
    p = RuleParser(known).parse(text)
    assert p.kind == kind
    assert parse_amount(p.amount_text) == amount
    if cat is not None:
        assert p.category == cat
    if payer is not None:
        assert n(p.payer) == payer
    if receiver is not None:
        assert n(p.receiver) == receiver
    assert sorted(n(x) for x in p.participants) == sorted(participants)
    if split is not None:
        assert p.split_mode == split


def test_not_money(ledger):
    assert RuleParser(ledger).parse("hôm nay trời đẹp").kind == "khong_ro"


def test_ambiguous_amount_kept_for_bot_to_ask(ledger):
    p = RuleParser(ledger).parse("tiền nước 450")
    assert p.amount_text == "450"


def test_find_amounts_skips_non_money():
    assert [r for _, _, r in find_amounts("lương tháng 11 15tr")] == ["15tr"]
    assert [r for _, _, r in find_amounts("ăn trưa 3 người 150k")] == ["150k"]
    assert [r for _, _, r in find_amounts("Lan 250k")] == ["250k"]  # "lan" không bị nhầm là "lần"


def test_guess_category_prefers_longer_keyword():
    assert guess_category("tiền nước") == "Nhà ở và điện nước"
    assert guess_category("nước ngọt") == "Ăn uống"
    assert guess_category("mua cơm") == "Ăn uống"  # "mua" chỉ dùng khi không có gì khác
    assert guess_category("đồ linh tinh") == "Mua sắm"
    assert guess_category("xyz") is None


def test_learned_hint_wins(ledger):
    ledger.learn_category("tiền ship", "Mua sắm")
    p = RuleParser(ledger).parse("tiền ship 25k")
    assert p.category == "Mua sắm"


def test_bot_learns_category_from_answer(ledger):
    bot = Bot(ledger, RuleParser(ledger), today=lambda: date(2026, 11, 25))
    r = bot.handle("u", "phí abc 50k")
    assert "thuộc nhóm nào?" in r
    bot.handle("u", "9")  # Khác
    assert bot.handle("u", "phí abc 70k") == "Đã ghi: phí abc 70.000đ · Khác"  # lần hai không hỏi nữa


def test_full_conversation_with_rule_parser(ledger):
    """Toàn bộ kịch bản scripts/cau_mau.txt chạy bằng bộ quy tắc, không cần key."""
    bot = Bot(ledger, RuleParser(ledger), today=lambda: date(2026, 11, 25))
    msgs = [
        "ăn lẩu 600k, tôi trả, chia với Nam và Lan", "thêm", "thêm", "ok",
        "Nam trả tiền taxi 120k cho tôi với Nam", "ok",
        "cho Hùng mượn 2tr", "thêm",
        "Hùng trả 500k",
        "vay chị Mai 1tr5", "thêm",
        "lương tháng 11 15tr",
        "tiền điện 450k",
    ]
    replies = [bot.handle("u", m) for m in msgs]
    assert all(not r.startswith("Chưa ghi được") for r in replies)
    s = bot.handle("u", "tổng kết")
    for line in [
        "- Nhà ở và điện nước: 450.000đ", "- Ăn uống: 200.000đ", "- Đi lại: 60.000đ",
        "Tổng chi: 710.000đ", "Tổng thu: 15.000.000đ", "Còn lại: 14.290.000đ",
        "- Bạn nợ Mai 1.500.000đ", "- Hùng nợ bạn 1.500.000đ", "- Lan nợ bạn 200.000đ", "- Nam nợ bạn 140.000đ",
        "Trả gọn (3 lần chuyển thay vì 4):", "- Hùng chuyển Mai 1.500.000đ",
    ]:
        assert line in s
