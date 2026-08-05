# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung     |
| --------------- | ------------ |
| Họ và tên       | Nguyễn Hùng Mạnh  |
| MSSV            | 2A202601256       |
| Khóa/Lớp        | K4        |
| Vai trò chính   | FullStack (làm solo, không có thành viên khác trong nhóm)   |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

Làm solo nên sở hữu toàn bộ hệ thống — từ MCP server, 7 agent A2A, tới batch runner và tài liệu.

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao   | Trạng thái                            |
| ------------------- | ------------------- | --------------- | ------------------- | --------------------------------------- |
| MCP data server (raw-only tools) | `src/mcp_server/server.py`, `src/mcp_server/schema.py` | `order_id`/`product_ids`/`customer_unique_id` | 7 tool trả dữ liệu thô từ CSV + `validate_case_output` | Hoàn thành |
| 4 agent nghiệp vụ (Customer/Order&Product/Payment/Delivery) | `src/agents/customer_agent.py`, `order_product_agent.py`, `payment_agent.py`, `delivery_agent.py` | `order_id` qua A2A handoff | `HandoffPayload` chứa sub-object đã tự tính (self-computed) | Hoàn thành |
| Policy Agent (ra phán quyết EC_POLICY_V2) | `src/agents/policy_agent.py` | Bằng chứng từ 4 agent trên | `case_assessment`, `root_cause_analysis`, `financial_resolution`, `resolution_actions` | Hoàn thành |
| Verifier Agent (2 lớp: schema/grounding + audit logic) | `src/agents/verifier_agent.py` | `case` hoàn chỉnh | `{valid, violations, audit_consistent, audit_issues}` | Hoàn thành |
| Coordinator (điều phối + retry toàn bộ pipeline) | `src/agents/coordinator.py` | Ticket `input/EC_*.json` | `case` cuối + `trace` | Hoàn thành |
| Provider layer 3 chiều (Ollama/OpenRouter/OpenAI) + tool-loop chống hallucination | `src/agents/base.py`, `src/config.py` | Config qua `EC_LLM_PROVIDER`/`.env` | `llm_chat()` thống nhất cho mọi agent | Hoàn thành |
| Batch runner đa lane song song | `scripts/run_batch.py`, `scripts/run_case.py`, `scripts/run_agents.py` | 50 ticket `input/` | `output/EC_*.json`, `logging/trace.jsonl`, `logging/metadata.json` | Hoàn thành (50/50) |
| Tài liệu kiến trúc | `architecture.md`, `HUONG_DAN_CHAY.md` | — | Mô tả kiến trúc khớp code thật | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                 | Thành viên/module được hỗ trợ | Kết quả                 |
| ------------------------- | ------------------------------ | ------------------------ |
| Audit toàn bộ hệ thống trước đó (bản dùng OpenAI + `policy_engine.py` tính sẵn) | Tự phát hiện hardcode nghiệp vụ, `SYNTHESIS_PROMPT` chết, script demo giả lập trace | Là cơ sở để quyết định viết lại toàn bộ pipeline không hardcode |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao          | Cách xác minh   |
| ---------------------- | ----------------------------- | --------------------------- | ----------------- |
| Xóa toàn bộ tính toán nghiệp vụ bằng code, chuyển sang MCP tool raw-only | `src/mcp_server/server.py` (xóa `policy_engine.py`) | 7 tool chỉ trả dữ liệu thô | `pytest tests/test_mcp_tools.py` |
| Ép mỗi agent tự tính + tự nộp qua "final tool", chặn hallucination | `agent_tool_loop()` trong `src/agents/base.py` | Từ chối mọi final-tool call đi kèm tool khác trong cùng lượt | Test round-by-round thủ công (xem mục 6) |
| Verifier 2 lớp: deterministic (schema/grounding) + LLM audit có cấu trúc | `src/agents/verifier_agent.py` | Audit bắt lỗi sai dấu `delivery_variance_hours`, kích hoạt retry toàn bộ | Chạy thật EC_001, xem `logging/trace_*.jsonl` |
| Batch 50 case qua 3 provider (OpenRouter/Ollama/OpenAI) chạy song song nhiều lane | `scripts/run_batch.py --cases/--start/--end/--trace-out/--metadata-out` | `output/EC_001.json` … `EC_050.json` | `python scripts/validate_output.py` |

