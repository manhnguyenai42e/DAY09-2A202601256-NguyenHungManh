# Báo cáo Chi tiết Kiến trúc Hệ thống Multi-Agent & MCP Data Tools

**Dự án**: K4 Day 09 - Multi-Agent E-commerce Dispute Resolution (Olist Dataset)  
**Tác giả**: Nguyễn Hùng Mạnh (MSSV: 2A202601256) — Khóa K4  
**Ngày hoàn thành**: 05/08/2026  

---

## 1. Tổng quan Kiến trúc Hệ thống (System Architecture Overview)

Hệ thống được thiết kế theo mô hình **Domain-Driven Multi-Agent Architecture** kết hợp với công nghệ **A2A (Agent-to-Agent Communication Protocol)** và **MCP (Model Context Protocol Data Server)**. 

Bài toán yêu cầu điều tra 50 hồ sơ khiếu nại thương mại điện tử (`EC_001.json` -> `EC_050.json`) trên bộ dữ liệu Olist. Mỗi hồ sơ khiếu nại được xử lý thông qua sự phối hợp bất đồng bộ giữa **7 Agent Services độc lập** và **6 MCP Tools chuẩn hóa**.

```text
[Input Ticket: EC_xxx.json]
       │
       ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 1. Coordinator Agent (Port 9100 - Orchestration)         │
 └──────┬────────────────────┬────────────────────┬─────────┘
        │ (A2A Call)         │ (A2A Call)         │ (A2A Call)
        ▼                    ▼                    ▼
 ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
 │ Customer     │    │ Order &      │    │ Payment &    │
 │ Agent (:9101)│    │ Product (:9102)   │ Delivery(:9104)│
 └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
        │                    │                    │
        ▼                    ▼                    ▼
 ┌──────────────────────────────────────────────────────────┐
 │ MCP Data Server (Port 8765 - Streamable HTTP Transport)   │
 │   - get_customer_history                                 │
 │   - get_order_and_product_details                        │
 │   - get_payment_reconciliation                           │
 │   - get_delivery_analysis                                │
 │   - evaluate_ec_policy (EC_POLICY_V2 Engine)             │
 │   - validate_and_truncate_output                         │
 └───────────────────────────┬──────────────────────────────┘
                             ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 2. Policy Agent (Port 9105 - Decision & Taxonomy)        │
 └───────────────────────────┬──────────────────────────────┘
                             ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 3. Verifier Agent (Port 9106 - Guardrail & Schema Audit) │
 └───────────────────────────┬──────────────────────────────┘
                             ▼
             [Output JSON: output/EC_xxx.json]
```

---

## 2. Chi tiết 7 Agent Services (A2A Architecture)

Tất cả 7 Agents được xây dựng thành các **dịch vụ HTTP bất đồng bộ độc lập**, mỗi Agent lắng nghe trên một cổng (Port) riêng biệt và sở hữu một **Agent Card** riêng để tự giới thiệu năng lực.

