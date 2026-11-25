"""Đọc và hiển thị số tiền VNĐ.

Mọi số tiền trong hệ thống là số nguyên đồng (int). Không dùng float ở bất kỳ đâu.

Các dạng đọc được:
    50k, 50 nghìn, 50 ngàn            -> 50.000
    150.000, 150,000, 150000, 150.000đ -> 150.000
    1tr2, 1 triệu 2, 1tr200k           -> 1.200.000
    1.5tr, 1,5tr, 1.5 triệu, 2 củ      -> 1.500.000 / 2.000.000
    1k5                                -> 1.500
    1 tỷ 2                             -> 1.200.000.000

Số trơn nhỏ hơn 1.000 (ví dụ "450") bị coi là mơ hồ: không rõ là 450 nghìn hay
450 đồng, nên ném AmbiguousAmount để bot hỏi lại.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation


class AmountError(ValueError):
    """Không đọc được số tiền."""


class AmbiguousAmount(AmountError):
    """Đọc được số nhưng không chắc đơn vị, cần hỏi lại người dùng."""


_UNITS = {
    "k": 1_000,
    "nghìn": 1_000,
    "nghin": 1_000,
    "ngàn": 1_000,
    "ngan": 1_000,
    "tr": 1_000_000,
    "triệu": 1_000_000,
    "trieu": 1_000_000,
    "củ": 1_000_000,
    "cu": 1_000_000,
    "tỷ": 1_000_000_000,
    "tỉ": 1_000_000_000,
    "ty": 1_000_000_000,
    "ti": 1_000_000_000,
    "tỏi": 1_000_000_000,
}

# Đơn vị dài đặt trước để regex không cắt "triệu" thành "tr".
_UNIT_RE = "|".join(sorted(map(re.escape, _UNITS), key=len, reverse=True))

_CURRENCY_SUFFIX = re.compile(r"\s*(?:vnđ|vnd|đồng|dong|đ)\s*$")

_AMOUNT_RE = re.compile(
    rf"""^
    (?P<num>\d+(?:[.,]\d+)*)
    \s*(?P<unit>{_UNIT_RE})?
    (?:\s*(?P<tail>\d{{1,3}})\s*(?P<tailunit>{_UNIT_RE})?)?
    $""",
    re.VERBOSE,
)


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFC", text).strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = _CURRENCY_SUFFIX.sub("", s)
    return s.strip()


def _parse_number(num: str, has_unit: bool) -> Decimal:
    """'150.000' -> 150000 ; '1.5' -> 1.5 (chỉ khi có đơn vị đi kèm)."""
    parts = re.split(r"[.,]", num)
    if len(parts) == 1:
        return Decimal(num)

    groups_of_three = all(len(p) == 3 for p in parts[1:])
    if groups_of_three:
        # Dấu chấm/phẩy là phân cách hàng nghìn: 150.000, 1,500,000
        return Decimal("".join(parts))

    if len(parts) == 2:
        # Số thập phân: 1.5tr, 1,25tr. Không có đơn vị thì không biết 1.5 là gì.
        if not has_unit:
            raise AmbiguousAmount(f"'{num}' là bao nhiêu tiền? Ghi rõ đơn vị, ví dụ {num}tr hoặc {num}k")
        return Decimal(f"{parts[0]}.{parts[1]}")

    raise AmountError(f"Không đọc được số '{num}'")


def parse_amount(text: str) -> int:
    """Đổi một chuỗi số tiền sang số nguyên đồng.

    Ném AmountError nếu không đọc được, AmbiguousAmount nếu cần hỏi lại.
    """
    if not text or not text.strip():
        raise AmountError("Chưa có số tiền")

    s = _normalize(text)
    m = _AMOUNT_RE.match(s)
    if not m:
        raise AmountError(f"Không đọc được số tiền '{text.strip()}'")

    unit = m.group("unit")
    tail = m.group("tail")
    tailunit = m.group("tailunit")

    if tail is not None and unit is None:
        # "1 2" hay "150 000" kiểu gõ cách: chỉ chấp nhận khi là nhóm hàng nghìn.
        if len(tail) == 3 and tailunit is None:
            return parse_amount(m.group("num") + tail)
        raise AmountError(f"Không đọc được số tiền '{text.strip()}'")

    try:
        value = _parse_number(m.group("num"), has_unit=unit is not None)
    except InvalidOperation as exc:  # pragma: no cover - regex đã lọc
        raise AmountError(f"Không đọc được số tiền '{text.strip()}'") from exc

    if unit is None:
        if value != value.to_integral_value():
            raise AmountError(f"Số tiền '{text.strip()}' không hợp lệ")
        amount = int(value)
        if amount < 1_000:
            raise AmbiguousAmount(
                f"'{text.strip()}' là {amount} nghìn ({format_vnd(amount * 1000)}) hay {amount} đồng?"
            )
        return amount

    mult = _UNITS[unit]
    total = value * mult

    if tail is not None:
        if value != value.to_integral_value():
            raise AmountError(f"Không đọc được số tiền '{text.strip()}'")
        if tailunit is not None:
            tail_mult = _UNITS[tailunit]
            if tail_mult >= mult:
                raise AmountError(f"Không đọc được số tiền '{text.strip()}'")
            total += Decimal(tail) * tail_mult
        else:
            # 1tr2 = 1.2tr, 1tr25 = 1.25tr, 1tr250 = 1.25tr, 1k5 = 1.5k
            total += Decimal(tail) * mult / (Decimal(10) ** len(tail))

    if total != total.to_integral_value():
        raise AmountError(f"Số tiền '{text.strip()}' bị lẻ dưới 1 đồng")
    amount = int(total)
    if amount <= 0:
        raise AmountError("Số tiền phải lớn hơn 0")
    return amount


def format_vnd(amount: int) -> str:
    """1500000 -> '1.500.000đ'"""
    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(amount):,}".replace(",", ".") + "đ"
