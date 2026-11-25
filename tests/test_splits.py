import pytest

from thuchi.splits import SplitError, SplitMismatch, split_equal, split_exact


def test_split_equal_even():
    assert split_equal(600_000, ["tôi", "Nam", "Lan"], "tôi") == {"tôi": 200_000, "Nam": 200_000, "Lan": 200_000}


def test_split_equal_two_people():
    assert split_equal(120_000, ["tôi", "Nam"], "Nam") == {"tôi": 60_000, "Nam": 60_000}


def test_split_equal_remainder_goes_to_payer_and_rounds_to_thousand():
    shares = split_equal(100_000, ["tôi", "Nam", "Lan"], "Nam")
    assert shares == {"tôi": 33_000, "Nam": 34_000, "Lan": 33_000}
    assert sum(shares.values()) == 100_000


def test_split_equal_odd_amount_rounds_to_dong():
    shares = split_equal(10_001, ["tôi", "Nam"], "tôi")
    assert shares == {"tôi": 5_001, "Nam": 5_000}


def test_split_equal_payer_not_participating_keeps_remainder():
    # Tôi trả hộ vé cho Nam và Lan, tiền lẻ tôi chịu.
    shares = split_equal(100_000, ["Nam", "Lan", "Hùng"], "tôi")
    assert shares == {"Nam": 33_000, "Lan": 33_000, "Hùng": 33_000, "tôi": 1_000}
    assert sum(shares.values()) == 100_000


def test_split_equal_dedup_participants():
    assert split_equal(100_000, ["Nam", "Nam", "tôi"], "tôi") == {"Nam": 50_000, "tôi": 50_000}


def test_split_equal_errors():
    with pytest.raises(SplitError):
        split_equal(0, ["a"], "a")
    with pytest.raises(SplitError):
        split_equal(100_000, [], "a")


def test_split_exact_ok():
    assert split_exact(600_000, {"Nam": 250_000, "Lan": 250_000, "tôi": 100_000}) == {
        "Nam": 250_000,
        "Lan": 250_000,
        "tôi": 100_000,
    }


def test_split_exact_mismatch_reports_missing():
    with pytest.raises(SplitMismatch) as exc:
        split_exact(600_000, {"Nam": 250_000, "Lan": 250_000})
    assert exc.value.missing == 100_000


def test_split_exact_over():
    with pytest.raises(SplitMismatch) as exc:
        split_exact(600_000, {"Nam": 400_000, "Lan": 300_000})
    assert exc.value.missing == -100_000


def test_split_exact_drops_zero_and_rejects_negative():
    assert split_exact(100_000, {"Nam": 100_000, "Lan": 0}) == {"Nam": 100_000}
    with pytest.raises(SplitError):
        split_exact(100_000, {"Nam": 150_000, "Lan": -50_000})
