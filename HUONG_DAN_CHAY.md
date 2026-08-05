# Hướng dẫn chạy hệ thống — K4 Day 9 Multi-Agent (A2A + MCP + Ollama local)

> Yêu cầu máy: Windows, GPU NVIDIA (~4GB VRAM trống), Ollama đã cài, Python 3.12.
> Thư mục làm việc: `D:\Workspace\DAY9-2A202601256-NguyenHungManh`. Đã có sẵn `.venv`.

## 0. Setup một lần duy nhất (đã làm rồi thì bỏ qua)

```powershell
cd D:\Workspace\DAY9-2A202601256-NguyenHungManh

# 0.1. Cài dependency (chỉ khi .venv chưa có / mới clone)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 0.2. Import model local vào Ollama (chỉ khi `ollama list` chưa có qwen3.5-4b-ec)
powershell scripts\setup_ollama_model.ps1

# Kiểm tra: phải thấy dòng qwen3.5-4b-ec
ollama list
```

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
.venv\Scripts\python scripts\run_batch.py --parallel 4
```

- Chạy ~4 phút, in tiến độ `[1/50]` → `[50/50]`, kết thúc bằng `Done. 50/50 cases written`.
- Ghi ra: `output/EC_*.json` (50 file), `logging/trace.jsonl` (trace thật), `logging/metadata.json`.
- Lặp thử nghiệm nhanh (~90 giây): thêm cờ `--fast` — bỏ bước LLM viết narration
  (chỉ ảnh hưởng ghi chú trong trace, **không đổi bất kỳ giá trị nào trong JSON được chấm**).
  Lần chạy chốt để nộp thì chạy **không có** `--fast` cho trace đầy đủ.

## 3. Kiểm tra trước khi nộp (vẫn Terminal 2)

```powershell
# 3.1. Validator: schema, giới hạn mảng, evidence đối chiếu CSV gốc
.venv\Scripts\python scripts\validate_output.py
# PHẢI in đúng: PASS: 50/50 files, schema+evidence clean.

# 3.2. Unit test (policy engine đối chiếu từng nhánh EC_POLICY_V2 với data thật)
.venv\Scripts\python -m pytest -q
# PHẢI: 15 passed
```

Nếu không PASS: **không nộp**, chạy lại bước 2 hoặc kiểm tra lỗi trước.

## 4. Đóng gói và nộp

```powershell
.venv\Scripts\python scripts\make_submission_zip.py
```

- Ra file `output_submit.zip` ở gốc thư mục, bên trong đúng cấu trúc `output/EC_001.json` → `output/EC_050.json`.
- Upload file này lên trang competition (điền 5 số cuối MHV + lớp) → **Nộp và chấm điểm**.
- Giữa 2 lượt nộp phải cách 120 giây; điểm mới thay điểm cũ.

## 5. Demo UI (tùy chọn — Terminal 1 phải đang chạy)

```powershell
# Terminal 3
cd D:\Workspace\DAY9-2A202601256-NguyenHungManh
.venv\Scripts\python src\web\server.py 8000
```

- Mở `http://localhost:8000` → chọn case → **Investigate**: mỗi lần bấm, ticket đi qua
  pipeline A2A + MCP **thật** (mất ~10-15s vì chờ GPU sinh narration) — trace trên UI là
  timestamp wall-clock thật, tên MCP tool thật.
- Trang audit tĩnh của lượt chạy 50 case: mở `logging\trace_viewer.html` trực tiếp trong browser
  (không cần server) — 300 handoff, 50 narration LLM khác nhau, lọc theo primary issue.

## Xử lý sự cố nhanh

| Triệu chứng | Nguyên nhân / Cách xử lý |
| --- | --- |
| `connection refused` khi chạy batch/dashboard | Terminal 1 chưa chạy hoặc đã tắt — bật lại bước 1. |
| Port 8765/9100-9106 bị chiếm khi bật Terminal 1 | Còn instance cũ: `netstat -ano \| findstr 8765` lấy PID → `taskkill /F /PID <pid>`. |
| Model vẫn nằm trên GPU sau khi tắt hết | Bình thường — Ollama giữ model ~5 phút (keep-alive) rồi tự unload. Đuổi ngay: `ollama stop qwen3.5-4b-ec`. Xem trạng thái: `ollama ps`. |
| Batch chậm bất thường | GPU đang bận việc khác — kiểm tra `nvidia-smi`; hoặc dùng `--fast` khi chỉ cần thử nghiệm. |
| Lỗi ký tự lạ khi in tiếng Việt trong console | Chạy với `$env:PYTHONIOENCODING="utf-8"` trước lệnh python. |

## Ghi chú minh bạch (chống nghi ngờ hardcode)

- Model duy nhất: `qwen3.5-4b-ec` (Qwen3.5-4B, Q4_K_M, 4B tham số — dưới trần 10B), khai báo trong
  `src/config.py`, chạy local qua Ollama `http://localhost:11434`. Không có API ngoài; repo không
  chứa `.env`, không có reference OpenAI.
- Mọi giá trị được chấm điểm do **MCP policy engine** (`src/mcp_server/policy_engine.py`) tính
  từ 9 file CSV gốc — agent lấy fact qua MCP tool, không được bịa.
- `logging/trace.jsonl` là trace của lượt chạy thật: 300 handoff, timestamp micro-giây,
  4 agent evidence song song, narration LLM khác nhau từng case.