Một output cụ thể: `output/EC_001.json` — case này từng bị Policy Agent chọn sai nhánh (`late_delivery_logistics`) do Delivery Agent tính sai dấu variance; Verifier audit bắt lỗi, hệ thống tự retry toàn bộ 4 agent + Policy, và case cuối cùng đúng (`unsupported_late_claim`, khớp với dữ liệu gốc: giao ngày 19/06 sớm hơn hẹn 26/06).

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Bản gốc của hệ thống (commit trước khi bắt đầu phiên làm việc này) dùng LLM thật để gọi tool và viết narration, nhưng **mọi số liệu và quyết định cuối cùng** (tổng tiền, chênh lệch giờ giao hàng, định dạng evidence ID, chọn `primary_issue`, tính `confidence`) đều do một module Python thuần (`policy_engine.py`) tính sẵn — LLM chỉ chọn nhãn rồi gọi 1 tool để lấy kết quả dựng sẵn. Ban tổ chức yêu cầu mọi giá trị trong output phải do chính agent LLM tự suy luận ra, không có hàm nào tính hộ.

### Cách triển khai

- **MCP server chỉ trả dữ liệu thô**: mỗi tool là một phép lọc theo khóa từ CSV gốc (`get_order_items`, `get_order_payments`, `get_customer`, `get_related_orders`, `get_products`) — không sum, không trừ ngày giờ, không dựng chuỗi evidence ID.
- **"Final tool" pattern**: mỗi agent nghiệp vụ được cấp các tool dữ liệu thô + đúng 1 tool nội bộ (`report_customer`, `report_payment`...) là cách duy nhất để nộp kết quả. Model phải tự cộng tiền, tự trừ giờ, tự dựng chuỗi ID trước khi gọi tool này.
- **Chốt chặn chống hallucination**: phát hiện model (đặc biệt Llama-3.1-8B-Instruct, và đôi khi cả model khác) có xu hướng gọi tool "nộp kết quả" cùng lúc với tool tra dữ liệu, tức là **đoán số liệu trước khi thấy kết quả thật**. `agent_tool_loop()` từ chối tuyệt đối mọi final-tool call không đứng một mình trong lượt gọi, kể cả khi tool đi kèm là tool đã gọi trước đó (giảm rủi ro bị "quen mặt" mà bỏ qua).
- **Structured audit gate**: Verifier có lớp LLM audit bắt buộc gọi `report_audit(consistent, issues)` — không phải văn bản tự do — để tự so sánh dấu `delivery_variance_hours` với `delivered_at`/`estimated_delivery_at` thật, và đối chiếu `primary_issue` với chính bằng chứng trong case. Nếu audit thấy sai, `valid = schema_valid AND audit_consistent = False`, Coordinator retry **toàn bộ 4 agent + Policy** (không chỉ Policy), vì lỗi có thể bắt nguồn từ bất kỳ agent nào.
- **Provider layer 3 chiều**: `EC_LLM_PROVIDER=ollama|openrouter|openai`, cho phép chạy nhiều lane song song trên các port khác nhau (`EC_PORT_OFFSET`) để tận dụng nhiều backend độc lập cùng lúc khi cần tăng thông lượng.

### Input, output và contract

| Thành phần              | Mô tả                                  |
| ------------------------ | ---------------------------------------- |
| Input                   | `input/EC_001.json` … `EC_050.json` (ticket khiếu nại, README §3) |
| Output                  | `output/EC_xxx.json` đúng schema README §6, `logging/trace.jsonl`, `logging/metadata.json` |
| Module phụ thuộc        | `src/data/loader.py` (đọc 9 CSV Olist), `mcp` SDK, `openai` SDK (dùng chung cho OpenAI/OpenRouter) |
| Module sử dụng output   | `scripts/validate_output.py` (kiểm trước khi nộp), `src/web/server.py` (dashboard demo) |
| Điều kiện lỗi cần xử lý | Model không gọi được final tool sau N vòng → case fail thẳng (ghi vào `cases_failed`), không bao giờ tự chế số liệu thay |