| STT | Tên Agent | Port A2A | Vai trò & Trách nhiệm Chuyên biệt | Input / Output Contract |
|---|---|---|---|---|
| 1 | **Coordinator Agent** | `:9100` | **Điều phối tổng**: Tiếp nhận ticket khiếu nại từ file `input/EC_xxx.json`, quản lý tiến trình dispatch A2A đến các Domain Agent, tập hợp ngữ cảnh và bàn giao cho Policy/Verifier Agent. | **Input**: `ticket_id`, `claimed_order_id`, `customer_request`<br>**Output**: JSON Output hoàn chỉnh của case. |
| 2 | **Customer Agent** | `:9101` | **Chuyên gia Ngữ cảnh Khách hàng**: Tra cứu mã định danh duy nhất `customer_unique_id` và truy vấn toàn bộ danh sách đơn hàng cũ trong lịch sử của cùng khách hàng này. | **Input**: `customer_id`, `claimed_order_id`<br>**Output**: `customer_context` (`customer_unique_id`, `related_order_ids`). |
| 3 | **Order & Product Agent** | `:9102` | **Chuyên gia Sản phẩm & Đơn hàng**: Trích xuất chi tiết các dòng sản phẩm (`item_ids`), người bán (`seller_ids`), mã sản phẩm (`product_ids`) và tên danh mục chuẩn Tiếng Anh (`category_names`). | **Input**: `claimed_order_id`<br>**Output**: `affected_entities` (item/seller), `product_context`. |
| 4 | **Payment Agent** | `:9103` | **Chuyên gia Đối soát Tài chính**: Tính toán tổng tiền sản phẩm (`item_total_brl`), tổng phí ship (`freight_total_brl`), tổng tiền khách thực trả (`payment_total_brl`), số tiền chênh lệch (`difference_brl`) và trạng thái `reconciled` (`abs(diff) <= 0.10 BRL`). | **Input**: `claimed_order_id`<br>**Output**: `payment_reconciliation`, `affected_entities.payment_ids`. |
| 5 | **Delivery Agent** | `:9104` | **Chuyên gia Phân tích Giao nhận**: So sánh mốc thời gian giao hàng thực tế vs dự kiến để tính `delivery_variance_hours`. So sánh thời điểm ĐVVC nhận hàng vs `shipping_limit_date` để phát hiện Seller bàn giao muộn (`late_handoff`). | **Input**: `claimed_order_id`<br>**Output**: `delivery_analysis` (`delivered_at`, `estimated_at`, `variance_hours`, `late_sellers`). |
| 6 | **Policy Agent** | `:9105` | **Động cơ Quyết định Chính sách**: Áp dụng quy tắc ưu tiên `EC_POLICY_V2` để phân loại `primary_issue` (1 trong 6 loại), gán `secondary_issues`, chỉ định `responsible_parties`, tính `recommended_refund_brl`, đề xuất `resolution_actions` và dựng `evidence_ids` chuẩn. | **Input**: Dữ liệu ngữ cảnh tổng hợp từ các Domain Agent<br>**Output**: `case_assessment`, `root_cause_analysis`, `financial_resolution`, `resolution_actions`, `evidence_ids`. |
| 7 | **Verifier Agent** | `:9106` | **Kiểm định & Bảo vệ Schema**: Đóng vai trò Guardrail kiểm tra lại file JSON trước khi xuất. Ép số thực về 2 chữ số thập phân (`round2`), cắt mảng theo trần giới hạn trong `LIMITS`, đảm bảo không vi phạm bất kỳ quy định chấm điểm nào. | **Input**: Draft case object<br>**Output**: Verified output JSON 100% khớp Schema. |

---

## 3. Chi tiết Máy chủ MCP Data Server & 6 MCP Tools

Máy chủ **MCP Server** (`src/mcp_server/server.py`) chạy tại `http://127.0.0.1:8765/mcp`, đóng vai trò là cổng truy xuất dữ liệu từ 9 file CSV của Olist và thực thi thuật toán phân loại deterministic.

MCP Server cung cấp **6 MCP Tools chuẩn hóa**:

### 🛠️ Tool 1: `get_customer_history`
* **Mô tả**: Đọc `customers.csv` và `orders.csv` để xác định mã khách hàng duy nhất và truy vấn lịch sử các đơn hàng trước đó.
* **Tham số (`params`)**: `customer_id` *(string)*, `order_id` *(string)*.
* **Giá trị trả về**:
  ```json
  {
    "customer_unique_id": "bbf65e7823171a84e70a495dd6c34ceb",
    "related_order_ids": ["65bbd0719855fe808bb19f62dfa9f42c"]
  }
  ```
* **Agent sử dụng**: `Customer Agent` (`:9101`).

---

### 🛠️ Tool 2: `get_order_and_product_details`
* **Mô tả**: Join `order_items.csv`, `products.csv` và `product_category_name_translation.csv` để trích xuất thông tin chi tiết mặt hàng và danh mục Tiếng Anh.
* **Tham số (`params`)**: `order_id` *(string)*.
* **Giá trị trả về**:
  ```json
  {
    "affected_entities": {
      "item_ids": ["9b75cdaf...:1", "9b75cdaf...:2"],
      "seller_ids": ["c70c1b0d8ca86052f45a432a38b73958"]
    },
    "product_context": {
      "product_ids": ["0a4f9f421af66d2ea061fbb8883419f7"],
      "category_names": ["health_beauty"]
    }
  }
  ```
* **Agent sử dụng**: `Order & Product Agent` (`:9102`).

---

### 🛠️ Tool 3: `get_payment_reconciliation`
* **Mô tả**: Đọc `order_payments.csv`, tính tổng tiền sản phẩm, tổng phí ship, tổng tiền thực trả, chênh lệch `difference_brl` và trạng thái đối soát `reconciled`.
* **Tham số (`params`)**: `order_id` *(string)*, `tolerance_brl` *(float, default 0.10)*.
* **Giá trị trả về**:
  ```json
  {
    "currency": "BRL",
    "item_total_brl": 220.64,
    "freight_total_brl": 16.70,
    "expected_total_brl": 237.34,
    "payment_total_brl": 237.34,
    "difference_brl": 0.00,
    "reconciled": true,
    "payment_types": ["credit_card"]
  }
  ```
