import pytest

from thuchi.money import AmbiguousAmount, AmountError, format_vnd, parse_amount


@pytest.mark.parametrize(
    "text, expected",
    [
        # nghìn
        ("50k", 50_000),
        ("50K", 50_000),
        ("50 k", 50_000),
        ("50 nghìn", 50_000),
        ("50 ngàn", 50_000),
        ("50 nghin", 50_000),
        ("120k", 120_000),
        ("1k5", 1_500),
        # số đầy đủ
        ("150.000", 150_000),
        ("150,000", 150_000),
        ("150000", 150_000),
        ("150 000", 150_000),
        ("150.000đ", 150_000),
        ("150.000 đ", 150_000),
        ("150000 vnd", 150_000),
        ("150.000 đồng", 150_000),
        ("1.500.000", 1_500_000),
        ("1,500,000", 1_500_000),
        ("1000", 1_000),
        # triệu viết tắt
        ("1tr2", 1_200_000),
        ("1tr5", 1_500_000),
        ("1tr25", 1_250_000),
        ("1tr250", 1_250_000),
        ("2tr05", 2_050_000),
        ("15tr", 15_000_000),
        ("1 triệu 2", 1_200_000),
        ("1 triệu 200 nghìn", 1_200_000),
        ("1tr200k", 1_200_000),
        # triệu thập phân
        ("1.5tr", 1_500_000),
        ("1,5tr", 1_500_000),
        ("1.5 triệu", 1_500_000),
        ("2 triệu", 2_000_000),
        ("2 trieu", 2_000_000),
        ("2 củ", 2_000_000),
        ("0.5tr", 500_000),
        # tỷ
        ("1 tỷ 2", 1_200_000_000),
        ("1.2 tỷ", 1_200_000_000),
        # hoa thường, khoảng trắng thừa
        ("  1TR2  ", 1_200_000),
        ("1  Triệu", 1_000_000),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["450", "50", "1.5", "1,25"])
def test_ambiguous_amounts_need_question(text):
    with pytest.raises(AmbiguousAmount):
        parse_amount(text)


@pytest.mark.parametrize("text", ["", "   ", "abc", "50kk", "1.2.3tr4", "0k", "1.2345k", "1tr2tr", "1k2tr"])
def test_invalid_amounts(text):
    with pytest.raises(AmountError):
        parse_amount(text)


def test_amount_is_always_int():
    assert type(parse_amount("1.5tr")) is int
    assert type(parse_amount("1tr2")) is int


def test_format_vnd():
    assert format_vnd(1_500_000) == "1.500.000đ"
    assert format_vnd(0) == "0đ"
    assert format_vnd(-60_000) == "-60.000đ"
