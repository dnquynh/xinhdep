# Zalo bot ghi thu chi

Đang làm chặng 1/3: lõi tính toán. Chưa có AI và chưa nối Zalo.

## Chạy thử

Cần Python 3.11 trở lên và pytest.

```bash
python3 -m pytest -q        # chạy toàn bộ test
python3 demo_chang1.py      # ghi 7 câu mẫu, in công nợ và tổng kết
```

## Cấu trúc

| File | Việc |
|---|---|
| `thuchi/money.py` | Đọc số tiền (50k, 1tr2, 1.5tr, 150.000…) ra số nguyên đồng |
| `thuchi/splits.py` | Chia đều (tiền lẻ người trả chịu) và chia theo số ghi rõ |
| `thuchi/debts.py` | Bù trừ công nợ từng cặp, rút gọn ít lần chuyển khoản nhất |
| `thuchi/store.py` | Lưu SQLite: người, tên gọi khác, nhóm, giao dịch, phần chia, tổng kết |
| `thuchi/schema.sql` | Lược đồ dữ liệu (SQL kiểu SQLite, dùng được cho D1/Turso) |

## Quy tắc đã chốt

- Tiền luôn là số nguyên đồng. Số trơn dưới 1.000 (ví dụ "450") thì bot hỏi lại đơn vị.
- Chia đều thì làm tròn theo nghìn, tiền lẻ người trả chịu.
- Chia theo số ghi rõ thì các phần phải cộng đúng tổng, lệch là bot hỏi lại.
- Tổng kết theo nhóm chỉ tính phần của bạn. Cho vay, đi vay, trả nợ không tính vào thu chi.
- Công nợ tính trên toàn bộ lịch sử, không reset theo tháng.
