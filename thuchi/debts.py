"""Tính công nợ từ danh sách "cạnh nợ" (debtor nợ creditor bao nhiêu).

- pairwise_balances: ai nợ ai bao nhiêu sau khi bù trừ hai chiều giữa từng cặp.
- net_balances: số dư ròng của mỗi người (dương = được nhận, âm = phải trả).
- simplify: gợi ý trả nợ với ít lần chuyển khoản nhất.

Rút gọn chính xác: chia mọi người thành nhiều nhóm nhỏ nhất có tổng bằng 0. Mỗi nhóm
k người cần k-1 lần chuyển, nên càng nhiều nhóm thì càng ít lần chuyển. Làm chính xác
bằng quy hoạch động trên tập con khi có tối đa EXACT_LIMIT người còn số dư, quá số đó
thì dùng cách tham lam (tối đa n-1 lần chuyển).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

P = TypeVar("P", bound=Hashable)

EXACT_LIMIT = 15


@dataclass(frozen=True)
class Debt(Generic[P]):
    debtor: P
    creditor: P
    amount: int


def net_balances(edges: Iterable[Debt[P]]) -> dict[P, int]:
    bal: dict[P, int] = defaultdict(int)
    for e in edges:
        bal[e.creditor] += e.amount
        bal[e.debtor] -= e.amount
    return {p: v for p, v in bal.items() if v != 0}


def pairwise_balances(edges: Iterable[Debt[P]], key=repr) -> list[Debt[P]]:
    """Bù trừ hai chiều giữa từng cặp người. `key` để sắp xếp cặp cho ổn định."""
    pair: dict[tuple[P, P], int] = defaultdict(int)
    for e in edges:
        if e.debtor == e.creditor or e.amount == 0:
            continue
        a, b = sorted((e.debtor, e.creditor), key=key)
        # Quy ước: giá trị dương nghĩa là a nợ b.
        pair[(a, b)] += e.amount if e.debtor == a else -e.amount

    result = []
    for (a, b), v in pair.items():
        if v > 0:
            result.append(Debt(a, b, v))
        elif v < 0:
            result.append(Debt(b, a, -v))
    result.sort(key=lambda d: (-d.amount, key(d.debtor), key(d.creditor)))
    return result


def _settle_group(members: list[tuple[P, int]], key) -> list[Debt[P]]:
    """Trả nợ trong một nhóm có tổng bằng 0: ghép người nợ nhiều nhất với người được nhận nhiều nhất."""
    creditors = sorted(((v, p) for p, v in members if v > 0), key=lambda t: (-t[0], key(t[1])))
    debtors = sorted(((-v, p) for p, v in members if v < 0), key=lambda t: (-t[0], key(t[1])))
    out: list[Debt[P]] = []
    ci = di = 0
    creditors = [list(c) for c in creditors]
    debtors = [list(d) for d in debtors]
    while ci < len(creditors) and di < len(debtors):
        pay = min(creditors[ci][0], debtors[di][0])
        out.append(Debt(debtors[di][1], creditors[ci][1], pay))
        creditors[ci][0] -= pay
        debtors[di][0] -= pay
        if creditors[ci][0] == 0:
            ci += 1
        if debtors[di][0] == 0:
            di += 1
    return out


def simplify(edges: Iterable[Debt[P]], key=repr) -> list[Debt[P]]:
    """Gợi ý các lần chuyển khoản để xóa hết nợ, ít lần nhất có thể."""
    bal = net_balances(edges)
    people = sorted(bal, key=key)
    n = len(people)
    if n == 0:
        return []

    if n > EXACT_LIMIT:
        groups = [people]
    else:
        values = [bal[p] for p in people]
        full = (1 << n) - 1
        sums = [0] * (1 << n)
        for mask in range(1, 1 << n):
            low = mask & -mask
            sums[mask] = sums[mask ^ low] + values[low.bit_length() - 1]
        best = [0] * (1 << n)
        for mask in range(1, 1 << n):
            m = 0
            sub = mask
            while sub:
                low = sub & -sub
                cand = best[mask ^ low]
                if cand > m:
                    m = cand
                sub ^= low
            best[mask] = m + (1 if sums[mask] == 0 else 0)

        # Truy vết thứ tự bỏ người ra, ranh giới nhóm là chỗ tổng tiền tố bằng 0.
        order: list[int] = []
        mask = full
        while mask:
            bonus = 1 if sums[mask] == 0 else 0
            sub = mask
            while sub:
                low = sub & -sub
                if best[mask ^ low] + bonus == best[mask]:
                    order.append(low.bit_length() - 1)
                    mask ^= low
                    break
                sub ^= low
        order.reverse()

        groups = []
        current: list[P] = []
        running = 0
        for i in order:
            current.append(people[i])
            running += values[i]
            if running == 0:
                groups.append(current)
                current = []
        if current:  # pragma: no cover - tổng toàn bộ luôn bằng 0
            groups.append(current)

    transfers: list[Debt[P]] = []
    for g in groups:
        transfers.extend(_settle_group([(p, bal[p]) for p in g], key))
    transfers.sort(key=lambda d: (-d.amount, key(d.debtor), key(d.creditor)))
    return transfers
