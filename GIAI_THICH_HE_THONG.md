# Giải thích hệ thống từ A đến Z

Tài liệu này trả lời 3 câu hỏi: **có bao nhiêu agent**, **mỗi agent làm gì**, và **một input chạy qua hệ thống ra sao**.

---

## PHẦN 1 — CON SỐ TỔNG QUAN

| Thành phần | Số lượng | Port |
|---|---|---|
| **Agent A2A** | **7** | 9100 – 9106 |
| **MCP server** | **1** | 8765 |
| **MCP tool** | **8** | (nằm trong MCP server) |
| **Model LLM** | **1** (`gpt-4o-mini`, đổi được sang local `qwen3.5-4b-ec`) | OpenAI API / Ollama :11434 |
| Lời gọi LLM mỗi case | ~14 | (7 agent × ~2 vòng tool-calling) |

Trong 7 agent: **1 điều phối** (Coordinator) + **4 điều tra** (Customer, Order&Product, Payment, Delivery) + **1 phán quyết** (Policy) + **1 kiểm định** (Verifier). **Cả 7 đều dùng LLM.**

## Hai cơ chế giao tiếp — đừng nhầm lẫn

**A2A = agent gọi agent** (HTTP giữa 2 service, KHÔNG có LLM):
Coordinator gửi POST tới `http://127.0.0.1:9101/a2a` với gói JSON-RPC `message/send`. Agent kia nhận, xử lý, trả gói handoff. Thuần 2 chương trình nói chuyện qua mạng.

**MCP = agent lấy dữ liệu** (LLM quyết định, 3 vòng):
1. Agent đưa cho LLM danh sách tool nó **được phép** dùng + system prompt vai trò
2. LLM trả về `tool_calls` — **tự chọn** gọi tool nào, tham số gì
3. Agent thực thi lời gọi đó lên MCP server `:8765` → nhận dữ liệu thật → đưa lại cho LLM viết nhận định

## Mỗi agent trả về 2 phần tách bạch

| | `facts` | `note` |
|---|---|---|
| Nội dung | JSON có cấu trúc | Văn xuôi tiếng Việt |
| Nguồn | **output nguyên vẹn của MCP tool** | LLM viết |
| Đi vào đâu | **file output được chấm điểm** | chỉ `trace.jsonl` |

Đây là ranh giới quan trọng nhất: LLM **quyết định gọi tool nào**, nhưng số liệu vào file output luôn là output nguyên vẹn của tool. Nếu LLM viết nhầm số trong `note` thì file output vẫn đúng — vì grader hard-gate cả case về 0 điểm chỉ vì lệch một xu.

---

## PHẦN 2 — 8 MCP TOOL LÀ GÌ?

MCP server (`src/mcp_server/server.py`) là **nơi duy nhất trong hệ thống được đọc 9 file CSV**. Nó mở ra 8 "quầy tra cứu". Agent muốn biết gì phải gọi tool, không được tự đọc file.

| # | Tên tool | Input | Trả về gì | CSV nào được đọc |
|---|---|---|---|---|
| 1 | `get_order` | order_id | Trạng thái đơn, 5 mốc thời gian (đặt, duyệt, giao carrier, giao khách, hẹn giao), customer_id | orders |
| 2 | `get_customer_context` | order_id | `customer_unique_id` + danh sách đơn khác của cùng khách | orders + customers |
| 3 | `get_affected_entities` | order_id | `order_ids`, `item_ids` (`<order>:<n>`), `seller_ids`, `payment_ids` (`<order>:<seq>`) | order_items + order_payments |
| 4 | `get_product_context` | order_id | `product_ids` + `category_names` (nguyên văn tiếng Bồ) | order_items + products |
| 5 | `get_delivery_analysis` | order_id | `delivery_variance_hours`, phân tích bàn giao từng seller, danh sách seller trễ | orders + order_items |
| 6 | `get_payment_reconciliation` | order_id | item_total, freight_total, expected_total, payment_total, difference, reconciled, payment_types | order_items + order_payments |
| 7 | `apply_policy` | order_id | **Toàn bộ thân case**: primary/secondary issue, root cause, bên chịu trách nhiệm, số tiền hoàn, evidence_ids, actions, confidence | tất cả (chạy full EC_POLICY_V2) |
| 8 | `validate_case_output` | case JSON | `{valid, violations[]}` — kiểm schema, trần mảng, đối chiếu evidence & entity với CSV | order_items + order_payments + products |

