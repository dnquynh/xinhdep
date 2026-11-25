"""Test luồng hội thoại của bot.

AI được thay bằng FakeParser trả về kết quả định sẵn cho từng câu, để kiểm tra phần
code của bot (hỏi lại, chia tiền, ghi sổ, công nợ) mà không gọi API thật. Việc AI
hiểu câu có đúng không được kiểm tra riêng bằng scripts/thu_ai_that.py với key thật.
"""

from datetime import date

import pytest

from thuchi.ai_parser import AIUnavailable, ParsedMessage, Share
from thuchi.bot import Bot, parse_shares_reply
from thuchi.store import Ledger

CHAT = "u1"


def pm(kind, amount_text=None, category=None, note="", payer=None, receiver=None, participants=(), split_mode="chua_noi", shares=()):
    return ParsedMessage(
        kind=kind,
        amount_text=amount_text,
        category=category,
        note=note,
        payer=payer,
        receiver=receiver,
        participants=list(participants),
        split_mode=split_mode,
        shares=[Share(name=n, amount_text=a) for n, a in shares],
    )


class FakeParser:
    def __init__(self, table):
        self.table = table
        self.calls = []

    def parse(self, text):
        self.calls.append(text)
        if text not in self.table:
            raise AssertionError(f"FakeParser chưa có câu: {text!r}")
        return self.table[text]


SEVEN = {
    "ăn lẩu 600k, tôi trả, chia với Nam và Lan": pm(
        "chi_chung", "600k", "Ăn uống", "ăn lẩu", payer="tôi", participants=["tôi", "Nam", "Lan"]
    ),
    "Nam trả tiền taxi 120k cho tôi với Nam": pm(
        "chi_chung", "120k", "Đi lại", "taxi", payer="Nam", participants=["tôi", "Nam"]
    ),
    "cho Hùng mượn 2tr": pm("cho_vay", "2tr", payer="tôi", receiver="Hùng"),
    "Hùng trả 500k": pm("tra_no", "500k", payer="Hùng", receiver="tôi"),
    "vay chị Mai 1tr5": pm("di_vay", "1tr5", payer="chị Mai", receiver="tôi"),
    "lương tháng 11 15tr": pm("thu", "15tr", "Thu nhập", "lương tháng 11"),
    "tiền điện 450k": pm("chi", "450k", "Nhà ở và điện nước", "tiền điện", payer="tôi"),
}


@pytest.fixture
def ledger():
    lg = Ledger(":memory:")
    yield lg
    lg.close()


def make_bot(ledger, table):
    return Bot(ledger, FakeParser(table), today=lambda: date(2026, 11, 25))


def chat(bot, *messages):
    return [bot.handle(CHAT, m) for m in messages]


# ---------------------------------------------------------------- 7 câu mẫu


def test_seven_examples_full_conversation(ledger):
    bot = make_bot(ledger, SEVEN)
    r = chat(
        bot,
        "ăn lẩu 600k, tôi trả, chia với Nam và Lan",
        "thêm",  # Nam là người mới
        "thêm",  # Lan là người mới
        "ok",  # chia đều
        "Nam trả tiền taxi 120k cho tôi với Nam",
        "ok",
        "cho Hùng mượn 2tr",
        "thêm",
        "Hùng trả 500k",
        "vay chị Mai 1tr5",
        "thêm",
        "lương tháng 11 15tr",
        "tiền điện 450k",
    )
    assert '"Nam" là ai?' in r[0]
    assert '"Lan" là ai?' in r[1]
    assert "Chia đều" in r[2] and "nhé?" in r[2]
    assert r[3].startswith("Đã ghi: ăn lẩu 600.000đ")
    assert "Nam nợ bạn 200.000đ" in r[3] and "Lan nợ bạn 200.000đ" in r[3]
    assert "Chia đều" in r[4]
    assert "Nam nợ bạn 140.000đ" in r[5]
    assert '"Hùng" là ai?' in r[6]
    assert "Hùng nợ bạn 2.000.000đ" in r[7]
    assert "Hùng nợ bạn 1.500.000đ" in r[8]
    assert '"chị Mai" là ai?' in r[9]
    assert "Bạn nợ Mai 1.500.000đ" in r[10]
    assert r[11].startswith("Đã ghi: thu lương tháng 11 15.000.000đ")
    assert r[12] == "Đã ghi: tiền điện 450.000đ · Nhà ở và điện nước"

    summary = bot.handle(CHAT, "tổng kết")
    assert "Tổng kết tháng 11/2026" in summary
    assert "- Nhà ở và điện nước: 450.000đ" in summary
    assert "- Ăn uống: 200.000đ" in summary
    assert "- Đi lại: 60.000đ" in summary
    assert "Tổng chi: 710.000đ" in summary
    assert "Tổng thu: 15.000.000đ" in summary
    assert "Còn lại: 14.290.000đ" in summary
    assert "Trả gọn (3 lần chuyển thay vì 4)" in summary
    assert "- Hùng chuyển Mai 1.500.000đ" in summary

    debts = bot.handle(CHAT, "công nợ")
    assert "- Bạn nợ Mai 1.500.000đ" in debts
    assert "- Nam nợ bạn 140.000đ" in debts


