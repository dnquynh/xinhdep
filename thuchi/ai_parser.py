"""Dùng Claude để hiểu câu chữ trong tin nhắn chi tiêu.

AI chỉ làm một việc: tách câu thành các trường có cấu trúc (loại giao dịch, đoạn chữ
ghi số tiền, nhóm, ai trả, chia cho ai). Đổi chữ ra số tiền, chia tiền, cộng trừ
công nợ đều do code làm ở money.py / splits.py / store.py.
"""

from __future__ import annotations

import os
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from .store import EXPENSE_CATEGORIES, INCOME_CATEGORIES

MODEL = "claude-haiku-5-5"

Kind = Literal["chi", "thu", "chi_chung", "cho_vay", "di_vay", "tra_no", "khong_ro"]
SplitMode = Literal["chia_deu", "ghi_ro", "chua_noi"]


class Share(BaseModel):
    name: str = Field(description="Tên người như trong tin nhắn; 'tôi' nếu là người nhắn")
    amount_text: str = Field(description="Đoạn chữ ghi số tiền của người này, chép nguyên văn")


class ParsedMessage(BaseModel):
    kind: Kind
    amount_text: str | None = Field(description="Đoạn chữ ghi tổng số tiền, chép nguyên văn, ví dụ '1tr5'")
    category: str | None = Field(description="Một nhóm trong danh sách, hoặc null nếu không chắc")
    note: str = Field(description="Mô tả ngắn khoản tiền, ví dụ 'ăn lẩu', 'tiền điện'")
    payer: str | None = Field(description="Người bỏ tiền ra (người trả, người cho vay, người trả nợ)")
    receiver: str | None = Field(description="Người nhận tiền (người vay, người được trả nợ)")
    participants: list[str] = Field(description="chi_chung: mọi người cùng dùng, gồm cả người trả nếu họ cũng dùng")
    split_mode: SplitMode
    shares: list[Share] = Field(description="Chỉ khi split_mode = ghi_ro")


SYSTEM_PROMPT = f"""Bạn tách tin nhắn ghi thu chi tiếng Việt thành dữ liệu có cấu trúc. Người nhắn là "tôi".
Bạn không tính toán gì, chỉ chép lại đúng chữ trong tin nhắn.

Loại giao dịch (kind):
- chi: tôi tự chi cho mình, không có ai khác cùng dùng. Ví dụ "tiền điện 450k", "cafe 30k".
- thu: tôi nhận thu nhập. Ví dụ "lương tháng 11 15tr", "thưởng 2tr".
- chi_chung: một người trả, có người khác cùng dùng hoặc được trả hộ. Ví dụ "ăn lẩu 600k với Nam",
  "Nam trả taxi 120k cho tôi với Nam", "Lan mua hộ tôi cuốn sách 80k".
- cho_vay: tôi đưa tiền cho người khác mượn. Ví dụ "cho Hùng mượn 2tr". payer = "tôi", receiver = người mượn.
- di_vay: tôi mượn tiền người khác. Ví dụ "vay chị Mai 1tr5". payer = người cho mượn, receiver = "tôi".
- tra_no: có người trả lại tiền đã nợ. Ví dụ "Hùng trả 500k" (payer = Hùng, receiver = "tôi"),
  "trả chị Mai 1tr" (payer = "tôi", receiver = Mai).
- khong_ro: không phải tin ghi tiền, hoặc không hiểu.

Quy tắc:
- amount_text: chép nguyên văn đoạn ghi tổng số tiền ("600k", "1tr5", "150.000đ"). Không đổi đơn vị. Không có thì null.
- category chỉ dùng cho chi và chi_chung, chọn đúng một trong: {", ".join(EXPENSE_CATEGORIES)}.
  Với thu dùng: {", ".join(INCOME_CATEGORIES)}. Không chắc nhóm nào thì để null, đừng đoán.
  Với cho_vay, di_vay, tra_no để null.
- Tên người: chép như trong tin nhắn ("chị Mai", "Nam"). Người nhắn luôn ghi là "tôi".
- chi: payer = "tôi", participants = [].
- chi_chung: payer = người trả (null nếu tin nhắn không nói ai trả). participants = tất cả người cùng dùng,
  gồm "tôi" nếu tôi cũng dùng, gồm người trả nếu người trả cũng dùng. "ăn lẩu với Nam và Lan, tôi trả"
  -> participants = ["tôi", "Nam", "Lan"].
- split_mode:
  - chia_deu: CHỈ khi tin nhắn có chữ "chia đều" hoặc "chia đôi".
  - ghi_ro: khi tin nhắn ghi số tiền của từng người, điền shares.
  - chua_noi: mọi trường hợp còn lại, kể cả "chia với Nam và Lan" mà không nói chia đều.
  Loại không phải chi_chung thì để chua_noi.
- shares để [] nếu split_mode không phải ghi_ro.
"""


class Parser(Protocol):
    def parse(self, text: str) -> ParsedMessage: ...


class AIUnavailable(RuntimeError):
    """Không gọi được AI (thiếu key, mất mạng, bị từ chối)."""


class ClaudeParser:
    def __init__(self, api_key: str | None = None, model: str = MODEL):
        import anthropic

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise AIUnavailable("Chưa có ANTHROPIC_API_KEY")
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model

    def parse(self, text: str) -> ParsedMessage:
        a = self._anthropic
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
                output_config={"effort": "low"},
                output_format=ParsedMessage,
            )
        except a.AuthenticationError as exc:
            raise AIUnavailable("API key không hợp lệ") from exc
        except a.RateLimitError as exc:
            raise AIUnavailable("AI đang quá tải, thử lại sau ít phút") from exc
        except a.APIConnectionError as exc:
            raise AIUnavailable("Không kết nối được AI") from exc
        except a.APIStatusError as exc:
            raise AIUnavailable(f"AI báo lỗi {exc.status_code}") from exc

        if response.stop_reason == "refusal" or response.parsed_output is None:
            return ParsedMessage(
                kind="khong_ro",
                amount_text=None,
                category=None,
                note="",
                payer=None,
                receiver=None,
                participants=[],
                split_mode="chua_noi",
                shares=[],
            )
        return response.parsed_output
