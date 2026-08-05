# Kiến trúc hệ thống — K4 Day 9: Multi-Agent Điều tra Khiếu nại TMĐT (A2A + MCP)

Cohort **K4**, chính sách **EC_POLICY_V2**. **7 agent A2A** + **1 MCP server** (7 tool), model mặc
định **Qwen3-8B** qua OpenRouter (hosted) — xem mục 5 cho provider layer 3 chiều (OpenRouter/Ollama
local/OpenAI).

## 1. Nguyên tắc thiết kế: LLM tự làm mọi thứ, MCP chỉ trả dữ liệu thô

**Cả 7 agent đều dùng LLM, và không có hàm Python nào tính hộ nội dung nghiệp vụ.** Tool MCP
(`src/mcp_server/server.py`) chỉ làm đúng một việc: lọc dữ liệu thô từ CSV theo khóa (`order_id`,
`customer_unique_id`, `product_id`...) — không cộng tiền, không trừ ngày giờ, không dựng chuỗi
evidence ID, không phân loại. Mọi phép tính và quyết định nghiệp vụ nằm hoàn toàn trong lý luận của
model.

Sáu agent nghiệp vụ chạy vòng lặp tool-calling thật (`agent_tool_loop()` trong `src/agents/base.py`):

1. Hệ thống lấy schema các MCP tool dữ liệu thô mà agent **được phép** dùng, cộng thêm đúng một tool
   nội bộ **"final tool"** (ví dụ `report_payment`) — cách duy nhất agent có thể nộp kết quả.
2. **Model tự quyết định** gọi tool dữ liệu nào, với tham số gì; hệ thống thực thi lời gọi đó lên MCP
   server và đưa **kết quả thô thật** về cho model.
3. Model tự tính toán từ dữ liệu thô đó (cộng, trừ, làm tròn, dựng chuỗi ID, phân loại...) rồi gọi
   final tool với toàn bộ kết quả đã tính. Hệ thống **bắt lấy đúng arguments model đưa ra làm kết quả
   cuối cùng — không sửa, không tính lại, không có phương án dự phòng**. Nếu model không gọi được final
   tool sau vài lượt, agent báo lỗi và case đó được ghi nhận là fail (`cases_failed` trong
   `metadata.json`) thay vì tự chế số liệu.

Trace ghi lại `tools_called_by_llm` cho từng agent — xem được chính xác model đã chọn gọi gì.

Agent thứ 7 (Coordinator) dùng LLM ở 2 thời điểm: **triage** lúc nhận ticket (nêu trọng tâm điều
tra) và **synthesis** lúc đóng hồ sơ đã qua kiểm định. Ngoài 2 lời gọi LLM đó, Coordinator chỉ **ghép**
các sub-object mà 4 agent nghiệp vụ + Policy Agent đã tự tính vào đúng vị trí theo schema README §6
(`_assemble_case()` trong `src/agents/coordinator.py`) — thuần định tuyến dữ liệu, không tính toán
hay quyết định nội dung nào.

**Ranh giới quan trọng — `facts` và `note` tách bạch:**

| | `facts` | `note` |
|---|---|---|
| Nội dung | JSON có cấu trúc (đã do model tự tính) | Văn xuôi tiếng Việt |
| Nguồn | argument model đưa vào final tool | model viết cùng lúc, trong cùng lời gọi final tool |
| Đi vào | **file output được chấm điểm** | chỉ `trace.jsonl` |

**Không còn "safety net" quay về deterministic.** Thiết kế trước có một lớp fallback: nếu model không
gọi tool, code tự gọi hàm Python tính sẵn. Lớp đó đã bị bỏ hoàn toàn cùng với
`src/mcp_server/policy_engine.py` — không còn hàm nào để fallback về. Đánh đổi: case nào model không
gọi đúng final tool sẽ fail thẳng (không có số liệu, dù sai) thay vì âm thầm có một câu trả lời không
phải do agent tự nghĩ ra.

**Verifier là agent duy nhất mà LLM không có quyền quyết định PASS/FAIL — và đó là chủ đích.** Nó là
cổng cuối cùng trước khi một case được ghi ra `output/`; một cổng gác có thể "ảo giác" ra chữ PASS thì
không còn là cổng gác. Lớp code deterministic duy nhất còn lại trong toàn hệ thống là
`validate_case_output`: kiểm schema, trần mảng, đối chiếu evidence ID/entity với CSV gốc — nó **không
bao giờ điền hay sửa một giá trị nào**, chỉ chấp nhận hoặc từ chối những gì agent đã tự tạo ra.

## 2. Sơ đồ thành phần