# ---------------------------------------------------------------- chia tiền


def test_split_always_asked_without_chia_deu(ledger):
    ledger.add_person("Nam")
    bot = make_bot(ledger, {"lẩu 300k với Nam": pm("chi_chung", "300k", "Ăn uống", "lẩu", "tôi", participants=["tôi", "Nam"])})
    r = bot.handle(CHAT, "lẩu 300k với Nam")
    assert "Chia đều (bạn 150.000đ, Nam 150.000đ) nhé?" in r
    assert ledger.transactions() == []


def test_ai_saying_chia_deu_is_ignored_unless_text_says_so(ledger):
    """Quy tắc b: AI có báo chia_deu mà câu không có chữ 'chia đều' thì vẫn hỏi."""
    ledger.add_person("Nam")
    bot = make_bot(
        ledger,
        {
            "lẩu 300k chia với Nam": pm("chi_chung", "300k", "Ăn uống", "lẩu", "tôi", participants=["tôi", "Nam"], split_mode="chia_deu"),
            "lẩu 300k chia đều với Nam": pm("chi_chung", "300k", "Ăn uống", "lẩu", "tôi", participants=["tôi", "Nam"], split_mode="chia_deu"),
        },
    )
    assert "nhé?" in bot.handle(CHAT, "lẩu 300k chia với Nam")
    bot.handle(CHAT, "hủy")
    assert bot.handle(CHAT, "lẩu 300k chia đều với Nam").startswith("Đã ghi")


def test_split_reply_with_exact_amounts(ledger):
    ledger.add_person("Nam")
    ledger.add_person("Lan")
    bot = make_bot(ledger, {"lẩu 600k": pm("chi_chung", "600k", "Ăn uống", "lẩu", "tôi", participants=["tôi", "Nam", "Lan"])})
    bot.handle(CHAT, "lẩu 600k")
    r = bot.handle(CHAT, "Nam 250k, Lan 250k, tôi 100k")
    assert r.startswith("Đã ghi")
    assert ledger.balance_with_me(ledger.resolve("Nam")) == 250_000
    assert ledger.month_summary(*_ym(ledger)).expense_by_category == {"Ăn uống": 100_000}


def test_split_reply_mismatch_asks_again(ledger):
    ledger.add_person("Nam")
    bot = make_bot(ledger, {"lẩu 600k": pm("chi_chung", "600k", "Ăn uống", "lẩu", "tôi", participants=["tôi", "Nam"])})
    bot.handle(CHAT, "lẩu 600k")
    r = bot.handle(CHAT, "Nam 250k, tôi 100k")
    assert "Mới chia 350.000đ/600.000đ, còn 250.000đ của ai?" in r
    r = bot.handle(CHAT, "Nam 300k, tôi 300k")
    assert r.startswith("Đã ghi")


def test_exact_split_in_first_message(ledger):
    ledger.add_person("Nam")
    bot = make_bot(
        ledger,
        {
            "lẩu 600k Nam 400k tôi 200k": pm(
                "chi_chung", "600k", "Ăn uống", "lẩu", "tôi", participants=["tôi", "Nam"], split_mode="ghi_ro",
                shares=[("Nam", "400k"), ("tôi", "200k")],
            )
        },
    )
    assert bot.handle(CHAT, "lẩu 600k Nam 400k tôi 200k").startswith("Đã ghi")
    assert ledger.balance_with_me(ledger.resolve("Nam")) == 400_000


def test_pay_for_one_person_no_question(ledger):
    ledger.add_person("Lan")
    bot = make_bot(ledger, {"Lan mua hộ tôi sách 80k": pm("chi_chung", "80k", "Học tập", "sách", "Lan", participants=["tôi"])})
    r = bot.handle(CHAT, "Lan mua hộ tôi sách 80k")
    assert r.startswith("Đã ghi") and "Bạn nợ Lan 80.000đ" in r


def test_shared_without_others_becomes_personal(ledger):
    bot = make_bot(ledger, {"cafe 30k tôi trả": pm("chi_chung", "30k", "Ăn uống", "cafe", "tôi", participants=["tôi"])})
    assert bot.handle(CHAT, "cafe 30k tôi trả").startswith("Đã ghi: cafe 30.000đ · Ăn uống")
    assert ledger.transactions()[0].kind == "chi"