**Ai được gọi tool nào** (đây chính là cơ chế phân quyền):

```
Customer Agent       → tool 2
Order&Product Agent  → tool 3, 4
Payment Agent        → tool 6, 3
Delivery Agent       → tool 5
Policy Agent         → tool 7
Verifier Agent       → tool 8
Coordinator          → (không gọi tool nào, chỉ điều phối)
```

Delivery Agent **không có đường nào** chạm tới dữ liệu thanh toán. Payment Agent **không có đường nào** chạm tới ngày giao hàng. Đó là separation of concerns thật, không phải hình thức.

---

## PHẦN 3 — 7 AGENT, TỪNG CON MỘT

Mỗi agent là **một HTTP service riêng** với 3 endpoint:
- `GET /.well-known/agent-card.json` → danh thiếp A2A (tên, mô tả, skill)
- `POST /a2a` → nhận tin nhắn JSON-RPC `message/send` (kênh giao tiếp chính)
- `GET /health` → kiểm tra sống

### 1. Coordinator Agent — :9100
- **Vai trò**: trưởng phòng điều tra. Là A2A *client* của 6 agent kia.
- **Làm gì**: nhận ticket → phát việc → gom kết quả → ráp JSON cuối → ghi file + ghi trace.
- **MCP tool**: không gọi tool nào.
- **LLM**: không dùng (thuần điều phối).
- **Đặc biệt**: quản lý **vòng retry** — nếu Verifier báo lỗi thì gửi lại Policy làm lại (tối đa 1 lần).

### 2. Customer Agent — :9101
- **Câu hỏi được giao**: *"Khách này là ai? Có mua gì trước đây không?"*
- **MCP tool**: `get_customer_context`
- **Sản phẩm**: `customer_context` = { customer_unique_id, related_order_ids }
- **LLM làm gì**: nhận định khách quen hay khách mới, có đơn nào đáng đối chiếu.
- **Ảnh hưởng output**: quyết định secondary issue `repeat_customer`.

### 3. Order & Product Agent — :9102
- **Câu hỏi**: *"Đơn gồm những gì? Của seller nào? Hàng ngành nào?"*
- **MCP tool**: `get_affected_entities` + `get_product_context`
- **Sản phẩm**: `affected_entities` (item/seller/payment IDs) + `product_context` (product IDs, categories)
- **LLM làm gì**: nhận định độ phức tạp đơn (nhiều item / nhiều seller / nhiều ngành hàng).
- **Ảnh hưởng output**: quyết định `multi_item_order`, `multi_seller_order`, `multiple_categories`.

### 4. Payment Agent — :9103
- **Câu hỏi**: *"Khách trả bao nhiêu? Có khớp giá trị đơn không?"*
- **MCP tool**: `get_payment_reconciliation` + `get_affected_entities`
- **Công thức** (từ đề): `expected = Σprice + Σfreight`; `difference = Σpayment − expected`; `reconciled = |difference| ≤ 0.10 BRL`
- **LLM làm gì**: nhận định thanh toán khớp/lệch, split payment có hợp lệ không.
- **Ảnh hưởng output**: quyết định `split_payment`, `valid_split_payment`.

### 5. Delivery Agent — :9104
- **Câu hỏi**: *"Giao trễ không? Trễ do ai?"*
- **MCP tool**: `get_delivery_analysis`
- **Công thức** (từ đề): `delivery_variance = ngày giao thực tế − ngày hẹn` (dương = trễ); với mỗi seller: `handoff_variance = ngày carrier nhận hàng − shipping_limit_date` (dương = seller trễ)
- **LLM làm gì**: nhận định trễ hay không, lỗi thuộc seller hay đơn vị vận chuyển.
- **Ảnh hưởng output**: quyết định `late_delivery_seller` vs `late_delivery_logistics`.

### 6. Policy Agent — :9105
- **Câu hỏi**: *"Với toàn bộ chứng cứ, kết luận theo EC_POLICY_V2 là gì?"*
- **MCP tool**: `apply_policy`
- **Áp bảng luật 6 nhánh theo đúng thứ tự ưu tiên**:

| Thứ tự | Điều kiện | Kết luận | Hoàn tiền |
|---|---|---|---|
| 1 | status = canceled & payment > 0 | `canceled_order_paid` | toàn bộ payment |
| 2 | status = unavailable & payment > 0 | `unavailable_order_paid` | toàn bộ payment |
| 3 | giao trễ & có seller bàn giao muộn | `late_delivery_seller` | phí ship |
| 4 | giao trễ & không seller nào muộn | `late_delivery_logistics` | phí ship |
| 5 | ≥2 payment row & khớp tiền | `valid_split_payment` | 0 |
| 6 | giao đúng hạn & khớp tiền | `unsupported_late_claim` | 0 |

- **LLM làm gì**: viết lập luận phán quyết bằng tiếng Việt, trích dẫn evidence ID.

### 7. Verifier Agent — :9106
- **Câu hỏi**: *"Case này đủ chuẩn nộp chưa?"*
- **MCP tool**: `validate_case_output`
- **Thiết kế 2 lớp bất đối xứng**:
  - **Lớp 1 — code deterministic**: kiểm 11 trường bắt buộc, trần mảng (5 item/3 seller/20 evidence...), `confidence ∈ [0,1]`, và **đối chiếu từng evidence ID + entity với CSV gốc**. → **Chỉ lớp này quyết định PASS/FAIL.**
  - **Lớp 2 — LLM audit độc lập**: model đọc lại case, kiểm tính nhất quán nghiệp vụ (số tiền hoàn có đúng loại vấn đề không, case_status có khớp không). → **Thêm** phát hiện, không **xóa** được phát hiện của lớp 1.
- **Vì sao bất đối xứng**: nếu LLM được quyền lật FAIL→PASS thì một lần ảo giác là lọt case hỏng = 0 điểm. Code cho *precision*, model cho *recall*.

---

## PHẦN 4 — PIPELINE: MỘT INPUT CHẠY RA SAO?

Lấy ví dụ thật: **EC_002.json**

### Input nhận vào
```json
{
  "case_id": "EC_002",
  "customer_request": {
    "claimed_order_id": "eb09635680fadffb33358e40b05c9029"
  }
}
```
Chỉ có vậy — một mã đơn. Mọi thứ khác phải tự điều tra.

### BƯỚC 1 — Coordinator nhận và phát việc (t = 0.00s)
Coordinator đọc `claimed_order_id`, tạo 4 gói handoff và gửi **đồng thời** (`asyncio.gather`) qua HTTP tới 4 agent. Ghi trace: `A2A_DISPATCH`.

### BƯỚC 2 — 4 agent điều tra chạy SONG SONG (t ≈ 0.0 → 8s)

**Customer Agent** gọi `get_customer_context`:
→ `customer_unique_id = ef3b6ab8...`, có 1 đơn khác → `related_order_ids = [d4b3b003...]`
→ LLM: *"Khách quen đã có lịch sử mua hàng..."*

**Order&Product Agent** gọi `get_affected_entities` + `get_product_context`:
→ 1 item (`eb096356...:1`), seller `c3867b46...`, product `f114a4c3...`, category `esporte_lazer`
→ LLM: *"Đơn cấu trúc đơn giản, một người bán, ngành thể thao..."*

**Payment Agent** gọi `get_payment_reconciliation`:
→ 2 payment row: credit_card 112.27 + voucher 100.00 = **212.27**
→ expected = 194.00 (hàng) + 18.27 (ship) = **212.27** → difference = 0.00 → **reconciled = true**
→ LLM: *"Đối soát chính xác trong sai số cho phép..."*

**Delivery Agent** gọi `get_delivery_analysis`:
→ hẹn giao 2018-03-28 00:00, giao thật 2018-03-31 15:23 → **trễ 87.39 giờ**
→ seller phải bàn giao trước 2018-03-15 20:31, thực tế carrier nhận 21:33 → **seller trễ 1.04 giờ** → `late_handoff = true`
→ LLM: *"Đơn trễ 87,39 giờ so với dự kiến..."*

Mỗi agent trả về một **gói handoff** gồm: ticket_id, câu hỏi, facts, evidence_ids, missing, next_action, note(LLM).

### BƯỚC 3 — Policy Agent phán quyết (t ≈ 8 → 14s)
Coordinator gom 4 báo cáo, gửi cho Policy. Policy gọi `apply_policy`, tra bảng luật theo thứ tự:
- Nhánh 1 (canceled)? → không, status = delivered
- Nhánh 2 (unavailable)? → không
- **Nhánh 3: giao trễ (87.39 > 0) VÀ có seller bàn giao muộn (1.04 > 0)?** → **KHỚP**