### Cách xác minh

```bash
python scripts/run_agents.py            # bật MCP server + 7 agent service
python scripts/run_batch.py --parallel 6 # chạy 50 case, ghi output/ + trace.jsonl + metadata.json
python scripts/validate_output.py        # kiểm schema, evidence grounding trước khi nộp
pytest                                   # 11 test cho MCP tool + validator
```

- **Kết quả mong đợi:** 50/50 file `output/EC_*.json` hợp lệ theo schema README §6.
- **Kết quả thực tế:** Đạt 50/50 sau nhiều vòng debug thật (xem mục 6) — không có case nào bị bỏ qua hay điền số liệu giả khi fail.
- **Artifact/log:** `output/EC_001.json` … `EC_050.json`, `logging/trace.jsonl`, `logging/metadata.json`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Sau khi ép LLM tự tính toán 100%, phát hiện model (Llama-3.1-8B-Instruct qua OpenRouter) gọi tool "nộp kết quả cuối" (`report_order_product`) cùng lúc với tool tra dữ liệu (`get_products`), dùng ID bịa (`"product_id1"`, `"product_id2"`...) trước khi từng thấy kết quả thật — vì đã lọt qua bước kiểm tra ban đầu (chỉ check tên tool có xuất hiện, không check có bị gộp lượt hay không).
- **Các phương án đã cân nhắc:**
  1. Chấp nhận final-tool call miễn là tên tool đúng, bất kể có gọi kèm tool nào khác không (thiết kế ban đầu).
  2. Chỉ chấp nhận nếu tool dữ liệu đi kèm đã từng được gọi thành công trước đó ("seen tools" — nới lỏng).
  3. Chỉ chấp nhận final-tool call khi nó **đứng một mình hoàn toàn** trong lượt gọi, không kèm bất kỳ tool nào khác.
- **Phương án đã chọn:** Phương án 3.
- **Lý do:** Phương án 2 test thực tế vẫn lọt dữ liệu bịa (model gọi lại `get_products` với ID cũ trong cùng lượt với final tool, nhưng kết quả thật của lượt đó chưa kịp về) — tức "đã từng gọi tool này" không đảm bảo model đã đọc kết quả *lần này*. Phương án 3 loại bỏ hoàn toàn khả năng đoán số liệu, đánh đổi bằng việc một số model (đặc biệt Llama-3.1-8B-Instruct) có thói quen gộp lượt rất cố chấp, dẫn đến agent bị kẹt lặp không bao giờ thành công.
- **Bằng chứng quyết định phù hợp:** Với phương án 3 + đổi sang model kỷ luật hơn (Qwen3-8B/GPT-4o-mini), EC_001 chạy sạch, mọi ID/số liệu đều khớp thật với `data/`; audit trước đó (đã lưu trong lịch sử debug) cho thấy phương án 1 tạo ra output với `customer_unique_id: "customer_unique_id"` (literal tên field) và ngày tháng không tồn tại trong dữ liệu gốc.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `RuntimeError: policy agent's report_case call is missing/invalid primary_issue: None` — xảy ra ở 15/30 case (50%) khi chạy batch qua GPT-4o-mini.
- **Lệnh hoặc bước tái hiện:** `EC_PORT_OFFSET=200 EC_LLM_PROVIDER=openai python scripts/run_batch.py --start 0 --end 40 --parallel 8`.
- **Nguyên nhân gốc:** Hai lớp nguyên nhân chồng lên nhau. (1) JSON Schema `"required"` trong function-calling thông thường của OpenAI chỉ là gợi ý cho model, không được API enforce — model đôi khi bỏ sót field bắt buộc. (2) `max_tokens=1024` (đặt trước đó để tránh OpenRouter báo "insufficient credits") quá thấp cho `report_case` — tool này có thể chứa tới 20 `evidence_ids` cộng nhiều mảng khác, khiến JSON bị cắt cụt giữa chừng, `json.loads()` thất bại và rơi về `args = {}` rỗng.
- **Cách xử lý:** (1) Bật **strict mode** của OpenAI function-calling (`"strict": true` bên trong object `function`, cộng `additionalProperties: false` + mọi field đều trong `required` ở mọi cấp schema — viết hàm `_strict_schema()` tự động chuẩn hóa) để API tự enforce schema thay vì chỉ tin lời model. (2) Tăng `max_tokens` từ 1024 lên 4096. Ngoài ra sửa `policy_agent.py` dùng `args.get()` + validate rõ ràng thay vì index trực tiếp `args["primary_issue"]` (từng gây `KeyError` thô, crash không rõ nguyên nhân).
- **Cách xác minh sau khi sửa:** Chạy lại đúng các case từng fail bằng `--cases EC_xxx,EC_yyy,...`; tỷ lệ lỗi `primary_issue` giảm từ 50% xuống gần như 0 (chỉ còn round-exhaustion tự nhiên của một số case biên, ví dụ khách hàng chỉ có 1 đơn duy nhất khiến model không quen xử lý danh sách rỗng — xử lý bằng cách nêu rõ trường hợp này trong system prompt của Customer Agent).
- **Điều học được:** Không được tin "required" trong JSON Schema là ràng buộc cứng trừ khi bật đúng cơ chế strict của provider; và giới hạn `max_tokens` phải tính theo kích thước thực tế của payload lớn nhất (không phải payload trung bình), nếu không sẽ gây lỗi "im lặng" (JSON cụt) rất khó phân biệt với lỗi model thật sự không tuân lệnh.

