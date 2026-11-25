"""Chia tiền một khoản chi chung.

Quy tắc:
- Chia đều: phần của từng người làm tròn xuống. Nếu tổng tiền chẵn nghìn thì làm
  tròn theo nghìn, còn không thì theo đồng. Tiền lẻ còn dư do người trả chịu.
- Chia theo số ghi rõ: các phần cộng lại phải đúng bằng tổng, lệch là báo lỗi để bot hỏi lại.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from typing import TypeVar

P = TypeVar("P", bound=Hashable)


class SplitError(ValueError):
    """Cách chia không hợp lệ."""


class SplitMismatch(SplitError):
    """Các phần chia cộng lại không khớp tổng tiền."""

    def __init__(self, total: int, split_sum: int):
        self.total = total
        self.split_sum = split_sum
        self.missing = total - split_sum
        super().__init__(f"Các phần chia cộng lại {split_sum}, tổng là {total}")


def split_equal(total: int, participants: Sequence[P], payer: P) -> dict[P, int]:
    """Chia đều `total` cho `participants`. Tiền lẻ cộng vào phần của `payer`.

    Nếu người trả không nằm trong danh sách chia (trả hộ người khác) mà vẫn còn
    tiền lẻ, người trả nhận phần lẻ đó như phần chi của chính mình.
    """
    if total <= 0:
        raise SplitError("Số tiền phải lớn hơn 0")
    people = list(dict.fromkeys(participants))  # bỏ trùng, giữ thứ tự
    if not people:
        raise SplitError("Chưa có ai để chia")

    unit = 1_000 if total % 1_000 == 0 else 1
    base = (total // len(people)) // unit * unit
    shares = {p: base for p in people}
    remainder = total - base * len(people)
    if remainder:
        shares[payer] = shares.get(payer, 0) + remainder
    return shares


def split_exact(total: int, shares: Mapping[P, int]) -> dict[P, int]:
    """Kiểm tra cách chia ghi rõ từng người. Trả về bản sao nếu hợp lệ."""
    if total <= 0:
        raise SplitError("Số tiền phải lớn hơn 0")
    if not shares:
        raise SplitError("Chưa có ai để chia")
    for person, amount in shares.items():
        if not isinstance(amount, int) or amount < 0:
            raise SplitError(f"Phần chia của {person} không hợp lệ: {amount}")
    split_sum = sum(shares.values())
    if split_sum != total:
        raise SplitMismatch(total, split_sum)
    return {p: a for p, a in shares.items() if a > 0}