def test_missing_payer_asked(ledger):
    ledger.add_person("Nam")
    bot = make_bot(ledger, {"taxi 100k với Nam": pm("chi_chung", "100k", "Đi lại", "taxi", None, participants=["tôi", "Nam"])})
    assert "ai trả tiền?" in bot.handle(CHAT, "taxi 100k với Nam")
    assert "nhé?" in bot.handle(CHAT, "Nam")
    r = bot.handle(CHAT, "ok")
    assert "Bạn nợ Nam 50.000đ" in r


# ---------------------------------------------------------------- hỏi lại số tiền, nhóm, người


def test_ambiguous_amount_asked(ledger):
    bot = make_bot(ledger, {"tiền nước 450": pm("chi", "450", "Nhà ở và điện nước", "tiền nước", "tôi")})
    r = bot.handle(CHAT, "tiền nước 450")
    assert "450 nghìn" in r and "450 đồng" in r
    assert bot.handle(CHAT, "nghìn").startswith("Đã ghi: tiền nước 450.000đ")


def test_missing_amount_asked(ledger):
    bot = make_bot(ledger, {"mua giày": pm("chi", None, "Mua sắm", "mua giày", "tôi")})
    assert bot.handle(CHAT, "mua giày") == "Khoản này bao nhiêu tiền?"
    assert "1.200.000đ" in bot.handle(CHAT, "1tr2")


def test_category_asked_when_ai_unsure(ledger):
    bot = make_bot(ledger, {"đồ linh tinh 200k": pm("chi", "200k", None, "đồ linh tinh", "tôi")})
    r = bot.handle(CHAT, "đồ linh tinh 200k")
    assert "thuộc nhóm nào?" in r and "4. Mua sắm" in r
    assert bot.handle(CHAT, "4") == "Đã ghi: đồ linh tinh 200.000đ · Mua sắm"


def test_category_reply_by_name_without_accents(ledger):
    bot = make_bot(ledger, {"x 200k": pm("chi", "200k", "Không có nhóm này", "x", "tôi")})
    bot.handle(CHAT, "x 200k")
    assert "Giải trí" in bot.handle(CHAT, "giai tri")


def test_unknown_person_alias_to_existing(ledger):
    nam = ledger.add_person("Nam")
    bot = make_bot(ledger, {"cho Nam béo mượn 100k": pm("cho_vay", "100k", payer="tôi", receiver="Nam béo")})
    assert '"Nam béo" là ai?' in bot.handle(CHAT, "cho Nam béo mượn 100k")
    r = bot.handle(CHAT, "Nam")
    assert "Nam nợ bạn 100.000đ" in r
    assert ledger.resolve("nam béo") == nam


def test_loan_without_borrower_asked(ledger):
    ledger.add_person("Hùng")
    bot = make_bot(ledger, {"cho mượn 1tr": pm("cho_vay", "1tr", payer="tôi", receiver=None)})
    assert "Cho ai mượn" in bot.handle(CHAT, "cho mượn 1tr")
    assert "Hùng nợ bạn 1.000.000đ" in bot.handle(CHAT, "Hùng")


# ---------------------------------------------------------------- trả nợ


def test_repayment_excess_asked_then_confirmed(ledger):
    hung = ledger.add_person("Hùng")
    ledger.add_loan(ledger.me, hung, 1_000_000)
    bot = make_bot(ledger, {"Hùng trả 1tr5": pm("tra_no", "1tr5", payer="Hùng", receiver="tôi")})
    r = bot.handle(CHAT, "Hùng trả 1tr5")
    assert "Hùng đang nợ bạn 1.000.000đ" in r and "dư 500.000đ" in r
    r = bot.handle(CHAT, "ok")
    assert "Bạn nợ Hùng 500.000đ" in r


def test_repayment_excess_cancel(ledger):
    hung = ledger.add_person("Hùng")
    ledger.add_loan(ledger.me, hung, 1_000_000)
    bot = make_bot(ledger, {"Hùng trả 1tr5": pm("tra_no", "1tr5", payer="Hùng", receiver="tôi")})
    bot.handle(CHAT, "Hùng trả 1tr5")
    assert bot.handle(CHAT, "không") == "Đã bỏ, không ghi gì."
    assert ledger.balance_with_me(hung) == 1_000_000


def test_repay_to_full_shows_cleared(ledger):
    hung = ledger.add_person("Hùng")
    ledger.add_loan(ledger.me, hung, 500_000)
    bot = make_bot(ledger, {"Hùng trả 500k": pm("tra_no", "500k", payer="Hùng", receiver="tôi")})
    assert "Hùng với bạn hết nợ" in bot.handle(CHAT, "Hùng trả 500k")


