# Hướng dẫn chạy hệ thống — K4 Day 9 Multi-Agent (A2A + MCP)

> Yêu cầu máy: Windows, Python 3.12. Thư mục làm việc:
> `D:\Workspace\DAY9-2A202601256-NguyenHungManh`. Đã có sẵn `.venv`.
> Provider LLM chọn qua biến môi trường `EC_LLM_PROVIDER` — xem mục 0.2.

## 0. Setup một lần duy nhất (đã làm rồi thì bỏ qua)

```powershell
cd D:\Workspace\DAY9-2A202601256-NguyenHungManh

# 0.1. Cài dependency (chỉ khi .venv chưa có / mới clone)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 0.2. Chọn provider LLM

Hệ thống hỗ trợ 3 provider, đặt qua biến môi trường `EC_LLM_PROVIDER` trước khi chạy
`run_agents.py` (tên model khai báo cứng trong `src/config.py` theo đúng quy định nộp bài,
chỉ API key đọc từ `.env`):

| `EC_LLM_PROVIDER` | Model | Cần gì |
| --- | --- | --- |
| `openrouter` (mặc định) | `qwen/qwen3-8b` — 8B, model card chính thức | `OPENROUTER_API_KEY` trong `.env` |
| `ollama` | `qwen3.5-4b-ec` local, 4B | Ollama đã cài + `powershell scripts\setup_ollama_model.ps1` (import model, chỉ cần 1 lần) |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` trong `.env` (tham số không được OpenAI công bố chính thức — xem `metadata.json`) |

```powershell
$env:EC_LLM_PROVIDER = "openrouter"   # hoặc "ollama" / "openai"
```

Muốn chạy nhiều lane song song trên các backend khác nhau (tăng thông lượng), đặt thêm
`EC_PORT_OFFSET` (số khác 0) cho mỗi lane để không đụng cổng — xem `architecture.md` mục 5.

## 1. Terminal 1 — bật hạ tầng (GIỮ NGUYÊN terminal này trong suốt quá trình)

```powershell
cd D:\Workspace\DAY9-2A202601256-NguyenHungManh
.venv\Scripts\python scripts\run_agents.py
```

Thành công khi thấy **đủ 7 dòng** `[run_agents] starting ...` (coordinator :9100 → verifier :9106)
và dòng `StreamableHTTP session manager started` (MCP server :8765).

## 2. Terminal 2 (mở mới) — chạy 50 case

```powershell
cd D:\Workspace\DAY9-2A202601256-NguyenHungManh
.venv\Scripts\python scripts\run_batch.py --parallel 6
```

- Ghi ra: `output/EC_*.json` (50 file), `logging/trace.jsonl` (trace thật), `logging/metadata.json`.
- Tốc độ phụ thuộc provider: `openrouter`/`openai` ~1-5 phút/case (mạng, có retry), `ollama` local
  chậm hơn nhiều (~5-30 phút/case tùy độ dài hội thoại, chạy trên GPU laptop).
- Không có cờ "chạy nhanh" bỏ qua LLM — **mọi giá trị trong output đều do LLM tự tính**, không có
  đường tắt deterministic nào để rút ngắn.
- Muốn chạy lại một số case cụ thể (ví dụ case bị fail): `--cases EC_004,EC_017` thay vì chạy lại
  cả 50. Muốn chạy một khoảng: `--start 0 --end 40`.
- Một số case có thể fail (model không gọi được tool nộp kết quả sau vài vòng) — hệ thống **không**
  tự chế số liệu thay, chỉ ghi case đó vào `cases_failed` trong `metadata.json`. Chạy lại đúng case
  đó bằng `--cases` cho tới khi đủ 50/50.

## 3. Kiểm tra trước khi nộp (vẫn Terminal 2)

```powershell
# 3.1. Validator: schema, giới hạn mảng, evidence đối chiếu CSV gốc
.venv\Scripts\python scripts\validate_output.py
# PHẢI in đúng: PASS: 50/50 files, schema+evidence clean.

# 3.2. Unit test (MCP tool dữ liệu thô + validator)
.venv\Scripts\python -m pytest -q
# PHẢI: 11 passed
```

