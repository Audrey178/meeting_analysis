# Spec: Refactor meeting-analysis thành backend AI chuẩn

Bản đồ module (đã duyệt 2026-11-11). Đây là mục lục của mọi spec module: spec của module `<id>` nằm ở
`SPEC-<id>.md` cạnh file này. Quy ước đích lấy từ skill `python-backend-ai-engineer`.

## Mục tiêu

Biến `be/` + `src/` (script nghiên cứu có lớp HTTP mỏng) thành một dịch vụ backend AI chạy ổn định:
một package `app/`, cấu hình tập trung, pipeline LLM sau một client, tác vụ dài chạy qua worker Celery,
API dạng job, test có LLM giả, Docker. **Kết quả phân tích không được đổi**: prompt đang tune cho bài báo.

Người dùng: (1) FE gọi API để phân tích cuộc họp; (2) tác giả chạy pipeline cho thí nghiệm.

## Quyết định đã chốt

| Câu hỏi | Quyết định |
|---|---|
| Phạm vi | Toàn bộ, kể cả `src/pipeline` |
| Hợp đồng API | Bỏ `/v3/meetings/*`; `/api/v1` dạng job (202 + `job_id`, poll trạng thái); sửa FE theo |
| Worker | Celery + Redis |
| Lưu trữ | Redis (broker, trạng thái job, cache). Postgres giữ trong compose, chưa dùng |
| Baseline | Được gọi LLM thật 1 lần để ghi câu trả lời cho `inputs/bien-ban-vdt-trang-copy-v1.json` |
| Prompt | Tách ra file template Jinja2 |
| `refresh` / `refresh_base` | Bỏ |

## Bản đồ module

| Module id | Trách nhiệm | Phụ thuộc |
|---|---|---|
| `foundation` | Package `app/`; `core/config.py` (pydantic-settings), `core/logging.py` (JSON + `request_id`), `core/exceptions.py`; `pyproject.toml` là nguồn phụ thuộc duy nhất; ruff + pytest | — |
| `llm-client` | Ghi baseline (record/replay); `app/ai/llm/`: adapter OpenAI-compatible + Verifier + Decisions, timeout, retry chọn lọc, semaphore, log token/latency; factory đọc `Settings` | foundation |
| `pipeline` | `app/ai/pipeline/`: 6 bước + graph; prompt sang `app/ai/prompts/*.j2`; docstring/logging theo quy ước; output giữ nguyên (replay test) | llm-client |
| `jobs` | `app/workers/`: Celery app, task phân tích idempotent, nạp DialSTART + analyzer một lần mỗi process, trạng thái job + kết quả từng phần trên Redis | pipeline |
| `api` | `app/main.py`, `app/api/v1/`: tạo job, đọc trạng thái/kết quả, `/health` `/ready`, lỗi JSON thống nhất, middleware `request_id`; xoá `be/` | jobs |
| `frontend` | `FE/src/api/`: tạo job + poll, cập nhật type | api |
| `deploy` | Dockerfile multi-stage (api, worker), compose api + worker + redis + postgres, `.env.example` | api, jobs |

Thứ tự xây: `foundation` → `llm-client` → `pipeline` → `jobs` → `api` → `frontend` ∥ `deploy`.

Mỗi module đi trọn vòng Specify → Plan → Tasks → Implement, có duyệt ở từng bước, rồi mới sang module sau.

| Spec | Trạng thái |
|---|---|
| [SPEC-foundation.md](SPEC-foundation.md) | Chờ duyệt |
| SPEC-llm-client.md … SPEC-deploy.md | Chưa viết |

## Ranh giới chung (mọi module)

- **Luôn làm:** tên tiếng Anh, docstring tiếng Việt có *Chức năng / Đầu vào / Đầu ra* (*Ngoại lệ* nếu raise);
  type hints cho hàm public; `logging` thay `print`; chạy `uv run pytest` + `uv run ruff check` trước mỗi commit;
  chuyển file bằng `git mv` ở commit riêng, sửa nội dung ở commit sau (giữ lịch sử, diff đọc được);
  mỗi task một commit nhỏ.
- **Hỏi trước:** thêm dependency ngoài danh sách đã duyệt trong spec module; đổi bất kỳ ký tự nào của prompt
  sau khi render; đổi schema output (tasks/decisions/content); gọi LLM thật (tốn tiền); đổi tên biến môi trường;
  đụng `.env`; xoá file ngoài phạm vi module; push / mở PR / merge.
- **Không bao giờ:** đọc hay commit secret (`.env`, API key); sửa logic, ngưỡng hay prompt của pipeline để test qua;
  xoá, skip hay nới assertion của test để xanh; sửa `experiments/dialstart` (trừ import), checkpoint, `paper/`.

## Tiêu chí hoàn thành (toàn dự án)

1. `be/`, `src/`, `requirements.txt` không còn; không còn `sys.path.insert` ngoài `experiments/`.
2. `os.environ` / `getenv` chỉ xuất hiện trong `app/core/config.py`.
3. Replay test: với câu trả lời LLM đã ghi, output pipeline giống baseline từng byte (JSON đã sort key).
4. Snapshot prompt: mọi prompt render ra giống hệt bản trước refactor.
5. `docker compose up` → `POST /api/v1/...` trả 202 → poll tới `succeeded` có đủ tasks, decisions, content.
6. `cd FE && npm run build` qua; FE chạy được với API mới.
7. `uv run pytest` xanh (không gọi LLM thật); `uv run ruff check app tests` sạch.