```
                         ┌──────────────────────────────┐
                         │      MCP DATA SERVER          │  streamable-http :8765
                         │  (src/mcp_server/server.py)   │
                         │  7 tool (raw fetch + rulebook  │
                         │  + validator, KHÔNG tính gì):   │
                         │   get_order                    │
                         │   get_order_items               │
                         │   get_order_payments            │
                         │   get_customer                  │
                         │   get_related_orders            │
                         │   get_products                  │
                         │   get_policy_rulebook            │
                         │   validate_case_output          │
                         └──────────────▲─────────────────┘
                                        │ MCP tool calls (mọi agent bên dưới)
      ┌────────────┬────────────┬──────┴─────┬────────────┬──────────────┐
      │            │            │            │            │              │
 ┌────▼───┐  ┌─────▼──────┐ ┌───▼─────┐ ┌────▼─────┐ ┌────▼─────┐  ┌─────▼─────┐
 │Customer│  │Order&Product│ │ Payment │ │ Delivery │ │  Policy  │  │ Verifier  │
 │ :9101  │  │   :9102     │ │  :9103  │ │  :9104   │ │  :9105   │  │  :9106    │
 │  +LLM  │  │   +LLM      │ │  +LLM   │ │  +LLM    │ │  +LLM    │  │ +LLM audit│
 │ (tự    │  │  (tự dựng   │ │ (tự     │ │ (tự trừ  │ │ (tự ra   │  │ (pass/fail│
 │  lọc)  │  │   ID/dedupe)│ │  cộng)  │ │  giờ)    │ │  phán    │  │  do code) │
 └────┬───┘  └──────┬──────┘ └────┬────┘ └────┬─────┘ │  quyết)  │  └─────┬─────┘
      │             │             │           │       └────┬─────┘        │
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
(nhận định do LLM viết, nộp cùng lúc với final tool).

| Agent | Port | MCP tool dữ liệu thô | Final tool (nộp kết quả) | Agent tự tính gì |
|---|---|---|---|---|
| Customer | 9101 | `get_customer`, `get_related_orders` | `report_customer` | Tự loại order hiện tại khỏi danh sách, tự cắt trần 5 |
| Order & Product | 9102 | `get_order_items`, `get_products` | `report_order_product` | Tự dựng `item_ids` dạng `"<order_id>:<n>"`, tự khử trùng lặp seller/product/category |
| Payment | 9103 | `get_order_items`, `get_order_payments` | `report_payment` | Tự cộng item_total/freight_total/payment_total, tự trừ difference, tự so `<= 0.10` để ra `reconciled` |
| Delivery | 9104 | `get_order`, `get_order_items` | `report_delivery` | Tự trừ ngày giờ ra `delivery_variance_hours` và `handoff_variance_hours` theo từng seller |
| Policy | 9105 | `get_policy_rulebook`, `get_order` | `report_case` | Tự đối chiếu 6 nhánh EC_POLICY_V2, tự dựng `secondary_issues`/`root_cause_analysis`/`evidence_ids`/`resolution_actions`, tự chọn `recommended_refund_brl` từ số liệu đã có, tự đánh giá `confidence` |
| Verifier | 9106 | `validate_case_output` | *(không có — chỉ chấp nhận/từ chối)* | Không tính gì; LLM chỉ audit độc lập, không quyết định PASS/FAIL |
| Coordinator | 9100 | *(không gọi MCP)* | *(không có)* | Không tính gì; chỉ ghép sub-object các agent khác đã tự tính |

### 3.1. Verifier: hai lớp bất đối xứng

- **Lớp 1 — code deterministic** (`validate_case_output`): kiểm schema, trần mảng, đối chiếu từng
  evidence ID và entity với CSV gốc. **Chỉ lớp này quyết định PASS/FAIL.**
- **Lớp 2 — LLM audit độc lập**: model đọc lại case, soát tính nhất quán nghiệp vụ (số tiền hoàn có
  đúng loại vấn đề không, `case_status` có khớp không) — bắt được vấn đề *ngữ nghĩa* mà rule không
  diễn đạt nổi. Nhận định của nó **thêm** phát hiện, không **xóa** được phát hiện của lớp 1.

Vì sao bất đối xứng: nếu LLM được quyền lật FAIL→PASS thì một lần ảo giác là lọt case hỏng = 0 điểm.
Code cho *precision* (không bao giờ lọt case sai), model cho *recall* (bắt thứ rule không mã hóa được).

**Luồng xử lý một ticket**: Coordinator phát song song cho Customer / Order & Product / Payment /
Delivery (`asyncio.gather` — bằng chứng độc lập nhau, không có ràng buộc thứ tự) → mỗi agent tự tính
phần việc của mình → Coordinator ghép lại, bàn giao cho Policy → Policy tự ra phán quyết + tự dựng
phần còn lại của case → Coordinator ghép case hoàn chỉnh, đưa cho Verifier → nếu Verifier báo vi phạm
thì gọi lại Policy Agent làm lại **tối đa 1 lần**; case vẫn còn lỗi thì vẫn được ghi ra file nhưng vi
phạm được ghi rõ trong `trace.jsonl` thay vì âm thầm bỏ qua — bài nộp bắt buộc phải luôn đủ đúng 50
file.

**Kiểm soát truy cập**: mỗi agent chỉ được gọi đúng các MCP tool dữ liệu thô liệt kê ở trên — ví dụ
Delivery Agent không có đường nào chạm tới dữ liệu thanh toán, Payment Agent không có đường nào chạm
tới ngày giao hàng. Verifier là agent duy nhất có thẩm quyền về schema và bằng chứng, và là cổng cuối
cùng trước khi bất kỳ case nào được ghi vào `output/`.

## 4. Confidence

`case_assessment.confidence` không còn được tính bằng công thức Python (README §6 vốn cũng không định
nghĩa công thức nào). Đây giờ là đánh giá chủ quan của chính Policy Agent về độ tin cậy phán quyết nó
vừa đưa ra — một phần của `report_case`, do model tự viết ra như mọi trường khác trong case.

## 5. Model và môi trường chạy

Hệ thống có **provider layer chuyển được 3 chiều** (`EC_LLM_PROVIDER` trong `src/config.py`:
`ollama` | `openrouter` | `openai`), tên model khai báo trong code theo đúng quy định nộp bài; chỉ
API key nằm trong `.env` (không commit).

**Mặc định và dùng để nộp bài: OpenRouter, model Qwen3-8B.**

| | Đang dùng để nộp bài | Có sẵn trong code |
|---|---|---|
| Model | `qwen/qwen3-8b` qua OpenRouter | `qwen3.5-4b-ec` local qua Ollama; `gpt-4o-mini` qua OpenAI |
| Tham số | **8B — model card chính thức của Qwen** | 4.2B (local, chứng minh được) / không công bố chính thức (gpt-4o-mini) |
| Chạy ở | OpenRouter API (hosted) | Ollama local `localhost:11434` / OpenAI API |
| Tốc độ | ~1-2s/lượt gọi | ~10s/lượt gọi (local, GPU laptop) / ~1-2s (OpenAI) |

**Vì sao không dùng Llama-3.1-8B-Instruct** (cũng 8B, cũng có model card chính thức từ Meta, đã thử
đầu tiên): qua OpenRouter, model này có thói quen rất cố chấp — gộp luôn tool "nộp kết quả" vào
chung một lượt với tool tra dữ liệu, TRƯỚC KHI thấy kết quả thật của tool đó, tức là đoán số liệu
thay vì đọc thật. `agent_tool_loop()` (`src/agents/base.py`) có chốt chặn: **không bao giờ chấp
nhận lời gọi final tool nếu nó đi kèm bất kỳ tool nào khác trong cùng một lượt** — vì chấp nhận
nghĩa là để case dựa trên phỏng đoán thay vì dữ liệu thật. Với Llama-3.1-8B-Instruct, chốt chặn này
đúng nhưng khiến agent bị kẹt lặp vô hạn (model cứ lặp lại đúng kiểu gộp bị từ chối). Qwen3-8B và
Ministral-8B-2512 (cũng 8B, model card Mistral) đều test ổn định — gọi đúng từng tool một, không
gộp — nên chọn Qwen3-8B làm mặc định.

**Lưu ý tuân thủ**: đề yêu cầu mỗi agent dùng model ≤10B tham số. `qwen/qwen3-8b` thỏa mãn hiển
nhiên và chứng minh được (model card Qwen ghi rõ 8B: https://huggingface.co/Qwen/Qwen3-8B). Nhánh
Ollama local (`qwen3.5-4b-ec`, 4.2B) và OpenAI (`gpt-4o-mini`, không công bố chính thức) vẫn còn
trong code — đặt `EC_LLM_PROVIDER=ollama` hoặc `EC_LLM_PROVIDER=openai` để chuyển.

- **Được dùng bởi**: cả 7 agent. Sáu agent nghiệp vụ chạy vòng lặp tool-calling (model tự chọn tool
  dữ liệu thô, tự tính, tự nộp qua final tool), Coordinator gọi 2 lần (triage + synthesis).
- Nhiệt độ 0.1 vì đây là tác vụ kiểm toán/tuân thủ, cần ổn định thay vì sáng tạo.
- Nhánh Ollama local chậm hơn nhiều so với OpenRouter (~10s/lượt gọi thay vì ~1-2s, do chạy trên GPU
  laptop thay vì hạ tầng hosted) — chỉ nên dùng khi không có mạng/API key.
- Dù dùng provider nào, một số case vẫn có thể fail nếu model không gọi đúng final tool sau vài lượt
  (không có fallback deterministic để bù) — xem `cases_failed` trong `logging/metadata.json`.

## 6. Cách chạy

```bash
python scripts/run_agents.py    # bật MCP server (:8765) + 7 agent service (:9100-9106)
python scripts/run_batch.py --parallel 4   # terminal thứ 2: chạy 50 input/EC_*.json
                                            # ghi output/, trace.jsonl, metadata.json
python scripts/run_case.py EC_001   # chạy 1 case qua pipeline thật, in trace + output ra terminal
python scripts/validate_output.py   # kiểm tra trước khi nộp: 50 file, schema, evidence grounding
pytest                               # unit test các MCP tool dữ liệu thô + validator
python src/web/server.py 8000        # dashboard demo chạy pipeline thật (cần run_agents đang chạy)
```

Chi tiết từng bước xem `HUONG_DAN_CHAY.md`.