Nếu không PASS: **không nộp**, chạy lại bước 2 hoặc kiểm tra lỗi trước.

## 4. Đóng gói và nộp

```powershell
.venv\Scripts\python scripts\make_submission_zip.py
```

- Ra file `output.zip` ở gốc thư mục, bên trong đúng cấu trúc `output/EC_001.json` → `output/EC_050.json`
  (đúng 50 file, không có file lạ).
- Upload file này lên trang competition (điền 5 số cuối MSSV + lớp) → **Nộp và chấm điểm**.
- Giữa 2 lượt nộp phải cách 120 giây; điểm mới thay điểm cũ.

## 5. Demo UI (tùy chọn — Terminal 1 phải đang chạy)

```powershell
# Terminal 3
cd D:\Workspace\DAY9-2A202601256-NguyenHungManh
.venv\Scripts\python src\web\server.py 8000
```

- Mở `http://localhost:8000` → chọn case → **Investigate**: mỗi lần bấm, ticket đi qua
  pipeline A2A + MCP **thật** — trace trên UI là timestamp wall-clock thật, tên MCP tool thật.
- Trang audit tĩnh của lượt chạy 50 case: mở `logging\trace_viewer.html` trực tiếp trong browser
  (không cần server).

## Xử lý sự cố nhanh

| Triệu chứng | Nguyên nhân / Cách xử lý |
| --- | --- |
| `connection refused` khi chạy batch/dashboard | Terminal 1 chưa chạy hoặc đã tắt — bật lại bước 1. |
| Port 8765/9100-9106 bị chiếm khi bật Terminal 1 | Còn instance cũ: `netstat -ano \| findstr 8765` lấy PID → `taskkill /F /PID <pid>`. |
| `agent did not call final tool ... within N rounds` | Model không hoàn tất được vòng tool-calling cho case đó — chạy lại đúng case bằng `--cases EC_xxx`, thường qua ở lần thử sau (nhiệt độ 0.1 vẫn có biến thiên). |
| `insufficient credits` (OpenRouter) | Tài khoản free-tier hết credit — đổi `EC_LLM_PROVIDER=openai` hoặc `ollama` tạm thời. |
| Model Ollama vẫn nằm trên GPU sau khi tắt hết | Bình thường — Ollama giữ model vài phút (keep-alive) rồi tự unload. Đuổi ngay: `ollama stop qwen3.5-4b-ec`. Xem trạng thái: `ollama ps`. |
| Lỗi ký tự lạ khi in tiếng Việt trong console | Chạy với `$env:PYTHONIOENCODING="utf-8"` trước lệnh python. |

## Ghi chú minh bạch (chống nghi ngờ hardcode)

- Không có hàm Python nào tính hộ số liệu nghiệp vụ. MCP tool (`src/mcp_server/server.py`) chỉ lọc
  dữ liệu thô theo khóa từ 9 file CSV gốc — không sum, không trừ ngày giờ, không dựng evidence ID,
  không phân loại. Mọi agent tự tính và tự nộp kết quả qua một tool nội bộ (`report_*`); hệ thống
  chỉ bắt lấy đúng arguments model đưa ra, không sửa, và từ chối mọi lời gọi tool nộp-kết-quả đi
  kèm tool khác trong cùng lượt (chống model đoán số liệu trước khi thấy kết quả thật — xem
  `agent_tool_loop()` trong `src/agents/base.py`).
- Lớp deterministic DUY NHẤT còn lại là `validate_case_output` trong Verifier: kiểm schema, trần
  mảng, đối chiếu evidence với CSV gốc — chỉ pass/fail, không bao giờ điền hay sửa giá trị.
- Model dùng để nộp bài khai báo đầy đủ trong `logging/metadata.json` (tên, tham số, provider cho
  từng nhóm case) — không giấu bất kỳ provider nào đã dùng.
- `logging/trace.jsonl` là trace thật của lượt chạy cuối cùng (không append qua nhiều lượt).
