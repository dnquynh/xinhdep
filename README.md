# Zalo bot ghi thu chi

Nhắn một câu tự nhiên, bot tự hiểu số tiền, nhóm chi phí, ai trả, chia cho ai, rồi tính công nợ.

Tiến độ:
- Chặng 1 (lõi tính toán): xong.
- Chặng 2 (hiểu tin nhắn + chat thử trên máy): xong. Mặc định hiểu tin nhắn bằng quy tắc, miễn phí, không cần key.
- Chặng 3 (nối Zalo + deploy): chưa làm.

## Cài đặt

Cần Python 3.11 trở lên.

```bash
pip install -r requirements.txt pytest
cp .env.example .env        # không cần sửa gì nếu dùng bản miễn phí
```

## Chạy thử

```bash
python3 -m pytest -q                                   # toàn bộ test, không cần key
python3 demo_chang1.py                                 # lõi tính toán với 7 câu mẫu, không cần key
python3 -m thuchi.cli                                  # chat thử với bot
python3 scripts/thu_ai_that.py                         # chỉ khi dùng Claude: kiểm tra AI hiểu đúng (cần key)
python3 -m thuchi.cli --db demo.db --script scripts/cau_mau.txt   # chạy lại 7 câu mẫu tự động
```

## Bot hiểu gì

- `tiền điện 450k`: chi cá nhân, AI tự xếp vào nhóm.
- `ăn lẩu 600k, tôi trả, chia với Nam và Lan`: chi chung. Bot hỏi lại cách chia, trả lời `ok` là chia đều hoặc ghi `Nam 250k, Lan 250k, tôi 100k`.
- `ăn lẩu 600k chia đều với Nam và Lan`: ghi luôn, không hỏi.
- `cho Hùng mượn 2tr`, `vay chị Mai 1tr5`, `Hùng trả 500k`, `trả chị Mai 1tr`: vay và trả nợ.
- `lương 15tr`: thu nhập.

Lệnh: `tổng kết`, `tổng kết tháng 10`, `công nợ`, `xóa`, `sửa: <câu mới>`, `hủy`, `help`.

## Bot hỏi lại khi

- Số tiền mơ hồ: "450" là 450 nghìn hay 450 đồng?
- Không chắc nhóm: bot đưa danh sách để chọn số, và nhớ lựa chọn cho lần sau.
- Gặp tên người mới: trả lời `thêm`, hoặc ghi tên người đã có nếu đó là tên gọi khác ("Nam béo" là "Nam").
- Chi chung mà không nói "chia đều" và không ghi số từng người.
- Các phần chia cộng lại không khớp tổng.
- Không rõ ai trả, ai mượn.
- Trả nợ nhiều hơn số đang nợ.

## Cấu trúc

| File | Việc |
|---|---|
| `thuchi/money.py` | Đọc số tiền (50k, 1tr2, 1.5tr, 150.000…) ra số nguyên đồng |
| `thuchi/splits.py` | Chia đều (tiền lẻ người trả chịu) và chia theo số ghi rõ |
| `thuchi/debts.py` | Bù trừ công nợ từng cặp, rút gọn ít lần chuyển khoản nhất |
| `thuchi/store.py` | Lưu SQLite: người, tên gọi khác, nhóm, giao dịch, phần chia, câu hỏi đang chờ |
| `thuchi/rule_parser.py` | Mặc định: hiểu tin nhắn bằng từ khóa và mẫu câu, miễn phí, nhớ nhóm bạn đã chọn |
| `thuchi/ai_parser.py` | Tùy chọn: gọi Claude Haiku (tốn phí, cần key, đặt `THUCHI_PARSER=claude`) |
| `thuchi/bot.py` | Hội thoại: ghi, hỏi lại, tổng kết, công nợ, xóa, sửa |
| `thuchi/cli.py` | Chat thử trên máy |

Bộ hiểu tin nhắn (quy tắc hay AI) chỉ tách câu chữ. Đổi chữ ra số tiền, chia tiền, cộng trừ công nợ đều do code làm.

Bản miễn phí nhận tên người là: "tôi/mình", người đã có trong sổ (viết thường cũng được), chữ viết hoa ("Nam"),
và "anh/chị + tên". Người mới thì nên viết hoa chữ đầu. Khi bot hỏi nhóm và bạn chọn, bot nhớ cho lần sau.

## Quy tắc đã chốt

- Tiền luôn là số nguyên đồng.
- Chia đều chỉ khi bạn nói rõ "chia đều"/"chia đôi". Làm tròn theo nghìn, tiền lẻ người trả chịu.
- Tổng kết theo nhóm chỉ tính phần của bạn. Cho vay, đi vay, trả nợ không tính vào thu chi.
- Công nợ tính trên toàn bộ lịch sử, không reset theo tháng.
- Ngày ghi là ngày nhắn tin (giờ Việt Nam). Chưa hiểu "hôm qua", "tuần trước".
