"""Hiểu tin nhắn bằng quy tắc, không cần AI, không tốn tiền.

Trả về cùng kiểu ParsedMessage như ClaudeParser, nên bot dùng được cả hai.
Cách làm:
- Tìm số tiền trong câu (bỏ qua "tháng 11", "3 người"...).
- Nhận loại giao dịch theo mẫu câu: "cho X mượn", "vay X", "X trả 500k", "lương"...
- Nhận tên người: "tôi/mình", người đã có trong sổ, chữ viết hoa, "anh/chị + tên",
  và các tên đứng sau "với", "cùng", "cho", "hộ".
- Xếp nhóm theo từ khóa, ưu tiên những gì bạn đã dạy bot (bảng category_hints).
Câu nào không chắc, bot sẽ hỏi lại ở bước sau.
"""

from __future__ import annotations

import re
import unicodedata

from .ai_parser import ParsedMessage, Share
from .money import AmountError, AmbiguousAmount, parse_amount
from .store import _HONORIFICS, SELF_WORDS, Ledger, normalize_name


def strip_accents(text: str) -> str:
    s = unicodedata.normalize("NFD", text)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


# ---------------------------------------------------------------- nhóm chi phí

# Từ khóa viết không dấu. Cụm dài được ưu tiên hơn cụm ngắn.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Nhà ở và điện nước": [
        "tien dien", "dien", "tien nuoc", "hoa don nuoc", "nuoc sinh hoat", "thue nha", "tien nha", "tien phong",
        "internet", "wifi", "tien mang", "cuoc mang", "gas", "binh ga", "tien rac", "phi quan ly", "chung cu",
        "sua nha", "dien nuoc", "truyen hinh", "cap quang",
    ],
    "Ăn uống": [
        "an", "uong", "com", "pho", "bun", "lau", "cafe", "ca phe", "caphe", "cf", "tra sua", "tra da", "tra chanh",
        "bia", "nhau", "buffet", "banh", "ga ran", "pizza", "kfc", "do an", "an sang", "an trua", "an toi", "an vat",
        "chao", "mi", "mien", "che", "kem", "nuoc ngot", "sinh to", "hu tieu", "banh mi", "lotteria", "highlands",
        "starbucks", "phuc long", "do uong", "an uong", "nuoc uong", "oc", "nuong", "hai san", "di cho", "rau", "thit",
        "trai cay", "hoa qua", "sua",
    ],
    "Đi lại": [
        "xang", "do xang", "taxi", "grab", "be", "gojek", "xanh sm", "gui xe", "ve xe", "xe buyt", "xe bus", "bus",
        "tau", "ve tau", "may bay", "ve may bay", "sua xe", "rua xe", "thay nhot", "phi cau duong", "cau duong",
        "do xe", "xe om", "di lai",
    ],
    "Mua sắm": [
        "quan", "ao", "giay", "dep", "tui", "vi da", "shopee", "lazada", "tiki", "tiktok shop", "my pham", "son",
        "kem chong nang", "do dung", "sieu thi", "dien thoai", "laptop", "tai nghe", "dong ho", "mua sam", "do gia dung",
        "noi that", "bat dia", "phu kien",
    ],
    "Giải trí": [
        "phim", "xem phim", "cgv", "lotte cinema", "game", "karaoke", "hat", "du lich", "netflix", "spotify",
        "youtube", "concert", "show", "bar", "pub", "bowling", "bi a", "bida", "di choi", "giai tri", "khach san",
        "homestay", "ve tham quan", "cong vien",
    ],
    "Sức khỏe": [
        "thuoc", "kham", "kham benh", "benh vien", "phong kham", "nha khoa", "rang", "gym", "tap gym", "yoga",
        "bao hiem y te", "vitamin", "xet nghiem", "tiem", "vaccine", "suc khoe", "mat kinh", "massage",
    ],
    "Học tập": [
        "hoc", "hoc phi", "sach", "khoa hoc", "vo", "but", "tieng anh", "ielts", "toeic", "udemy", "coursera",
        "luyen thi", "gia su", "hoc them", "tai lieu", "van phong pham",
    ],
    "Hiếu hỉ": [
        "cuoi", "dam cuoi", "an cuoi", "mung cuoi", "mung", "dam ma", "dam gio", "vieng", "sinh nhat", "qua",
        "li xi", "lixi", "phong bi", "tan gia", "thoi noi", "day thang", "hieu hi", "bieu",
    ],
}
# Từ quá chung, chỉ dùng khi không có từ khóa nào khác.
GENERIC_KEYWORDS = {"mua": "Mua sắm", "do": "Mua sắm"}