→ `primary_issue = late_delivery_seller`
→ `root_cause = SELLER_HANDOFF_AFTER_LIMIT`
→ `responsible_parties = [{seller, c3867b46...}]`
→ `refund = 18.27` (phí ship)
→ `case_status = action_required`
→ `secondary_issues = [split_payment, repeat_customer]`
→ `actions = [refund_freight, review_seller_handoff, verify_payment_allocation]`
→ `evidence_ids = [order:eb09..., item:eb09...:1, payment:eb09...:1, payment:eb09...:2, seller:c386..., policy:SELLER_HANDOFF_AFTER_LIMIT]`

→ LLM viết lập luận: *"Xác định vấn đề chính là giao hàng muộn do người bán chuyển hàng sau hạn mức..."*

### BƯỚC 4 — Verifier kiểm định (t ≈ 14 → 20s)
Gọi `validate_case_output`:
- 11 trường bắt buộc → đủ ✓
- Trần mảng (1 item ≤ 5, 1 seller ≤ 3, 6 evidence ≤ 20) → đạt ✓
- `item:eb09...:1` có tồn tại trong CSV? → có ✓
- `payment:eb09...:1`, `:2` có tồn tại? → có ✓
- `seller:c3867b46...` có bán trong đơn này? → có ✓
- `esporte_lazer` có đúng là category gốc trong CSV? → có ✓
→ **valid = true, violations = []**

LLM audit: *"[schema/grounding: PASS] Nhất quán: hoàn 18.27 BRL đúng mức phí ship..."*

### BƯỚC 5 — Coordinator ghi kết quả
- Ghi `output/EC_002.json` (thêm `case_id` vào đầu)
- Ghi 6 dòng vào `logging/trace.jsonl` (mỗi agent 1 dòng, kèm timestamp micro-giây)
- Chuyển sang ticket kế tiếp

### Nếu Verifier báo lỗi thì sao?
Coordinator gửi **lại** cho Policy làm lại (tối đa 1 lần), rồi cho Verifier kiểm lại. Nếu vẫn lỗi → **vẫn ghi file** (bài nộp bắt buộc đủ 50) nhưng ghi rõ vi phạm vào trace để truy vết, không âm thầm bỏ qua.

---

## PHẦN 5 — VÌ SAO MỖI CASE PHẢI CHẠY ĐỦ AGENT?

Vì **schema output của đề bắt buộc** đủ 10 khối, mỗi khối chỉ một agent tạo được:

| Khối trong output | Agent tạo ra |
|---|---|
| `customer_context` | Customer |
| `affected_entities`, `product_context` | Order & Product |
| `payment_reconciliation` | Payment |
| `delivery_analysis` | Delivery |
| `case_assessment`, `root_cause_analysis`, `evidence_ids`, `financial_resolution`, `resolution_actions` | Policy |

Kể cả đơn bị hủy (không cần phân tích giao vận) thì output **vẫn bắt buộc** có khối `delivery_analysis` (điền `null` / mảng rỗng). Thiếu khối = hard gate 0 điểm. Nên không bỏ bớt agent nào được.

---

## PHẦN 6 — RANH GIỚI: LLM LÀM GÌ, CODE LÀM GÌ

| Việc | Ai làm | Vì sao |
|---|---|---|
| Đọc CSV, join bảng | MCP tool (code) | Dữ liệu gốc phải chính xác tuyệt đối |
| Cộng tiền, trừ ngày ra giờ | MCP tool (code) | Model 4B tính sai → lệch 1 xu = hard gate 0 điểm |
| Ghép chuỗi evidence ID | MCP tool (code) | Sai format = false positive = 0 điểm |
| Tra bảng luật 6 nhánh | MCP tool (code) | Luật đặc tả chính xác, không có chỗ phán đoán |
| Kiểm schema, đối chiếu evidence | MCP tool (code) | Cổng gác không được ảo giác |
| **Nhận định chuyên môn từng lĩnh vực** | **LLM** | Việc ngôn ngữ, cần suy luận, không có "một đáp án đúng" |
| **Viết lập luận phán quyết** | **LLM** | Giải thích cho người đọc hiểu vì sao |
| **Soát tính nhất quán nghiệp vụ** | **LLM** | Bắt được vấn đề ngữ nghĩa mà rule không mã hóa nổi |

**Nguyên tắc**: model suy luận, máy tính tính toán. Đây là mô hình tool-use tiêu chuẩn — LLM không tự cộng trừ, nó gọi công cụ, giống người dùng máy tính bỏ túi.
