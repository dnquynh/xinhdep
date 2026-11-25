"""Sổ thu chi lưu trên SQLite.

Lớp Ledger là nơi duy nhất ghi/đọc dữ liệu. Phần hiểu tin nhắn (AI) và bot chỉ gọi
các hàm ở đây, không tự viết SQL và không tự cộng trừ tiền.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .debts import Debt, pairwise_balances, simplify
from .splits import SplitError, split_equal, split_exact

VN_TZ = timezone(timedelta(hours=7))  # Việt Nam không có giờ mùa hè

EXPENSE_CATEGORIES = (
    "Ăn uống",
    "Nhà ở và điện nước",
    "Đi lại",
    "Mua sắm",
    "Giải trí",
    "Sức khỏe",
    "Học tập",
    "Hiếu hỉ",
    "Khác",
)
INCOME_CATEGORIES = ("Thu nhập",)

# Không dùng "me" (dễ nhầm "mẹ") hay "to" (dễ nhầm tên riêng).
SELF_WORDS = {"tôi", "toi", "mình", "minh", "tớ", "tao"}

# Danh xưng đứng trước tên, bỏ đi khi so khớp: "anh Nam" -> "nam"
_HONORIFICS = (
    "anh", "chị", "chi", "em", "bạn", "ban", "cô", "co", "chú", "chu", "bác", "bac",
    "ông", "ong", "bà", "ba", "cậu", "cau", "dì", "di", "thím", "mợ", "a", "c", "e",
)

_SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")


class LedgerError(ValueError):
    """Lỗi nghiệp vụ, thông điệp hiển thị được cho người dùng."""


class UnknownPerson(LedgerError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Chưa biết '{name}' là ai")


class UnknownCategory(LedgerError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Không có nhóm '{name}'")


def normalize_name(name: str) -> str:
    """Chuẩn hóa tên để so khớp. Giữ dấu tiếng Việt vì 'Lan' và 'Lân' là hai người."""
    s = unicodedata.normalize("NFC", name).strip().lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    words = s.split(" ")
    while len(words) > 1 and words[0] in _HONORIFICS:
        words = words[1:]
    return " ".join(words)


def today_vn() -> date:
    return datetime.now(VN_TZ).date()


@dataclass(frozen=True)
class Person:
    id: int
    name: str
    is_me: bool = False


@dataclass
class Transaction:
    id: int
    kind: str
    amount: int
    category: str | None
    payer_id: int | None
    receiver_id: int | None
    note: str
    occurred_on: str
    splits: dict[int, int] = field(default_factory=dict)


@dataclass
class MonthSummary:
    year: int
    month: int
    expense_by_category: dict[str, int]
    income_by_category: dict[str, int]

    @property
    def total_expense(self) -> int:
        return sum(self.expense_by_category.values())

    @property
    def total_income(self) -> int:
        return sum(self.income_by_category.values())

    @property
    def net(self) -> int:
        return self.total_income - self.total_expense


class Ledger:
    def __init__(self, path: str | Path = ":memory:", me_name: str = "Tôi"):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(_SCHEMA)
        self._seed(me_name)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ khởi tạo

    def _seed(self, me_name: str) -> None:
        with self.db:
            for name in EXPENSE_CATEGORIES:
                self.db.execute("INSERT OR IGNORE INTO categories (name, kind) VALUES (?, 'chi')", (name,))
            for name in INCOME_CATEGORIES:
                self.db.execute("INSERT OR IGNORE INTO categories (name, kind) VALUES (?, 'thu')", (name,))
            row = self.db.execute("SELECT id FROM people WHERE is_me = 1").fetchone()
            if row is None:
                cur = self.db.execute("INSERT INTO people (display_name, is_me) VALUES (?, 1)", (me_name,))
                me_id = cur.lastrowid
                for w in SELF_WORDS:
                    self.db.execute("INSERT OR IGNORE INTO aliases (alias, person_id) VALUES (?, ?)", (w, me_id))

    # ------------------------------------------------------------------ người

    @property
    def me(self) -> Person:
        row = self.db.execute("SELECT id, display_name FROM people WHERE is_me = 1").fetchone()
        return Person(row["id"], row["display_name"], True)

    def person(self, person_id: int) -> Person:
        row = self.db.execute("SELECT id, display_name, is_me FROM people WHERE id = ?", (person_id,)).fetchone()
        if row is None:
            raise LedgerError(f"Không có người id={person_id}")
        return Person(row["id"], row["display_name"], bool(row["is_me"]))

    def people(self) -> list[Person]:
        rows = self.db.execute("SELECT id, display_name, is_me FROM people ORDER BY id").fetchall()
        return [Person(r["id"], r["display_name"], bool(r["is_me"])) for r in rows]

    def find_person(self, name: str) -> Person | None:
        key = normalize_name(name)
        if not key:
            return None
        row = self.db.execute("SELECT person_id FROM aliases WHERE alias = ?", (key,)).fetchone()
        return self.person(row["person_id"]) if row else None

    def resolve(self, name: str) -> Person:
        p = self.find_person(name)
        if p is None:
            raise UnknownPerson(name.strip())
        return p

    def add_person(self, display_name: str, aliases: tuple[str, ...] = ()) -> Person:
        display_name = display_name.strip()
        key = normalize_name(display_name)
        if not key:
            raise LedgerError("Tên không được để trống")
        if self.find_person(display_name):
            raise LedgerError(f"'{display_name}' đã có trong danh sách")
        with self.db:
            cur = self.db.execute("INSERT INTO people (display_name) VALUES (?)", (display_name,))
            pid = cur.lastrowid
            self.db.execute("INSERT INTO aliases (alias, person_id) VALUES (?, ?)", (key, pid))
        person = self.person(pid)
        for a in aliases:
            self.add_alias(person, a)
        return person

    def add_alias(self, person: Person, alias: str) -> None:
        key = normalize_name(alias)
        if not key:
            raise LedgerError("Tên gọi khác không được để trống")
        existing = self.find_person(alias)
        if existing and existing.id != person.id:
            raise LedgerError(f"'{alias}' đang là tên của {existing.name}")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO aliases (alias, person_id) VALUES (?, ?)", (key, person.id))

    # ------------------------------------------------------------------ nhóm

    def categories(self, kind: str) -> list[str]:
        rows = self.db.execute("SELECT name FROM categories WHERE kind = ? ORDER BY id", (kind,)).fetchall()
        return [r["name"] for r in rows]

    def _category_id(self, name: str, kind: str) -> int:
        target = unicodedata.normalize("NFC", name).strip().lower()
        for row in self.db.execute("SELECT id, name FROM categories WHERE kind = ?", (kind,)):
            if unicodedata.normalize("NFC", row["name"]).lower() == target:
                return row["id"]
        raise UnknownCategory(name)

    # ------------------------------------------------------------------ ghi giao dịch

    def _insert(
        self,
        kind: str,
        amount: int,
        *,
        category_id: int | None = None,
        payer: Person | None = None,
        receiver: Person | None = None,
        splits: dict[int, int] | None = None,
        note: str = "",
        raw_text: str = "",
        on: date | None = None,
    ) -> Transaction:
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise LedgerError("Số tiền phải là số nguyên đồng lớn hơn 0")
        occurred = (on or today_vn()).isoformat()
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db:
            cur = self.db.execute(
                """INSERT INTO transactions
                   (kind, amount, category_id, payer_id, receiver_id, note, raw_text, occurred_on, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    kind,
                    amount,
                    category_id,
                    payer.id if payer else None,
                    receiver.id if receiver else None,
                    note.strip(),
                    raw_text,
                    occurred,
                    created,
                ),
            )
            tx_id = cur.lastrowid
            for pid, share in (splits or {}).items():
                self.db.execute(
                    "INSERT INTO splits (transaction_id, person_id, amount) VALUES (?, ?, ?)", (tx_id, pid, share)
                )
        return self.get(tx_id)

    def add_expense(self, amount: int, category: str, note: str = "", *, raw_text: str = "", on: date | None = None):
        """Chi cá nhân: tôi trả, chỉ mình tôi dùng."""
        cid = self._category_id(category, "chi")
        me = self.me
        return self._insert(
            "chi", amount, category_id=cid, payer=me, splits={me.id: amount}, note=note, raw_text=raw_text, on=on
        )

    def add_income(
        self, amount: int, category: str = "Thu nhập", note: str = "", *, raw_text: str = "", on: date | None = None
    ):
        cid = self._category_id(category, "thu")
        return self._insert("thu", amount, category_id=cid, receiver=self.me, note=note, raw_text=raw_text, on=on)

    def add_shared_equal(
        self,
        amount: int,
        category: str,
        payer: Person,
        participants: list[Person],
        note: str = "",
        *,
        raw_text: str = "",
        on: date | None = None,
    ):
        """Chi chung chia đều. `participants` là những người cùng dùng (có thể gồm người trả)."""
        shares = split_equal(amount, [p.id for p in participants], payer.id)
        return self._add_shared(amount, category, payer, shares, note, raw_text, on)

    def add_shared_exact(
        self,
        amount: int,
        category: str,
        payer: Person,
        shares: dict[Person, int],
        note: str = "",
        *,
        raw_text: str = "",
        on: date | None = None,
    ):
        """Chi chung chia theo số ghi rõ từng người. Lệch tổng thì ném SplitMismatch."""
        checked = split_exact(amount, {p.id: a for p, a in shares.items()})
        return self._add_shared(amount, category, payer, checked, note, raw_text, on)

    def _add_shared(self, amount, category, payer, shares, note, raw_text, on):
        if set(shares) <= {payer.id}:
            raise SplitError("Khoản chi chung phải có ít nhất một người khác ngoài người trả")
        cid = self._category_id(category, "chi")
        return self._insert(
            "chi_chung", amount, category_id=cid, payer=payer, splits=shares, note=note, raw_text=raw_text, on=on
        )

    def add_loan(
        self, lender: Person, borrower: Person, amount: int, note: str = "", *, raw_text: str = "", on: date | None = None
    ):
        """Cho vay (lender = tôi) hoặc đi vay (borrower = tôi)."""
        if lender.id == borrower.id:
            raise LedgerError("Người cho vay và người vay phải khác nhau")
        return self._insert("vay", amount, payer=lender, receiver=borrower, note=note, raw_text=raw_text, on=on)

    def add_repayment(
        self, payer: Person, receiver: Person, amount: int, note: str = "", *, raw_text: str = "", on: date | None = None
    ):
        """`payer` trả nợ cho `receiver`. Kiểm tra trả dư bằng repayment_excess() trước khi gọi."""
        if payer.id == receiver.id:
            raise LedgerError("Người trả và người nhận phải khác nhau")
        return self._insert("tra_no", amount, payer=payer, receiver=receiver, note=note, raw_text=raw_text, on=on)

    # ------------------------------------------------------------------ đọc, xóa

    def get(self, tx_id: int) -> Transaction:
        row = self.db.execute(
            """SELECT t.*, c.name AS category_name FROM transactions t
               LEFT JOIN categories c ON c.id = t.category_id WHERE t.id = ?""",
            (tx_id,),
        ).fetchone()
        if row is None:
            raise LedgerError(f"Không có giao dịch id={tx_id}")
        splits = {
            r["person_id"]: r["amount"]
            for r in self.db.execute("SELECT person_id, amount FROM splits WHERE transaction_id = ?", (tx_id,))
        }
        return Transaction(
            id=row["id"],
            kind=row["kind"],
            amount=row["amount"],
            category=row["category_name"],
            payer_id=row["payer_id"],
            receiver_id=row["receiver_id"],
            note=row["note"],
            occurred_on=row["occurred_on"],
            splits=splits,
        )

    def transactions(self, *, month: tuple[int, int] | None = None) -> list[Transaction]:
        sql = "SELECT id FROM transactions WHERE deleted_at IS NULL"
        args: tuple = ()
        if month:
            sql += " AND occurred_on LIKE ?"
            args = (f"{month[0]:04d}-{month[1]:02d}-%",)
        sql += " ORDER BY id"
        return [self.get(r["id"]) for r in self.db.execute(sql, args).fetchall()]

    def last_transaction(self) -> Transaction | None:
        row = self.db.execute("SELECT id FROM transactions WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        return self.get(row["id"]) if row else None

    def delete(self, tx_id: int) -> None:
        with self.db:
            cur = self.db.execute(
                "UPDATE transactions SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), tx_id),
            )
        if cur.rowcount == 0:
            raise LedgerError(f"Không có giao dịch id={tx_id} để xóa")

    def delete_last(self) -> Transaction | None:
        tx = self.last_transaction()
        if tx:
            self.delete(tx.id)
        return tx

    # ------------------------------------------------------------------ công nợ

    @staticmethod
    def _edges_of(tx: Transaction) -> list[Debt[int]]:
        if tx.kind == "chi_chung":
            return [Debt(pid, tx.payer_id, share) for pid, share in tx.splits.items() if pid != tx.payer_id]
        if tx.kind in ("vay", "tra_no"):
            # vay: người nhận nợ người đưa. tra_no: tạo cạnh ngược lại để bù trừ.
            return [Debt(tx.receiver_id, tx.payer_id, tx.amount)]
        return []

    def edges(self) -> list[Debt[int]]:
        """Công nợ tính trên toàn bộ lịch sử, không theo tháng."""
        out: list[Debt[int]] = []
        for tx in self.transactions():
            out.extend(self._edges_of(tx))
        return out

    def debts(self) -> list[Debt[Person]]:
        """Ai nợ ai bao nhiêu, đã bù trừ hai chiều từng cặp."""
        return [Debt(self.person(d.debtor), self.person(d.creditor), d.amount) for d in pairwise_balances(self.edges(), key=int)]

    def simplified_debts(self) -> list[Debt[Person]]:
        """Gợi ý trả nợ ít lần chuyển khoản nhất."""
        return [Debt(self.person(d.debtor), self.person(d.creditor), d.amount) for d in simplify(self.edges(), key=int)]

    def debt_between(self, debtor: Person, creditor: Person) -> int:
        """Số tiền `debtor` đang nợ `creditor` (âm nếu ngược lại)."""
        total = 0
        for e in self.edges():
            if e.debtor == debtor.id and e.creditor == creditor.id:
                total += e.amount
            elif e.debtor == creditor.id and e.creditor == debtor.id:
                total -= e.amount
        return total

    def balance_with_me(self, person: Person) -> int:
        """Dương: người đó nợ tôi. Âm: tôi nợ người đó."""
        return self.debt_between(person, self.me)

    def repayment_excess(self, payer: Person, receiver: Person, amount: int) -> int:
        """Số tiền trả dư so với nợ hiện tại (0 nếu không dư). Bot dùng để hỏi lại."""
        owed = max(self.debt_between(payer, receiver), 0)
        return max(amount - owed, 0)

    # ------------------------------------------------------------------ nhóm đã học

    @staticmethod
    def _hint_key(note: str) -> str:
        s = unicodedata.normalize("NFD", note.lower())
        s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
        s = re.sub(r"[^a-z0-9 ]", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    def learn_category(self, note: str, category: str) -> None:
        key = self._hint_key(note)
        if key:
            self._category_id(category, "chi")  # kiểm tra nhóm có thật
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO category_hints (keyword, category) VALUES (?, ?)", (key, category))

    def category_hints(self) -> dict[str, str]:
        return {r["keyword"]: r["category"] for r in self.db.execute("SELECT keyword, category FROM category_hints")}

    # ------------------------------------------------------------------ câu hỏi đang chờ

    def get_pending(self, chat_id: str, max_age: timedelta = timedelta(hours=2)) -> dict | None:
        row = self.db.execute("SELECT payload, created_at FROM pending WHERE chat_id = ?", (chat_id,)).fetchone()
        if row is None:
            return None
        if datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"]) > max_age:
            self.clear_pending(chat_id)
            return None
        return json.loads(row["payload"])

    def set_pending(self, chat_id: str, payload: dict) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO pending (chat_id, payload, created_at) VALUES (?, ?, ?)",
                (chat_id, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
            )

    def clear_pending(self, chat_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM pending WHERE chat_id = ?", (chat_id,))

    # ------------------------------------------------------------------ tổng kết

    def month_summary(self, year: int, month: int) -> MonthSummary:
        """Chi theo nhóm chỉ tính phần của tôi. Cho vay, đi vay, trả nợ không tính vào thu chi."""
        me_id = self.me.id
        expense = {name: 0 for name in self.categories("chi")}
        income = {name: 0 for name in self.categories("thu")}
        for tx in self.transactions(month=(year, month)):
            if tx.kind in ("chi", "chi_chung"):
                expense[tx.category] += tx.splits.get(me_id, 0)
            elif tx.kind == "thu":
                income[tx.category] += tx.amount
        return MonthSummary(
            year=year,
            month=month,
            expense_by_category={k: v for k, v in expense.items() if v},
            income_by_category={k: v for k, v in income.items() if v},
        )