* **Agent sử dụng**: `Payment Agent` (`:9103`).

---

### 🛠️ Tool 4: `get_delivery_analysis`
* **Mô tả**: Trích xuất các mốc thời gian từ `orders.csv` và `order_items.csv`, tính toán số giờ trễ hạn giao hàng (`delivery_variance_hours`) và số giờ trễ bàn giao của từng seller.
* **Tham số (`params`)**: `order_id` *(string)*.
* **Giá trị trả về**:
  ```json
  {
    "delivered_at": "2018-06-19 01:28:42",
    "estimated_delivery_at": "2018-06-26 00:00:00",
    "carrier_handoff_at": "2018-06-15 14:15:00",
    "delivery_variance_hours": -166.52,
    "seller_handoff_analysis": [
      {
        "seller_id": "c70c1b0d8ca86052f45a432a38b73958",
        "shipping_limit_at": "2018-06-18 07:57:36",
        "handoff_variance_hours": -65.71,
        "late_handoff": false
      }
    ],
    "late_handoff_seller_ids": []
  }
  ```
* **Agent sử dụng**: `Delivery Agent` (`:9104`).

---

### 🛠️ Tool 5: `evaluate_ec_policy`
* **Mô tả**: Áp dụng Động cơ Quy tắc Ưu tiên `EC_POLICY_V2` trong [policy_engine.py](file:///d:/Workspace/DAY9-2A202601256-NguyenHungManh/src/mcp_server/policy_engine.py) để phân loại lỗi, tính khoản tiền hoàn, chỉ định bên chịu trách nhiệm và tạo `evidence_ids`.
* **Tham số (`params`)**: `order_id` *(string)*, `policy_version` *(string)*.
* **Giá trị trả về**:
  ```json
  {
    "primary_issue": "unsupported_late_claim",
    "secondary_issues": ["multi_item_order", "repeat_customer"],
    "case_status": "no_action",
    "root_cause_analysis": {
      "ranked_causes": [{"cause_code": "DELIVERY_WITHIN_ESTIMATE", "rank": 1}],
      "responsible_parties": []
    },
    "recommended_refund_brl": 0.00,
    "resolution_actions": ["reject_late_refund"],
    "evidence_ids": [
      "order:9b75cdaf...",
      "item:9b75cdaf...:1",
      "item:9b75cdaf...:2",
      "payment:9b75cdaf...:1",
      "policy:DELIVERY_WITHIN_ESTIMATE"
    ]
  }
  ```
* **Agent sử dụng**: `Policy Agent` (`:9105`).

---

### 🛠️ Tool 6: `validate_and_truncate_output`
* **Mô tả**: Guardrail kiểm định Schema: Ép toàn bộ số thực tiền tệ và số giờ về đúng 2 chữ số thập phân (`round(val, 2)`), cắt mảng theo trần giới hạn trong `LIMITS` (ví dụ `evidence_ids` <= 20, `resolution_actions` <= 5).
* **Tham số (`params`)**: `case_data` *(dict/json)*.
* **Giá trị trả về**: Dữ liệu JSON hoàn toàn hợp lệ 100% không còn bất kỳ lỗi Schema nào.
* **Agent sử dụng**: `Verifier Agent` (`:9106`).

---

## 4. Chi tiết Toàn bộ Kịch bản Script (`scripts/`)

Thư mục `scripts/` chứa 7 script hỗ trợ vận hành và kiểm thử hệ thống:

### 1. `scripts/run_agents.py`
* Khởi chạy đồng thời **MCP Server** (port 8765) và **7 A2A Agent Services** (ports 9100 đến 9106) trong 1 tiến trình Python bất đồng bộ duy nhất.
* Lệnh chạy: `.venv\Scripts\python.exe scripts/run_agents.py`

### 2. `scripts/run_batch.py`
* Đọc toàn bộ 50 ticket khiếu nại trong `input/EC_001.json` -> `EC_050.json`.
* Gửi qua Coordinator Agent để điều phối A2A 50 cases.
* Ghi 50 file kết quả JSON tương ứng vào `output/EC_001.json` -> `EC_050.json`.
* Ghi nhật ký trace handoff vào `logging/trace.jsonl` và thông tin môi trường vào `logging/metadata.json`.
* Lệnh chạy: `.venv\Scripts\python.exe scripts/run_batch.py`

### 3. `scripts/make_submission_zip.py`
* Tự động nén folder `output/` thành file `output.zip` (dung lượng 48.1 KB).
* Đảm bảo cấu trúc đường dẫn bên trong zip có đúng tiền tố `output/EC_xxx.json` theo đúng quy định của Ban Tổ Chức.
* Lệnh chạy: `.venv\Scripts\python.exe scripts/make_submission_zip.py`

### 4. `scripts/validate_output.py`
* Script kiểm tra trước khi nộp bài. Đảm bảo:
  * Có đủ 50 file trong `output/`.
  * Không chứa file thừa/thiếu.
  * Mỗi file JSON khớp 100% Schema quy định.
  * Toàn bộ `evidence_ids` đều có dữ liệu thực tế trong CSV (Grounding check).
* Lệnh chạy: `.venv\Scripts\python.exe scripts/validate_output.py`

### 5. `scripts/run_dashboard.py`
* Khởi tạo Web Server điều tra (port 8000) và tự động mở trình duyệt web giao diện điều tra Multi-Agent.
* Lệnh chạy: `.venv\Scripts\python.exe scripts/run_dashboard.py`

### 6. `scripts/sync_to_k3.py`
* Tự động đồng bộ toàn bộ mã nguồn `src/` và `scripts/` sang thư mục workspace nhóm `D:\Workspace\K3-Day9-Multi-Agent-A2A`.
* Lệnh chạy: `python scripts/sync_to_k3.py`

### 7. `scripts/test_all_50_cases_api.py`
* Kịch bản test tự động gửi request HTTP POST 50 cases qua API server để xác minh toàn bộ 50 cases đều đạt kết quả 200 OK và hợp lệ.
* Lệnh chạy: `.venv\Scripts\python.exe scripts/test_all_50_cases_api.py`

---

## 5. Quy trình Xử lý End-to-End & Luồng Handoff A2A

```text
[BƯỚC 1: TIẾP NHẬN TICKET]
Coordinator Agent (:9100) đọc ticket input EC_001.json
  │
  ├──► BƯỚC 2: PHÂN CÔNG SONG SONG (A2A DISPATCH)
  │      ├─► Customer Agent (:9101)      ──> Gọi MCP Tool 1 ──► Lấy customer_context
  │      ├─► Order & Product Agent (:9102)──> Gọi MCP Tool 2 ──► Lấy affected_entities & product_context
  │      ├─► Payment Agent (:9103)       ──> Gọi MCP Tool 3 ──► Lấy payment_reconciliation
  │      └─► Delivery Agent (:9104)      ──> Gọi MCP Tool 4 ──► Lấy delivery_analysis
  │
  ├──► BƯỚC 3: TỔNG HỢP BẰNG CHỨNG (HANDOFF AGGREGATION)
  │      Coordinator tập hợp dữ liệu từ 4 Domain Agent về 1 context duy nhất
  │
  ├──► BƯỚC 4: ĐÁNH GIÁ CHÍNH SÁCH & QUYẾT ĐỊNH (POLICY EVALUATION)
  │      Coordinator gọi Policy Agent (:9105)
  │      Policy Agent gọi MCP Tool 5 (evaluate_ec_policy)
  │      └─► Chốt primary_issue, secondary_issues, refund_brl, actions & evidence_ids
  │
  └──► BƯỚC 5: KIỂM ĐỊNH SCHEMA & XUẤT FILE (SCHEMA AUDIT & OUTPUT)
         Coordinator gọi Verifier Agent (:9106)
         Verifier Agent gọi MCP Tool 6 (validate_and_truncate_output)
         └─► Ép kiểu, làm tròn 2 chữ số thập phân, cắt mảng theo LIMITS
         └─► Ghi kết quả vào file output/EC_001.json
```

---

## 6. Hướng dẫn Khởi chạy & Nộp bài Thi

### 1. Chạy điều tra và sinh 50 Output Cases
```powershell
.venv\Scripts\python.exe scripts/run_batch.py
```

### 2. Kiểm tra tính hợp lệ của Output trước khi nộp
```powershell
.venv\Scripts\python.exe scripts/validate_output.py
```
*(Kết quả mong đợi: `PASS: 50/50 files, schema+evidence clean`)*

### 3. Tạo file Zip Nộp bài
```powershell
.venv\Scripts\python.exe scripts/make_submission_zip.py
```
*(File nộp bài `output.zip` chuẩn 48.1 KB sẽ được tạo ngay tại root repo).*

### 4. Mở Web UI Testing Dashboard để Demo
```powershell
.venv\Scripts\python.exe scripts/run_dashboard.py
```
*(Trình duyệt sẽ tự động mở `http://localhost:8000` với giao diện theo dõi real-time logs A2A & MCP)*.