# ---------------------------------------------------------------- lệnh


def test_delete_last(ledger):
    bot = make_bot(ledger, SEVEN)
    bot.handle(CHAT, "tiền điện 450k")
    assert bot.handle(CHAT, "xóa cái vừa ghi") == "Đã xóa: tiền điện 450.000đ · Nhà ở và điện nước"
    assert ledger.transactions() == []
    assert bot.handle(CHAT, "xóa") == "Chưa có khoản nào để xóa."


def test_edit_last(ledger):
    table = dict(SEVEN)
    table["tiền điện 480k"] = pm("chi", "480k", "Nhà ở và điện nước", "tiền điện", "tôi")
    bot = make_bot(ledger, table)
    bot.handle(CHAT, "tiền điện 450k")
    r = bot.handle(CHAT, "sửa: tiền điện 480k")
    assert r == "Đã sửa: tiền điện 480.000đ · Nhà ở và điện nước"
    txs = ledger.transactions()
    assert len(txs) == 1 and txs[0].amount == 480_000


def test_edit_last_keeps_old_until_new_is_complete(ledger):
    table = dict(SEVEN)
    table["tiền điện 480"] = pm("chi", "480", "Nhà ở và điện nước", "tiền điện", "tôi")
    bot = make_bot(ledger, table)
    bot.handle(CHAT, "tiền điện 450k")
    assert "480 nghìn" in bot.handle(CHAT, "sửa: tiền điện 480")
    assert ledger.transactions()[0].amount == 450_000  # chưa xóa khi còn đang hỏi
    bot.handle(CHAT, "nghìn")
    assert [t.amount for t in ledger.transactions()] == [480_000]


def test_summary_other_month(ledger):
    bot = make_bot(ledger, {})
    assert "Tổng kết tháng 10/2026" in bot.handle(CHAT, "tổng kết tháng 10")
    assert "Tổng kết tháng 12/2025" in bot.handle(CHAT, "tổng kết tháng 12")  # tháng 12 chưa tới -> năm trước
    assert "Tổng kết tháng 3/2025" in bot.handle(CHAT, "tổng kết 3/2025")


def test_cancel_and_new_message_drops_pending(ledger):
    ledger.add_person("Nam")
    table = {
        "lẩu 300k với Nam": pm("chi_chung", "300k", "Ăn uống", "lẩu", "tôi", participants=["tôi", "Nam"]),
        "tiền điện 450k": SEVEN["tiền điện 450k"],
    }
    bot = make_bot(ledger, table)
    bot.handle(CHAT, "lẩu 300k với Nam")
    r = bot.handle(CHAT, "tiền điện 450k")
    assert r.startswith('(Bỏ khoản chưa ghi: "lẩu 300k với Nam")')
    assert "Đã ghi: tiền điện" in r
    assert bot.handle(CHAT, "hủy") == "Không có gì đang chờ để hủy."


def test_not_understood(ledger):
    bot = make_bot(ledger, {"hôm nay trời đẹp": pm("khong_ro")})
    assert "chưa hiểu" in bot.handle(CHAT, "hôm nay trời đẹp")


def test_ai_unavailable_message(ledger):
    class Down:
        def parse(self, text):
            raise AIUnavailable("Không kết nối được AI")

    bot = Bot(ledger, Down())
    assert bot.handle(CHAT, "tiền điện 450k") == "Chưa ghi được: Không kết nối được AI."


def test_pending_is_per_chat(ledger):
    ledger.add_person("Nam")
    bot = make_bot(ledger, {"lẩu 300k với Nam": pm("chi_chung", "300k", "Ăn uống", "lẩu", "tôi", participants=["tôi", "Nam"])})
    bot.handle("a", "lẩu 300k với Nam")
    assert bot.handle("b", "hủy") == "Không có gì đang chờ để hủy."
    assert bot.handle("a", "ok").startswith("Đã ghi")


def test_parse_shares_reply():
    assert parse_shares_reply("Nam 250k, Lan 250k, tôi 100k") == [("Nam", "250k"), ("Lan", "250k"), ("tôi", "100k")]
    assert parse_shares_reply("anh Nam: 1tr2 và tôi 300k") == [("anh Nam", "1tr2"), ("tôi", "300k")]
    assert parse_shares_reply("ok") == []
    assert parse_shares_reply("250k") == []


def _ym(ledger):
    d = date.today()
    t = ledger.transactions()
    if t:
        y, m, _ = t[0].occurred_on.split("-")
        return int(y), int(m)
    return d.year, d.month
