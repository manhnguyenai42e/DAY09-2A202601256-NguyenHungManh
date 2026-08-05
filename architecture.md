# Kiến trúc hệ thống — K4 Day 9: Multi-Agent Điều tra Khiếu nại TMĐT (A2A + MCP)

Cohort **K4**, chính sách **EC_POLICY_V2**. **7 agent A2A** + **1 MCP server** (8 tool), toàn bộ chạy
local với model **Qwen3.5-4B** qua Ollama.

## 1. Nguyên tắc thiết kế: mỗi agent nghiệp vụ là một LLM agent, MCP tool là "giác quan"

Năm agent nghiệp vụ (Customer, Order & Product, Payment, Delivery, Policy) đều chạy chu trình 2 pha:

1. **Grounding (bám dữ liệu)** — gọi MCP tool của riêng mình để lấy dữ kiện từ 9 file CSV gốc.
   Agent **không được phép** bịa ra bất kỳ dữ kiện, mã ID hay con số nào không đến từ tool.
2. **Reasoning (suy luận)** — đưa dữ kiện đó cho model Qwen3.5-4B local kèm **system prompt riêng
   theo vai trò**, để model viết nhận định chuyên môn đi kèm trong `note` của gói handoff A2A
   (hàm `agent_reflect()` trong `src/agents/base.py`).

Mỗi case vì vậy phát sinh **~6 lời gọi LLM** từ 6 agent khác nhau với 6 vai trò khác nhau, và tất cả
đều được ghi vào `logging/trace.jsonl`.

**Điều LLM cố tình KHÔNG được giao: số học và định dạng mã bằng chứng.**
`EC_POLICY_V2` (README §4) là bảng luật đặc tả chính xác kèm công thức — không phải chỗ để phán đoán —
và grader **hard gate về 0 điểm** cả case chỉ vì lệch một xu hoặc sai định dạng một evidence ID.
Model 4B lượng tử hóa không đủ tin cậy để trừ ngày ra giờ, cộng tiền 2 chữ số thập phân, hay ghép
chuỗi `item:<order_id>:<n>`. Những việc đó nằm trong code Python thuần đã có unit test
(`src/mcp_server/policy_engine.py`, kiểm thử với order_id thật cho cả 6 nhánh primary issue) và được
expose thành MCP tool. Đây đúng là mô hình tool-use tiêu chuẩn: **model suy luận, máy tính tính toán.**

**Verifier là agent duy nhất không dùng LLM — và đó là chủ đích.** Nó là cổng cuối cùng trước khi
một case được ghi ra `output/`; một cổng gác có thể "ảo giác" ra chữ PASS thì không còn là cổng gác.
Verifier chạy kiểm tra deterministic về schema, trần mảng và đối chiếu bằng chứng với CSV gốc, và có
quyền trả case ngược lại cho Policy Agent làm lại.

## 2. Sơ đồ thành phần

```
                         ┌──────────────────────────────┐
                         │      MCP DATA SERVER          │  streamable-http :8765
                         │  (src/mcp_server/server.py)   │
                         │  8 tool:                       │
                         │   get_order                    │
                         │   get_customer_context         │
                         │   get_affected_entities        │
                         │   get_product_context          │
                         │   get_delivery_analysis        │
                         │   get_payment_reconciliation   │
                         │   apply_policy                 │
                         │   validate_case_output         │
                         └──────────────▲─────────────────┘
                                        │ MCP tool calls (mọi agent bên dưới)
      ┌────────────┬────────────┬──────┴─────┬────────────┬──────────────┐
      │            │            │            │            │              │
 ┌────▼───┐  ┌─────▼──────┐ ┌───▼─────┐ ┌────▼─────┐ ┌────▼─────┐  ┌─────▼─────┐
 │Customer│  │Order&Product│ │ Payment │ │ Delivery │ │  Policy  │  │ Verifier  │
 │ :9101  │  │   :9102     │ │  :9103  │ │  :9104   │ │  :9105   │  │  :9106    │
 │  +LLM  │  │   +LLM      │ │  +LLM   │ │  +LLM    │ │  +LLM    │  │ KHÔNG LLM │
 └────┬───┘  └──────┬──────┘ └────┬────┘ └────┬─────┘ └────┬─────┘  └─────┬─────┘
      │             │             │           │            │              │
      └─────────────┴──────┬──────┴───────────┘            │              │
                           │ A2A handoff (JSON-RPC message/send)          │
                    ┌──────▼────────┐                                    │
                    │  Coordinator   │────────────────────────────────────┘
                    │    :9100       │  4 agent evidence chạy SONG SONG
                    └──────┬─────────┘  → policy → verifier (retry tối đa 1 lần)
                           │
              output/EC_xxx.json  +  logging/trace.jsonl
```