INCOME_KEYWORDS = [
    "luong", "thuong", "bonus", "thu nhap", "duoc tra", "nhan duoc", "duoc cho", "duoc tang", "duoc li xi",
    "ban duoc", "hoan tien", "tien lai", "lai tiet kiem", "co tuc", "hoa hong", "freelance", "lam them",
]


def _contains_word(haystack: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", haystack) is not None


def guess_category(note: str, hints: dict[str, str] | None = None) -> str | None:
    key = strip_accents(note.lower())
    for hint_key, cat in sorted((hints or {}).items(), key=lambda kv: -len(kv[0])):
        if hint_key and _contains_word(key, hint_key):
            return cat
    best: tuple[int, str] | None = None
    for cat, words in CATEGORY_KEYWORDS.items():
        for w in words:
            if _contains_word(key, w) and (best is None or len(w) > best[0]):
                best = (len(w), cat)
    if best:
        return best[1]
    for w, cat in GENERIC_KEYWORDS.items():
        if _contains_word(key, w):
            return cat
    return None


# ---------------------------------------------------------------- số tiền

_UNIT = r"k|nghìn|nghin|ngàn|ngan|tr|triệu|trieu|củ|tỷ|tỉ"
_AMOUNT_CAND = re.compile(
    rf"(?<![\w.,])(\d+(?:[.,]\d+)*)\s*({_UNIT})?(?:\s*(\d{{1,3}})(?!\d)\s*(k|nghìn|nghin|ngàn|ngan)?)?\s*(đồng|đ|vnđ|vnd)?(?!\w)",
    re.IGNORECASE,
)
_NOT_MONEY_BEFORE = {"tháng", "thang", "ngày", "ngay", "năm", "lần", "số", "phòng", "tầng", "lớp", "bàn", "kỳ", "đợt"}
_NOT_MONEY_AFTER = re.compile(r"^\s*(người|nguoi|lần|giờ|gio|h\b|tháng|thang|ngày|ngay|năm|tuổi|tuoi|phút|cái|ly|cốc|suất|vé)", re.I)


def find_amounts(text: str) -> list[tuple[int, int, str]]:
    """Các đoạn ghi tiền trong câu: (bắt đầu, kết thúc, chữ). Chưa đổi ra số."""
    out = []
    for m in _AMOUNT_CAND.finditer(text):
        raw = m.group(0).strip()
        before = text[: m.start()].split()
        prev = before[-1].lower().strip(",.:;") if before else ""
        if prev in _NOT_MONEY_BEFORE:
            continue
        has_unit = bool(m.group(2) or m.group(5))
        if not has_unit and _NOT_MONEY_AFTER.match(text[m.end():]):
            continue
        try:
            parse_amount(raw)
        except AmbiguousAmount:
            pass  # vẫn giữ, bot sẽ hỏi lại đơn vị
        except AmountError:
            continue
        start = m.start() + (len(m.group(0)) - len(m.group(0).lstrip()))
        out.append((start, start + len(raw), raw))
    return out


# ---------------------------------------------------------------- tên người

_SELF = {w for w in SELF_WORDS}
_HON = set(_HONORIFICS) - {"a", "c", "e"}
_STOP_AFTER_NAMES = re.compile(
    r"\s*(?:,|\.|;|\bđã\b|\btrả\b|\bbao\b|\bthanh toán\b|\bchia\b|\bmỗi\b|\btiền\b|\bhết\b|\bluôn\b|\bnhé\b|§|$)", re.I
)


class RuleParser:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    # ----------------------------------------------------- tiện ích tên

    def _is_name(self, phrase: str) -> bool:
        p = phrase.strip(" ,.;:")
        if not p or any(ch.isdigit() for ch in p) or len(p.split()) > 3:
            return False
        low = p.lower()
        if low in _SELF:
            return True
        if self.ledger.find_person(p) is not None:
            return True
        words = p.split()
        if words[0].lower() in _HON and len(words) >= 2:
            return True
        return all(w[:1].isupper() for w in words)

    def _clean_name(self, phrase: str) -> str:
        p = phrase.strip(" ,.;:")
        if p.lower() in _SELF:
            return "tôi"
        return p

    def _names_in(self, chunk: str) -> list[str]:
        """'Nam và Lan' / 'tôi với Nam' / 'Nam, Lan' -> danh sách tên."""
        parts = re.split(r"\s*(?:,|\bvà\b|\bvới\b|\bcùng\b|\bva\b|\bvoi\b)\s*", chunk.strip(), flags=re.I)
        names = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Bỏ từ đệm: "cả Lan", "Nam nữa"
            part = re.sub(r"^(?:cả|ca)\s+|\s+(?:nữa|nua|luôn|luon)$", "", part, flags=re.I).strip()
            if self._is_name(part):
                names.append(self._clean_name(part))
                continue
            # "tôi sách", "Nam đi ăn": lấy tên ở đầu rồi dừng, phần sau không còn là tên
            words = part.split()
            for n in (2, 1):
                cand = " ".join(words[:n])
                if len(words) > n and self._is_name(cand) and (n == 1 or words[0].lower() in _HON):
                    names.append(self._clean_name(cand))
                    break
            break
        return names

    def _names_after(self, text: str, marker: str) -> list[str]:
        out = []
        for m in re.finditer(rf"\b(?:{marker})\s+", text, flags=re.I):
            rest = text[m.end():]
            stop = _STOP_AFTER_NAMES.search(rest)
            chunk = rest[: stop.start()] if stop else rest
            out += self._names_in(chunk)
        return out

    def _word_before(self, text: str, idx: int) -> str | None:
        """Tên đứng ngay trước vị trí idx (1-3 từ)."""
        words = text[:idx].replace(",", " , ").split()
        for n in (3, 2, 1):
            if len(words) >= n:
                cand = " ".join(words[-n:])
                if "," in cand:
                    continue
                if self._is_name(cand) and (n == 1 or cand.split()[0].lower() in _HON or all(w[:1].isupper() for w in cand.split())):
                    return self._clean_name(cand)
        return None

    # ----------------------------------------------------- chính

    def parse(self, text: str) -> ParsedMessage:
        t = unicodedata.normalize("NFC", text).strip()
        t = re.sub(r"\s+", " ", t)
        amounts = find_amounts(t)
        if not amounts:
            return self._result("khong_ro" if not self._looks_like_money(t) else "chi", None, t, note=t)

        # Phần chia ghi rõ: "Nam 120k tôi 120k". Tổng là số đầu tiên không có tên đứng trước.
        if len(amounts) == 1:
            named = [(*amounts[0], None)]  # một số tiền thì đó là tổng
        else:
            named = [(s, e, raw, self._word_before(t, s)) for s, e, raw in amounts]
        total = next(((s, e, raw) for s, e, raw, who in named if who is None), None)
        shares = [(who, raw) for s, e, raw, who in named if who is not None and (total is None or s != total[0])]
        if total is None:
            # Chỉ có các phần chia, tổng = cộng lại
            try:
                amount_text = str(sum(parse_amount(raw) for _, raw in shares))
            except AmountError:
                amount_text = shares[0][1]
            s0 = named[0][0]
            total = (s0, s0, amount_text)
        start, end, amount_text = total
        if total[0] == total[1]:
            marked = t
        else:
            marked = t[:start] + " § " + t[end:]
        marked = re.sub(r"\s+", " ", marked).strip()
        low = marked.lower()
        plain = strip_accents(low)
        NAME = r"(.{1,30}?)"

        # --- vay, cho vay
        m = re.search(rf"^{NAME}\s+cho\s+(?:tôi|mình|tớ|toi|minh)\s+(?:mượn|vay|muon)\b", marked, re.I)
        if m and self._is_name(m.group(1)):
            return self._result("di_vay", amount_text, t, payer=self._clean_name(m.group(1)), receiver="tôi")
        m = re.search(rf"\bcho\s+{NAME}\s+(?:mượn|vay|muon)\b", marked, re.I)
        if m and self._is_name(m.group(1)):
            return self._result("cho_vay", amount_text, t, payer="tôi", receiver=self._clean_name(m.group(1)))
        m = re.search(r"\bcho\s+(?:mượn|vay|muon)\s+(.*?)\s*§", marked, re.I)
        if m:
            name = m.group(1).strip()
            return self._result("cho_vay", amount_text, t, payer="tôi", receiver=self._clean_name(name) if self._is_name(name) else None)
        m = re.search(rf"^(?:(?:tôi|mình|toi|minh)\s+)?(?:đi\s+)?(?:vay|mượn|muon)\s+(?:của\s+|cua\s+)?{NAME}\s*§", marked, re.I)
        if m and self._is_name(m.group(1)):
            return self._result("di_vay", amount_text, t, payer=self._clean_name(m.group(1)), receiver="tôi")

        # --- trả nợ
        m = re.search(rf"^(?:(?:tôi|mình|toi|minh)\s+)?(?:đã\s+)?(?:trả|tra|chuyển trả|hoàn)\s+(?:lại\s+|nợ\s+|no\s+)?(?:cho\s+)?{NAME}\s*§\s*(?:$|,|\.)", marked, re.I)
        if m and self._is_name(m.group(1)) and m.group(1).lower() not in _SELF:
            return self._result("tra_no", amount_text, t, payer="tôi", receiver=self._clean_name(m.group(1)))
        m = re.search(
            rf"^{NAME}\s+(?:đã\s+)?(?:trả|tra|chuyển trả|chuyển khoản trả|ck trả|hoàn|gửi lại|gửi trả)\s+(?:lại\s+|nợ\s+|no\s+)?(?:cho\s+)?(?:(?:tôi|mình|toi|minh)\s+)?§\s*(?:$|,|\.|nợ|rồi)",
            marked,
            re.I,
        )
        if m and self._is_name(m.group(1)) and m.group(1).lower() not in _SELF:
            return self._result("tra_no", amount_text, t, payer=self._clean_name(m.group(1)), receiver="tôi")

        note = self._note(marked)

        # --- người trả, người cùng dùng
        payer = None
        for vm in re.finditer(r"\b(trả|bao|thanh toán|quẹt thẻ|ứng|mua|đặt|chuyển khoản|ck)\b", marked, re.I):
            who = self._word_before(marked, vm.start())
            if who:
                payer = who
                break
        with_names = self._names_after(marked, r"chia đều với|chia đôi với|chia với|chia cho|với|cùng|cung|voi")
        for_names = self._names_after(marked, r"cho|hộ|giùm|giúp|ho")
        share_names = [n for n, _ in shares]

        participants: list[str] = []
        others_present = bool(with_names or share_names or (payer and payer != "tôi") or (for_names and payer))
        if not others_present and not shares:
            for_names = [n for n in for_names if n != "tôi"]
            others_present = bool(for_names)

        # --- thu nhập
        if not others_present and any(_contains_word(plain, k) for k in INCOME_KEYWORDS):
            return self._result("thu", amount_text, t, category="Thu nhập", note=note)

        if not others_present:
            hints = self.ledger.category_hints()
            return self._result("chi", amount_text, t, category=guess_category(note, hints), note=note, payer="tôi")

        if for_names and payer:
            # "Nam trả taxi cho tôi với Nam": người được trả hộ là những người cùng dùng
            participants = for_names + [n for n in with_names if n not in for_names]
        else:
            participants = ["tôi"] + with_names + for_names
            if payer and payer not in participants:
                participants.append(payer)
        for n in share_names:
            if n not in participants:
                participants.append(n)
        participants = list(dict.fromkeys(participants))

        if shares:
            split_mode = "ghi_ro"
        elif re.search(r"chia\s*(đều|deu|đôi|doi)", low):
            split_mode = "chia_deu"
        else:
            split_mode = "chua_noi"

        hints = self.ledger.category_hints()
        return self._result(
            "chi_chung",
            amount_text,
            t,
            category=guess_category(note, hints),
            note=note,
            payer=payer,
            participants=participants,
            split_mode=split_mode,
            shares=shares if split_mode == "ghi_ro" else [],
        )

    @staticmethod
    def _looks_like_money(t: str) -> bool:
        return bool(re.search(r"\b(tiền|chi|mua|trả|vay|mượn|lương)\b", t, re.I))

    def _note(self, marked: str) -> str:
        """Mô tả ngắn: phần chữ trước số tiền, bỏ "X trả" và đoạn "với/cho ..."."""
        head, _, tail = marked.partition("§")
        note = head.strip(" ,.") or tail.split(",")[0].strip(" ,.")
        m = re.search(r"\b(?:đã\s+)?(?:trả|bao|thanh toán|mua|đặt)\b\s*", note, re.I)
        if m and m.start() > 0 and self._word_before(note, m.start()):
            note = note[m.end():]
            note = re.sub(r"^(?:hộ|giùm|giúp)\s+\S+\s+", "", note, flags=re.I)
        note = re.sub(r"\s*\b(?:với|cùng|cho|hộ|giùm)\b.*$", "", note, flags=re.I)
        return note.strip(" ,.:") or marked.replace("§", "").strip(" ,.")

    @staticmethod
    def _result(kind, amount_text, raw, *, category=None, note="", payer=None, receiver=None, participants=(), split_mode="chua_noi", shares=()):
        if not note:
            note = re.sub(r"\s+", " ", raw).strip()
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
