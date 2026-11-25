-- Lược đồ dữ liệu. Viết bằng SQL chuẩn của SQLite để sau này chuyển sang
-- Cloudflare D1 hoặc Turso (cùng phương ngữ SQLite) không phải sửa.

CREATE TABLE IF NOT EXISTS people (
    id            INTEGER PRIMARY KEY,
    display_name  TEXT NOT NULL,
    is_me         INTEGER NOT NULL DEFAULT 0 CHECK (is_me IN (0, 1))
);

-- Tên gọi khác của một người, đã chuẩn hóa: "Nam", "anh Nam", "nam" -> "nam"
CREATE TABLE IF NOT EXISTS aliases (
    alias      TEXT PRIMARY KEY,
    person_id  INTEGER NOT NULL REFERENCES people(id)
);

CREATE TABLE IF NOT EXISTS categories (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    kind  TEXT NOT NULL CHECK (kind IN ('chi', 'thu'))
);

-- kind:
--   chi        chi cá nhân của tôi           payer = tôi
--   thu        thu nhập của tôi              receiver = tôi
--   chi_chung  một người trả, nhiều người chia (bảng splits)
--   vay        payer cho receiver mượn tiền (cho vay hoặc đi vay)
--   tra_no     payer trả nợ cho receiver
CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('chi', 'thu', 'chi_chung', 'vay', 'tra_no')),
    amount       INTEGER NOT NULL CHECK (amount > 0),
    category_id  INTEGER REFERENCES categories(id),
    payer_id     INTEGER REFERENCES people(id),
    receiver_id  INTEGER REFERENCES people(id),
    note         TEXT NOT NULL DEFAULT '',
    raw_text     TEXT NOT NULL DEFAULT '',
    occurred_on  TEXT NOT NULL,              -- YYYY-MM-DD, giờ Việt Nam
    created_at   TEXT NOT NULL,              -- ISO 8601
    deleted_at   TEXT                        -- xóa mềm, NULL là còn hiệu lực
);

CREATE INDEX IF NOT EXISTS idx_tx_occurred ON transactions (occurred_on) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS splits (
    transaction_id  INTEGER NOT NULL REFERENCES transactions(id),
    person_id       INTEGER NOT NULL REFERENCES people(id),
    amount          INTEGER NOT NULL CHECK (amount > 0),
    PRIMARY KEY (transaction_id, person_id)
);

-- Câu hỏi bot đang chờ người dùng trả lời (mỗi cuộc chat tối đa một câu).
CREATE TABLE IF NOT EXISTS pending (
    chat_id     TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,             -- JSON bản nháp giao dịch + loại câu hỏi
    created_at  TEXT NOT NULL
);