Mỗi ô là một **HTTP service độc lập thật sự**, có `GET /.well-known/agent-card.json` (Agent Card:
tên, mô tả, url, skill) và `POST /a2a` triển khai phương thức JSON-RPC `message/send` của giao thức
A2A (`src/a2a_common/protocol.py`, `src/agents/base.py`). Script `scripts/run_agents.py` khởi động
MCP server và cả 7 agent đồng thời (một process Python, 8 server chạy song song bằng asyncio, mỗi
server một port riêng — quản lý process trên Windows đơn giản hơn 8 process OS, trong khi mỗi service
vẫn được địa chỉ hóa độc lập).

**Ghi chú về tầng A2A**: gói `a2a-sdk` (1.1.2) cài từ PyPI là SDK production đầy đủ — nhiều transport
gRPC/REST/JSON-RPC, task store gắn DB kèm Alembic migration, push notification, luồng xác thực — thiết
kế cho agent task chạy dài và có thể resume, không phải cho một batch classifier đồng bộ chạy một lượt.
Thay vì tiêu thời gian đấu nối cỗ máy task-lifecycle đó mà không được thêm điểm nào, phần **hợp đồng
giao tiếp thật sự** của A2A — Agent Card để khám phá + JSON-RPC `message/send` mang gói handoff có cấu
trúc — được hiện thực trực tiếp trên Starlette/httpx. Mỗi agent vẫn là một HTTP service riêng biệt có
card và endpoint JSON-RPC; thứ được bỏ qua chỉ là tầng lưu trữ task mà bài toán này không cần.

## 3. Vai trò agent, quyền truy cập dữ liệu và hợp đồng handoff

Mọi gói handoff (`src/a2a_common/protocol.py: HandoffPayload`) đều mang đủ hợp đồng tối thiểu mà đề
bài yêu cầu: `ticket_id`, `question` (câu hỏi được giao), `facts` (dữ kiện kèm evidence ID nguồn),
`evidence_ids`, `missing` (thiếu hoặc mâu thuẫn gì), `next_action` (đề xuất bước kế), và `note`
(nhận định do LLM viết).

| Agent | Port | MCP tool được gọi | Sản phẩm bàn giao | Vai trò của LLM |
|---|---|---|---|---|
| Customer | 9101 | `get_customer_context` | `customer_context` (customer_unique_id, related_order_ids) | **Có** — nhận định khách quen/khách mới, đơn liên quan đáng đối chiếu |
| Order & Product | 9102 | `get_affected_entities`, `get_product_context` | `affected_entities`, `product_context` | **Có** — nhận định độ phức tạp đơn (nhiều item / nhiều seller / nhiều ngành hàng) |
| Payment | 9103 | `get_payment_reconciliation`, `get_affected_entities` | `payment_reconciliation` | **Có** — nhận định thanh toán có khớp không, split payment hợp lệ không |
| Delivery | 9104 | `get_delivery_analysis` | `delivery_analysis` | **Có** — nhận định trễ hay không, lỗi thuộc seller hay đơn vị vận chuyển |
| Policy | 9105 | `apply_policy` | toàn bộ thân case (`case_assessment`, `root_cause_analysis`, `financial_resolution`, `resolution_actions`, `evidence_ids`) | **Có** — viết lập luận phán quyết, trích dẫn evidence ID |
| Verifier | 9106 | `validate_case_output` | `{valid, violations}` — schema, trần mảng (README §6), đối chiếu evidence ID và entity với CSV gốc | **Không, có chủ đích** — cổng cuối không được phép ảo giác ra kết quả đạt |
| Coordinator | 9100 | (chỉ đóng vai A2A client) | điều phối toàn bộ, ráp JSON cuối, ghi `output/` + `trace.jsonl` | Không — thuần điều phối |

