"""Xử lý hội thoại của bot: nhận một tin nhắn, trả về câu trả lời.

Không phụ thuộc Zalo: CLI và Zalo đều gọi Bot.handle(chat_id, text).
Bot hỏi lại khi thiếu hoặc không rõ: số tiền, nhóm, người, ai trả, cách chia, trả dư.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from .ai_parser import AIUnavailable, ParsedMessage, Parser
from .money import AmbiguousAmount, AmountError, format_vnd, parse_amount
from .splits import SplitError, SplitMismatch, split_equal
from .store import _HONORIFICS, Ledger, LedgerError, Person, Transaction, normalize_name, today_vn

HELP = """Mình ghi thu chi và công nợ cho bạn. Cứ nhắn tự nhiên:
- tiền điện 450k
- ăn lẩu 600k, tôi trả, chia đều với Nam và Lan
- cho Hùng mượn 2tr / Hùng trả 500k / vay chị Mai 1tr5
- lương 15tr

Lệnh:
- tổng kết (hoặc: tổng kết tháng 10)
- công nợ
- xóa (xóa khoản vừa ghi)
- sửa: <câu mới> (thay khoản vừa ghi)
- hủy (bỏ câu đang hỏi dở)"""

YES = {
    "ok", "oke", "okay", "okie", "ừ", "ừm", "uh", "ờ", "có", "co", "đúng", "dung", "được", "duoc",
    "đồng ý", "dong y", "chia đều", "chia deu", "y", "yes", "đúng rồi", "ok luôn", "chuẩn",
}
NO = {"không", "khong", "ko", "no", "thôi", "thoi", "hủy", "huỷ", "huy", "bỏ", "bo"}
ADD_WORDS = {"thêm", "them", "thêm mới", "them moi", "người mới", "nguoi moi"} | YES

KIND_LABEL = {"chi": "chi", "thu": "thu", "chi_chung": "chi chung", "vay": "vay", "tra_no": "trả nợ"}


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFC", text).strip().lower()
    s = re.sub(r"[!.?…]+$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _strip_accents(text: str) -> str:
    s = unicodedata.normalize("NFD", text)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


def _display_name(name: str) -> str:
    """'chị Mai' -> 'Mai' (giữ nguyên chữ hoa/thường của tên)."""
    words = name.strip().split()
    while len(words) > 1 and words[0].lower() in _HONORIFICS:
        words = words[1:]
    out = " ".join(words)
    return out[:1].upper() + out[1:]


def _split_names(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,|;|\bvà\b|\bvới\b|\bva\b|\bvoi\b)\s*", text.strip())
    return [p.strip() for p in parts if p.strip()]


def parse_shares_reply(text: str) -> list[tuple[str, str]]:
    """'Nam 250k, Lan 250k, tôi 100k' -> [('Nam','250k'), ('Lan','250k'), ('tôi','100k')]"""
    out: list[tuple[str, str]] = []
    for seg in re.split(r"[,;\n]|\s+và\s+|\s+va\s+", text):
        words = seg.replace(":", " ").split()
        if not words:
            continue
        idx = next((i for i, w in enumerate(words) if w[0].isdigit()), None)
        if idx is None or idx == 0:
            return []
        out.append((" ".join(words[:idx]), " ".join(words[idx:])))
    return out


class Bot:
    def __init__(self, ledger: Ledger, parser: Parser, today=today_vn):
        self.ledger = ledger
        self.parser = parser
        self.today = today

    # ================================================================ lối vào

    def handle(self, chat_id: str, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        low = _norm(text)

        pending = self.ledger.get_pending(chat_id)
        if pending:
            if low in NO:
                self.ledger.clear_pending(chat_id)
                return "Đã bỏ, không ghi gì."
            reply = self._answer(chat_id, pending, text)
            if reply is not None:
                return reply
            # Không phải câu trả lời: coi như tin mới, bỏ khoản đang hỏi dở.
            self.ledger.clear_pending(chat_id)
            dropped = f"(Bỏ khoản chưa ghi: \"{pending['raw']}\")\n"
            return dropped + self._handle_new(chat_id, text, low)

        if low in NO:
            return "Không có gì đang chờ để hủy."
        return self._handle_new(chat_id, text, low)

    def _handle_new(self, chat_id: str, text: str, low: str) -> str:
        if low in {"help", "giúp", "giup", "hướng dẫn", "huong dan", "/start", "/help"}:
            return HELP
        m = re.match(r"^(?:tổng kết|tong ket)\b(.*)$", low)
        if m:
            return self._summary(m.group(1))
        if re.match(r"^(?:công nợ|cong no|ai nợ|ai no|nợ nần|no nan)\b", low):
            return self._debts_report()
        if re.match(r"^(?:xóa|xoá|xoa|hoàn tác|hoan tac|undo)\b", low):
            return self._delete_last()
        m = re.match(r"^(?:sửa|sủa|sua)\b\s*[:\-]?\s*(.*)$", text.strip(), flags=re.IGNORECASE)
        if m:
            return self._edit_last(chat_id, m.group(1))
        return self._new_record(chat_id, text)

    # ================================================================ ghi mới

    def _new_record(self, chat_id: str, text: str, replace_id: int | None = None) -> str:
        try:
            parsed = self.parser.parse(text)
        except AIUnavailable as exc:
            return f"Chưa ghi được: {exc}."
        draft = self._draft_from(parsed, text)
        draft["replace_id"] = replace_id
        return self._process(chat_id, draft)

    @staticmethod
    def _draft_from(p: ParsedMessage, raw: str) -> dict:
        split_mode = p.split_mode
        if split_mode == "chia_deu" and not re.search(r"chia\s*(đều|deu|đôi|doi)", _norm(raw)):
            # Quy tắc đã chốt: chỉ chia đều khi bạn nói rõ "chia đều"/"chia đôi".
            split_mode = "chua_noi"
        return {
            "raw": raw,
            "kind": p.kind,
            "amount": None,
            "amount_text": p.amount_text,
            "category": p.category,
            "note": p.note,
            "payer": p.payer,
            "receiver": p.receiver,
            "participants": list(p.participants),
            "split_mode": split_mode,
            "shares": [[s.name, s.amount_text] for s in p.shares],
            "split_confirmed": False,
            "excess_ok": False,
        }

    def _ask(self, chat_id: str, d: dict, q: str, question: str, extra=None) -> str:
        d["q"] = q
        d["q_extra"] = extra
        self.ledger.set_pending(chat_id, d)
        return question

    def _person(self, name: str) -> Person | None:
        return self.ledger.find_person(name)

    def _unknown(self, names: list[str | None]) -> str | None:
        for n in names:
            if n and self._person(n) is None:
                return n
        return None

    def _process(self, chat_id: str, d: dict) -> str:
        lg = self.ledger
        kind = d["kind"]
        if kind == "khong_ro":
            lg.clear_pending(chat_id)
            return "Mình chưa hiểu tin này. Bạn ghi kiểu: \"tiền điện 450k\", \"cho Hùng mượn 2tr\". Nhắn \"help\" để xem thêm."

        # 1. Số tiền
        if d["amount"] is None:
            if not d["amount_text"]:
                return self._ask(chat_id, d, "amount", "Khoản này bao nhiêu tiền?")
            try:
                d["amount"] = parse_amount(d["amount_text"])
            except AmbiguousAmount as exc:
                num = re.sub(r"\D", "", d["amount_text"])
                return self._ask(chat_id, d, "amount", str(exc), extra=int(num) if num else None)
            except AmountError:
                return self._ask(chat_id, d, "amount", f"\"{d['amount_text']}\" là bao nhiêu tiền? Ghi lại giúp mình, ví dụ 150k.")

        # 2. Nhóm
        if kind == "thu":
            if d["category"] not in lg.categories("thu"):
                d["category"] = "Thu nhập"
        elif kind in ("chi", "chi_chung"):
            if d["category"] not in lg.categories("chi"):
                return self._ask_category(chat_id, d)

        # 3. Người
        if kind == "chi_chung":
            if not d["payer"]:
                return self._ask(chat_id, d, "payer", f"{self._label(d)}: ai trả tiền?")
        elif kind == "cho_vay":
            d["payer"] = d["payer"] or "tôi"
            if not d["receiver"]:
                return self._ask(chat_id, d, "receiver", f"Cho ai mượn {format_vnd(d['amount'])}?")
        elif kind == "di_vay":
            d["receiver"] = d["receiver"] or "tôi"
            if not d["payer"]:
                return self._ask(chat_id, d, "payer", f"Bạn vay ai {format_vnd(d['amount'])}?")
        elif kind == "tra_no":
            if not d["payer"] and not d["receiver"]:
                return self._ask(chat_id, d, "payer", f"Ai trả {format_vnd(d['amount'])}?")
            d["payer"] = d["payer"] or "tôi"
            d["receiver"] = d["receiver"] or "tôi"

        names = [d["payer"], d["receiver"], *d["participants"], *(s[0] for s in d["shares"])]
        unknown = self._unknown(names)
        if unknown:
            return self._ask(
                chat_id,
                d,
                "person",
                f"\"{unknown}\" là ai? Trả lời \"thêm\" để thêm người mới tên {_display_name(unknown)}, "
                f"hoặc ghi tên người đã có nếu đó là tên gọi khác.",
                extra=unknown,
            )

        # 4. Chia tiền
        if kind == "chi_chung":
            reply = self._check_split(chat_id, d)
            if reply is not None:
                return reply

        # 5. Trả nợ dư
        if kind == "tra_no" and not d["excess_ok"]:
            payer, receiver = self._person(d["payer"]), self._person(d["receiver"])
            excess = lg.repayment_excess(payer, receiver, d["amount"])
            if excess:
                owed = max(lg.debt_between(payer, receiver), 0)
                return self._ask(
                    chat_id,
                    d,
                    "excess",
                    f"{self._who(payer, True)} đang nợ {self._who(receiver)} {format_vnd(owed)}, "
                    f"trả {format_vnd(d['amount'])} là dư {format_vnd(excess)}. "
                    f"Vẫn ghi không? (ok / hủy)",
                )

        return self._commit(chat_id, d)

    def _ask_category(self, chat_id: str, d: dict) -> str:
        cats = self.ledger.categories("chi")
        lines = "\n".join(f"{i}. {c}" for i, c in enumerate(cats, 1))
        return self._ask(chat_id, d, "category", f"{self._label(d)} thuộc nhóm nào? Trả lời số:\n{lines}")

    def _check_split(self, chat_id: str, d: dict) -> str | None:
        lg = self.ledger
        payer = self._person(d["payer"])
        people: list[Person] = []
        for n in d["participants"]:
            p = self._person(n)
            if p not in people:
                people.append(p)

        if d["split_mode"] == "ghi_ro" and d["shares"]:
            shares: dict[Person, int] = {}
            for name, amount_text in d["shares"]:
                try:
                    amt = parse_amount(amount_text)
                except AmountError:
                    return self._ask_split(chat_id, d, people, payer, f"Không đọc được số tiền \"{amount_text}\".")
                p = self._person(name)
                shares[p] = shares.get(p, 0) + amt
            total = sum(shares.values())
            if total != d["amount"]:
                missing = d["amount"] - total
                if missing > 0:
                    msg = f"Mới chia {format_vnd(total)}/{format_vnd(d['amount'])}, còn {format_vnd(missing)} của ai?"
                else:
                    msg = f"Các phần cộng lại {format_vnd(total)}, nhiều hơn tổng {format_vnd(d['amount'])} là {format_vnd(-missing)}."
                d["shares"] = []
                return self._ask(chat_id, d, "split", msg + " Ghi lại cách chia giúp mình, ví dụ \"Nam 250k, tôi 100k\".")
            d["_shares"] = {p.id: a for p, a in shares.items() if a > 0}
            return None

        if not people or all(p.id == payer.id for p in people):
            if payer.is_me:
                d["kind"] = "chi"  # tôi trả cho riêng tôi
                return None
            return self._ask(chat_id, d, "participants", f"{self._who(payer, True)} trả {format_vnd(d['amount'])} cho những ai?")

        others = [p for p in people if p.id != payer.id]
        if len(people) == 1 and len(others) == 1:
            # Trả hộ đúng một người: người đó chịu cả, không cần hỏi.
            d["_shares"] = {others[0].id: d["amount"]}
            return None

        if d["split_mode"] == "chia_deu" or d["split_confirmed"]:
            d["_shares"] = split_equal(d["amount"], [p.id for p in people], payer.id)
            return None

        return self._ask_split(chat_id, d, people, payer)

    def _ask_split(self, chat_id: str, d: dict, people: list[Person], payer: Person, prefix: str = "") -> str:
        shares = split_equal(d["amount"], [p.id for p in people], payer.id) if people else {}
        preview = ", ".join(f"{self._who(self.ledger.person(pid))} {format_vnd(a)}" for pid, a in shares.items())
        names = ", ".join(self._who(p) for p in people)
        q = (
            f"{prefix + ' ' if prefix else ''}{self._label(d)}, {self._who(payer)} trả, có {names}. "
            f"Chia đều ({preview}) nhé?\n"
            f"Trả lời \"ok\", hoặc ghi cách chia, ví dụ \"Nam 250k, tôi 100k\"."
        )
        return self._ask(chat_id, d, "split", q)

    # ================================================================ trả lời câu hỏi

    def _answer(self, chat_id: str, d: dict, text: str) -> str | None:
        """Trả về câu trả lời của bot, hoặc None nếu tin này không phải câu trả lời."""
        q, extra = d.get("q"), d.get("q_extra")
        low = _norm(text)
        lg = self.ledger

        if q == "amount":
            if extra and re.search(r"\b(nghìn|nghin|ngàn|ngan|k)\b", low):
                d["amount"] = int(extra) * 1000
            elif extra and re.search(r"\b(đồng|dong|đ)\b", low):
                d["amount"] = int(extra)
            else:
                try:
                    d["amount"] = parse_amount(text)
                except AmbiguousAmount as exc:
                    return self._ask(chat_id, d, "amount", str(exc), extra=int(re.sub(r"\D", "", text) or 0) or None)
                except AmountError:
                    return None
            return self._process(chat_id, d)

        if q == "category":
            cats = lg.categories("chi")
            if low.isdigit() and 1 <= int(low) <= len(cats):
                d["category"] = cats[int(low) - 1]
            else:
                key = _strip_accents(low)
                match = [c for c in cats if key and key in _strip_accents(c.lower())]
                if len(match) != 1:
                    return None
                d["category"] = match[0]
            return self._process(chat_id, d)

        if q == "person":
            name = extra
            existing = self._person(text)
            if low in ADD_WORDS:
                lg.add_person(_display_name(name), aliases=(name,))
            elif existing is not None:
                lg.add_alias(existing, name)
            elif len(low.split()) <= 3 and not any(ch.isdigit() for ch in low):
                # Ghi một tên mới hẳn: thêm người đó, coi "name" là tên gọi khác.
                person = lg.add_person(_display_name(text))
                lg.add_alias(person, name)
            else:
                return None
            return self._process(chat_id, d)

        if q in ("payer", "receiver"):
            if len(low.split()) > 4 or any(ch.isdigit() for ch in low):
                return None
            d[q] = text.strip()
            return self._process(chat_id, d)

        if q == "participants":
            names = _split_names(text)
            if not names or any(any(ch.isdigit() for ch in n) for n in names):
                return None
            d["participants"] = names
            return self._process(chat_id, d)

        if q == "split":
            if low in YES:
                d["split_confirmed"] = True
                d["split_mode"] = "chia_deu"
                return self._process(chat_id, d)
            pairs = parse_shares_reply(text)
            if not pairs:
                return None
            if len(pairs) == 1:
                # "tiền điện 450k" trông giống "<tên> <số tiền>". Chỉ coi là cách chia
                # khi tên đó là người đã biết hoặc có trong danh sách cùng chia.
                known = {normalize_name(x) for x in d["participants"]}
                if self._person(pairs[0][0]) is None and normalize_name(pairs[0][0]) not in known:
                    return None
            d["split_mode"] = "ghi_ro"
            d["shares"] = [list(p) for p in pairs]
            for name, _ in pairs:
                if normalize_name(name) not in {normalize_name(x) for x in d["participants"]}:
                    d["participants"].append(name)
            return self._process(chat_id, d)

        if q == "excess":
            if low in YES:
                d["excess_ok"] = True
                return self._process(chat_id, d)
            return None

        return None

    # ================================================================ ghi vào sổ

    def _commit(self, chat_id: str, d: dict) -> str:
        lg = self.ledger
        kind, amount, note, raw = d["kind"], d["amount"], d["note"] or "", d["raw"]
        if d.get("replace_id"):
            try:
                lg.delete(d["replace_id"])
            except LedgerError:
                pass
        try:
            if kind == "chi":
                tx = lg.add_expense(amount, d["category"], note, raw_text=raw)
            elif kind == "thu":
                tx = lg.add_income(amount, d["category"], note, raw_text=raw)
            elif kind == "chi_chung":
                payer = self._person(d["payer"])
                shares = {lg.person(pid): a for pid, a in d["_shares"].items()}
                tx = lg.add_shared_exact(amount, d["category"], payer, shares, note, raw_text=raw)
            elif kind in ("cho_vay", "di_vay"):
                tx = lg.add_loan(self._person(d["payer"]), self._person(d["receiver"]), amount, note, raw_text=raw)
            elif kind == "tra_no":
                tx = lg.add_repayment(self._person(d["payer"]), self._person(d["receiver"]), amount, note, raw_text=raw)
            else:  # pragma: no cover
                raise LedgerError(f"Loại '{kind}' chưa hỗ trợ")
        except (LedgerError, SplitError, SplitMismatch) as exc:
            lg.clear_pending(chat_id)
            return f"Chưa ghi được: {exc}."

        lg.clear_pending(chat_id)
        head = "Đã sửa" if d.get("replace_id") else "Đã ghi"
        return f"{head}: {self.describe(tx)}" + self._debt_lines(tx)

    # ================================================================ hiển thị

    def _who(self, p: Person, cap: bool = False) -> str:
        if p.is_me:
            return "Bạn" if cap else "bạn"
        return p.name

    def _label(self, d: dict) -> str:
        note = d.get("note") or "Khoản này"
        amount = f" {format_vnd(d['amount'])}" if d.get("amount") else ""
        return f"{note[:1].upper()}{note[1:]}{amount}"

    def describe(self, tx: Transaction) -> str:
        lg = self.ledger
        amt = format_vnd(tx.amount)
        note = tx.note or ""
        if tx.kind == "chi":
            return f"{note} {amt} · {tx.category}".strip()
        if tx.kind == "thu":
            return f"thu {note} {amt}".replace("  ", " ")
        if tx.kind == "chi_chung":
            payer = lg.person(tx.payer_id)
            parts = ", ".join(f"{self._who(lg.person(pid))} {format_vnd(a)}" for pid, a in tx.splits.items())
            return f"{note} {amt} · {tx.category} · {self._who(payer)} trả, chia: {parts}".strip()
        payer, receiver = lg.person(tx.payer_id), lg.person(tx.receiver_id)
        if tx.kind == "vay":
            if payer.is_me:
                return f"cho {receiver.name} mượn {amt}"
            if receiver.is_me:
                return f"vay {payer.name} {amt}"
            return f"{payer.name} cho {receiver.name} mượn {amt}"
        return f"{self._who(payer)} trả {self._who(receiver)} {amt}"

    def _debt_lines(self, tx: Transaction) -> str:
        lg = self.ledger
        me = lg.me
        ids = {tx.payer_id, tx.receiver_id, *tx.splits}
        ids.discard(None)
        lines = []
        if me.id in ids:
            for pid in sorted(ids - {me.id}):
                p = lg.person(pid)
                bal = lg.balance_with_me(p)
                if bal > 0:
                    lines.append(f"{p.name} nợ bạn {format_vnd(bal)}")
                elif bal < 0:
                    lines.append(f"Bạn nợ {p.name} {format_vnd(-bal)}")
                else:
                    lines.append(f"{p.name} với bạn hết nợ")
        elif tx.kind == "chi_chung":
            payer = lg.person(tx.payer_id)
            for pid in tx.splits:
                if pid != payer.id:
                    p = lg.person(pid)
                    lines.append(f"{p.name} nợ {payer.name} {format_vnd(lg.debt_between(p, payer))}")
        if not lines:
            return ""
        return "\nCông nợ: " + " · ".join(lines)

    # ================================================================ lệnh

    def _summary(self, arg: str) -> str:
        today: date = self.today()
        year, month = today.year, today.month
        m = re.search(r"(\d{1,2})\s*[/-]\s*(\d{4})", arg) or re.search(r"(?:tháng|thang)?\s*(\d{1,2})\b", arg)
        if m:
            month = int(m.group(1))
            if m.lastindex and m.lastindex >= 2:
                year = int(m.group(2))
            elif month > today.month:
                year -= 1
            if not 1 <= month <= 12:
                return "Tháng không hợp lệ. Ví dụ: tổng kết tháng 10"
        s = self.ledger.month_summary(year, month)
        out = [f"Tổng kết tháng {month}/{year}", "", "Chi (phần của bạn):"]
        if s.expense_by_category:
            out += [f"- {k}: {format_vnd(v)}" for k, v in sorted(s.expense_by_category.items(), key=lambda kv: -kv[1])]
        else:
            out.append("- chưa có khoản nào")
        out += [
            f"Tổng chi: {format_vnd(s.total_expense)}",
            f"Tổng thu: {format_vnd(s.total_income)}",
            f"Còn lại: {format_vnd(s.net)}",
            "",
            self._debts_report(),
        ]
        return "\n".join(out)

    def _debts_report(self) -> str:
        debts = self.ledger.debts()
        if not debts:
            return "Công nợ: không ai nợ ai."
        out = ["Công nợ:"]
        for d in debts:
            out.append(f"- {self._who(d.debtor, True)} nợ {self._who(d.creditor)} {format_vnd(d.amount)}")
        simple = self.ledger.simplified_debts()
        if len(simple) < len(debts):
            out += ["", f"Trả gọn ({len(simple)} lần chuyển thay vì {len(debts)}):"]
            for d in simple:
                out.append(f"- {self._who(d.debtor, True)} chuyển {self._who(d.creditor)} {format_vnd(d.amount)}")
        return "\n".join(out)

    def _delete_last(self) -> str:
        tx = self.ledger.delete_last()
        if tx is None:
            return "Chưa có khoản nào để xóa."
        return f"Đã xóa: {self.describe(tx)}"

    def _edit_last(self, chat_id: str, new_text: str) -> str:
        last = self.ledger.last_transaction()
        if last is None:
            return "Chưa có khoản nào để sửa."
        if not new_text.strip():
            return f"Khoản vừa ghi: {self.describe(last)}\nGhi \"sửa: <câu mới>\" để thay, ví dụ \"sửa: tiền điện 480k\"."
        return self._new_record(chat_id, new_text, replace_id=last.id)
