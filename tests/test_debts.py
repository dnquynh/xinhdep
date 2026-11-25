import itertools
import random

from thuchi.debts import Debt, net_balances, pairwise_balances, simplify


def _apply(edges, transfers):
    """Áp dụng các lần chuyển khoản, trả về số dư còn lại (phải bằng 0 hết)."""
    paid = [Debt(t.creditor, t.debtor, t.amount) for t in transfers]
    return net_balances(list(edges) + paid)


def test_pairwise_offsets_both_directions():
    edges = [Debt("Nam", "tôi", 200_000), Debt("tôi", "Nam", 60_000)]
    assert pairwise_balances(edges) == [Debt("Nam", "tôi", 140_000)]


def test_pairwise_fully_settled_disappears():
    edges = [Debt("Hùng", "tôi", 2_000_000), Debt("tôi", "Hùng", 2_000_000)]
    assert pairwise_balances(edges) == []


def test_net_balances():
    edges = [Debt("A", "B", 100), Debt("B", "C", 100)]
    assert net_balances(edges) == {"A": -100, "C": 100}


def test_simplify_chain_becomes_one_transfer():
    # A nợ B 100, B nợ C 100 -> A trả thẳng C 100.
    edges = [Debt("A", "B", 100), Debt("B", "C", 100)]
    assert simplify(edges) == [Debt("A", "C", 100)]


def test_simplify_three_people_cycle_cancels():
    edges = [Debt("A", "B", 100), Debt("B", "C", 100), Debt("C", "A", 100)]
    assert simplify(edges) == []


def test_simplify_four_people_finds_two_pairs():
    # Số dư: A -50, B +50, C -70, D +70. Tham lam ngây thơ có thể ra 3 lần, tối ưu là 2.
    edges = [Debt("A", "D", 50), Debt("C", "D", 20), Debt("C", "B", 50)]
    result = simplify(edges)
    assert len(result) == 2
    assert _apply(edges, result) == {}
    assert set(result) == {Debt("A", "B", 50), Debt("C", "D", 70)}


def test_simplify_six_people_two_zero_groups():
    # Số dư: +6 +3 +2 -5 -3 -3. Có thể chia thành 2 nhóm tổng 0 -> 4 lần chuyển.
    bal = {"A": 6, "B": 3, "C": 2, "D": -5, "E": -3, "F": -3}
    edges = [Debt(p, "_", -v) if v < 0 else Debt("_", p, v) for p, v in bal.items()]
    result = simplify(edges)
    assert _apply(edges, result) == {}
    # Tối ưu: {A,E,F} 2 lần + {B,C,D} 2 lần = 4
    assert len(result) == 4


def _min_transfers_bruteforce(balances: list[int]) -> int:
    n = len(balances)
    best = 0
    # số nhóm tổng 0 nhiều nhất, thử mọi cách gán nhóm
    for labels in itertools.product(range(n), repeat=n):
        sums = {}
        for v, g in zip(balances, labels):
            sums[g] = sums.get(g, 0) + v
        if all(s == 0 for s in sums.values()):
            best = max(best, len(sums))
    return n - best


def test_simplify_is_optimal_on_random_small_cases():
    rng = random.Random(42)
    for _ in range(40):
        n = rng.randint(2, 6)
        people = [f"P{i}" for i in range(n)]
        edges = []
        for _ in range(rng.randint(1, 8)):
            a, b = rng.sample(people, 2)
            edges.append(Debt(a, b, rng.choice([10, 20, 30, 50])))
        result = simplify(edges)
        assert _apply(edges, result) == {}
        bal = list(net_balances(edges).values())
        if bal:
            assert len(result) == _min_transfers_bruteforce(bal)


def test_simplify_many_people_falls_back_and_still_settles():
    rng = random.Random(7)
    people = [f"P{i}" for i in range(20)]
    edges = [Debt(*rng.sample(people, 2), rng.randint(1, 100) * 1000) for _ in range(60)]
    result = simplify(edges)
    assert _apply(edges, result) == {}
    assert len(result) <= len(net_balances(edges)) - 1