## 7. Hiểu biết về luồng end-to-end

*(5 câu hỏi mẫu trong template gốc — về Crossref/vector index/retrieval — thuộc một lab RAG khác, không khớp bài K4 Day 9 Multi-Agent A2A này. Thay bằng 5 câu tương đương cho đúng bài.)*

1. **Ticket đi từ `input/` tới `output/` như thế nào?** Coordinator đọc `input/EC_xxx.json`, gửi `order_id` song song cho Customer/Order&Product/Payment/Delivery Agent qua A2A (`message/send`), mỗi agent tự gọi MCP tool dữ liệu thô rồi tự tính, tự nộp qua final tool. Coordinator ghép các sub-object đã tự tính đó vào ngữ cảnh cho Policy Agent, Policy Agent tự ra phán quyết + tự dựng phần còn lại của case, Coordinator ghép case hoàn chỉnh gửi cho Verifier.
2. **`evidence_ids` và grounding dùng để đo gì?** Verifier's `validate_case_output` đối chiếu từng `evidence_ids`/`product_id`/`seller_id`/`category_name` model report với dữ liệu thật trong CSV — evidence không tồn tại trong nguồn bị coi là vi phạm và fail case, để đảm bảo model không bịa dữ liệu.
3. **Còn kiểm tra gì khác ngoài schema/grounding?** LLM audit (Layer 2 của Verifier) kiểm tính nhất quán nghiệp vụ mà rule code không diễn đạt được: dấu `delivery_variance_hours` có khớp `delivered_at` vs `estimated_delivery_at` thật không, `primary_issue` có khớp bằng chứng không, refund có đúng loại vấn đề không.
4. **Vì sao retry phải chạy lại toàn bộ 4 agent + Policy, không chỉ Policy?** Vì lỗi Verifier bắt được (ví dụ sai dấu delivery_variance_hours) có thể bắt nguồn từ bất kỳ agent nghiệp vụ nào, không chỉ từ quyết định của Policy Agent; retry chỉ Policy sẽ tái sử dụng số liệu sai của agent gốc và lặp lại đúng lỗi cũ.
5. **Case coi là thành công dựa trên artifact/metric nào?** `output/EC_xxx.json` được ghi ra khi và chỉ khi Verifier trả `valid=true` (hoặc đã hết lượt retry, khi đó vẫn ghi nhưng vi phạm được log rõ trong `trace.jsonl`, không giấu); toàn batch được coi xong khi `logging/metadata.json` báo `cases_processed=50` và `cases_failed=[]`.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Hùng Mạnh
**Ngày xác nhận:** 2026-08-05