**Luồng xử lý một ticket**: Coordinator phát song song cho Customer / Order & Product / Payment /
Delivery (`asyncio.gather` — bằng chứng độc lập nhau, không có ràng buộc thứ tự) → gộp dữ kiện, bàn
giao cho Policy → đưa case cho Verifier → nếu Verifier báo vi phạm thì trả ngược cho Policy làm lại
**tối đa 1 lần**; case vẫn còn lỗi thì vẫn được ghi ra file nhưng vi phạm được ghi rõ trong
`trace.jsonl` thay vì âm thầm bỏ qua — bài nộp bắt buộc phải luôn đủ đúng 50 file.

**Kiểm soát truy cập**: mỗi agent chỉ được gọi đúng các MCP tool liệt kê ở trên — ví dụ Delivery Agent
không có đường nào chạm tới dữ liệu thanh toán, Payment Agent không có đường nào chạm tới ngày giao
hàng. Verifier là agent duy nhất có thẩm quyền về schema và bằng chứng, và là cổng cuối cùng trước khi
bất kỳ case nào được ghi vào `output/`.

## 4. Cách tính confidence

README §6 không định nghĩa công thức cho `case_assessment.confidence`. Hàm
`policy_engine.compute_confidence` bắt đầu ở 0.95 khi case khớp sạch một nhánh luật, rồi trừ dần với
dữ liệu mỏng hoặc mơ hồ (đơn không có dòng item, thanh toán không khớp, hoặc case rơi vào nhánh dự
phòng thay vì khớp gọn một trong 6 điều kiện chính). Ghi rõ ở đây thay vì để LLM tự bịa ra một con số,
để kết quả tái lập được.

## 5. Model và môi trường chạy

- **Model**: `qwen3.5-4b-ec` — Qwen3.5-4B-Q4_K_M, import vào Ollama từ file GGUF có sẵn của LM Studio
  (`ollama/Modelfile.qwen35`) chứ không tải lại. **4B tham số**, thấp hơn nhiều so với trần 10B của đề;
  vừa với 6GB VRAM của laptop.
- **Được dùng bởi**: cả 5 agent nghiệp vụ (Customer, Order & Product, Payment, Delivery, Policy) — mỗi
  agent một lời gọi có role prompt riêng cho mỗi case, tổng ~6 lời gọi LLM/case. Không bao giờ dùng cho
  số học, ngưỡng phân loại hay định dạng evidence ID.
- Khai báo trong code tại `src/config.py`, đồng bộ sang `logging/metadata.json` theo đúng quy định nộp
  bài (không đặt trong `.env`).
- Nhiệt độ 0.1 vì đây là tác vụ kiểm toán/tuân thủ, cần ổn định thay vì sáng tạo.

## 6. Cách chạy

```bash
python scripts/run_agents.py    # bật MCP server (:8765) + 7 agent service (:9100-9106)
python scripts/run_batch.py --parallel 4   # terminal thứ 2: chạy 50 input/EC_*.json
                                            # ghi output/, trace.jsonl, metadata.json
                                            # thêm --fast để bỏ narration khi cần lặp nhanh
python scripts/validate_output.py   # kiểm tra trước khi nộp: 50 file, schema, evidence grounding
pytest                               # unit test policy engine + MCP tool
python src/web/server.py 8000        # dashboard demo chạy pipeline thật (cần run_agents đang chạy)
```

Chi tiết từng bước xem `HUONG_DAN_CHAY.md`.
