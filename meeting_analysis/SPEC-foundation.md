# Spec module: `foundation`

Thuộc bản đồ [SPEC.md](SPEC.md). Phụ thuộc: không có. Các module sau đều dựa vào nó.

## Mục tiêu

Dựng nền chung cho mọi module: package `app/` cài được (không cần chèn `sys.path`), cấu hình tập trung,
logging, exception nghiệp vụ, tooling. **Không đổi hành vi runtime nào**: `be/` và `src/` vẫn chạy y như cũ
cho tới khi module sau thay chúng.

Ngoài phạm vi: chuyển code từ `be/` hay `src/` sang (thuộc các module sau). Mỗi module sau tự thêm field
`Settings` cho biến môi trường mà nó chuyển sang, nên không định nghĩa trước field chưa ai dùng.

## Tech stack

- Python ≥ 3.11 (venv hiện tại là 3.12.3), `uv` + `uv.lock`, build backend setuptools.
- Dependency mới (đã duyệt cho module này): `pydantic-settings>=2.5,<3`; dev: `ruff`.
- Logging JSON viết bằng `logging` của stdlib (khoảng 20 dòng), không thêm `structlog` hay `python-json-logger`.

## Commands

```
uv sync --all-extras --group dev            # cài môi trường, kể cả app/ ở chế độ editable
uv run pytest tests                         # test của app/
uv run ruff check app tests                 # lint
uv run ruff format --check app tests        # format
uv run uvicorn --app-dir be main:app        # smoke: be/ cũ vẫn khởi động (GET /health → 200)
```

## Cấu trúc sau module này

```
app/
├── __init__.py
└── core/
    ├── __init__.py
    ├── config.py        # Settings + get_settings() (lru_cache)
    ├── logging.py       # configure_logging(), request_id_var, RequestIdFilter, JsonFormatter
    └── exceptions.py    # AppError và các lớp con
tests/
├── conftest.py
└── unit/core/
    ├── test_config.py
    ├── test_logging.py
    └── test_exceptions.py
pyproject.toml           # nguồn phụ thuộc duy nhất; [tool.ruff], [tool.pytest]
requirements.txt         # XOÁ (gộp vào pyproject)
```

`be/`, `src/`, `conftest.py` ở gốc giữ nguyên. Module `pipeline` sẽ bỏ `conftest.py` gốc khi `src/` hết.

## Yêu cầu

### `core/config.py`

- `Settings(BaseSettings)` có các field `app_env: Literal["dev", "staging", "prod"] = "dev"` và
  `log_level: str = "INFO"`.
- Mọi secret khai báo kiểu `SecretStr` (quy ước cho các module sau).
- Tên biến môi trường **giữ nguyên** như hiện tại (`OPENAI_API_KEY`, `V3_MAX_CONCURRENCY`…): field là tên
  biến viết thường, không prefix, không lồng nhau. `.env` hiện có dùng tiếp được, không phải sửa.
- Thứ tự ưu tiên **giữ như `load_dotenv(override=True)` hiện nay: `.env` thắng biến của shell.** Lý do: từng
  gặp `VERIFIER_*` cũ còn export trong shell đè cấu hình mới. Làm bằng `settings_customise_sources`, theo thứ tự
  init → dotenv → env.
- `get_settings()` cache bằng `@lru_cache`. Test gọi `get_settings.cache_clear()` hoặc dựng `Settings(...)` trực tiếp.

### `core/logging.py`

- `request_id_var: ContextVar[str]` (mặc định `"-"`). Middleware ở module `api` và task ở module `jobs` sẽ đặt giá trị.
- `RequestIdFilter` gắn `record.request_id` vào mọi bản ghi log.
- `configure_logging(settings)`: `app_env == "dev"` ghi text
  `%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s`; `staging` và `prod` ghi mỗi dòng một JSON
  gồm `ts, level, logger, message, request_id`, có lỗi thì thêm `exc_info`. Gọi nhiều lần không nhân đôi handler.

### `core/exceptions.py`

Exception nghiệp vụ không phụ thuộc HTTP. Handler ở module `api` đọc `code` và `http_status`.

| Lớp | `code` | `http_status` |
|---|---|---|
| `AppError` (gốc) | `internal_error` | 500 |
| `InvalidInputError` | `invalid_input` | 422 |
| `NotFoundError` | `not_found` | 404 |
| `ConflictError` | `conflict` | 409 |
| `UpstreamServiceError` | `upstream_error` (`upstream_timeout` khi `timed_out`) | 502 (504 khi `timed_out`) |
| `ServiceUnavailableError` | `service_unavailable` | 503 |

`LLMUpstreamError`, `CacheUnavailableError`… hiện có sẽ được nối vào cây này ở module sở hữu chúng, không làm ở đây.

### `pyproject.toml`

- `[tool.setuptools.packages.find]` đổi thành `include = ["app*"]` ở gốc. Cấu hình `package-dir = {"" = "src"}`
  hiện tại sai, vì code import `src.pipeline…`; nó chỉ chạy được nhờ `conftest.py` gốc chèn `sys.path`.
- Gộp `requirements.txt` vào `pyproject.toml`: thêm vào `dependencies` các gói còn thiếu mà code đang import
  (`openai`, `httpx`, `python-dotenv`, `pydantic`); rồi xoá `requirements.txt`.
- Xoá extra `be-v2`: không có code nào dùng, Postgres để sau thì thêm lại. Giữ `api`, `dialstart`,
  `local-embeddings`, `paper`; các module sau sẽ sắp xếp lại.
- `[dependency-groups] dev = ["pytest>=8,<9", "ruff", "fakeredis[lua]>=2.20,<3"]`.
- `[tool.ruff]`: `line-length = 120`, `target-version = "py311"`, `extend-exclude = ["src", "be", "experiments",
  "scripts", "FE"]` (gỡ dần khi code chuyển vào `app/`); lint `select = ["E", "F", "W", "I", "UP", "B"]`.
- `[tool.pytest.ini_options]`: `testpaths = ["tests"]`; giữ marker `integration`.

## Code style

```python
class Settings(BaseSettings):
    """
    Chức năng: Cấu hình ứng dụng, đọc từ file .env và biến môi trường (.env thắng shell).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"


class UpstreamServiceError(AppError):
    """
    Chức năng: Lỗi từ dịch vụ bên ngoài (LLM, kho transcript), không phải do dữ liệu của bên gọi.

    Đầu vào:
        message (str): Mô tả lỗi, trả về cho client.
        timed_out (bool): True nếu lỗi do hết thời gian chờ; chọn 504 thay vì 502.
    """

    code = "upstream_error"
    http_status = 502
```

## Chiến lược test

- `pytest`, đặt trong `tests/unit/core/`, không cần mạng, Redis hay LLM.
- `test_config.py`:
  - giá trị mặc định;
  - đọc từ biến môi trường (`monkeypatch.setenv`);
  - `.env` thắng shell (file `.env` tạm qua `tmp_path` + `_env_file`);
  - `SecretStr` không lộ trong `repr`/`str`.
- `test_logging.py`:
  - JSON ở `prod` parse được và có đúng `request_id` đang đặt trong contextvar;
  - text ở `dev`;
  - gọi `configure_logging` hai lần vẫn một handler.
- `test_exceptions.py`: `code` và `http_status` từng lớp; `UpstreamServiceError(timed_out=True)` thành 504 và `upstream_timeout`.

## Ranh giới

- **Luôn làm:** như [SPEC.md](SPEC.md); mỗi file mới có docstring module bằng tiếng Việt.
- **Hỏi trước:** mọi dependency ngoài `pydantic-settings` và `ruff`; chạy `ruff format` lên code ngoài `app/` và `tests/`.
- **Không bao giờ:** sửa `be/`, `src/`, `.env`; đổi tên biến môi trường.

## Tiêu chí hoàn thành

1. `uv sync --all-extras --group dev` thành công; `uv run python -c "import app.core.config"` chạy được từ một
   thư mục bất kỳ, không cần `conftest.py` hay `sys.path`.
2. `uv run pytest tests` xanh; `uv run ruff check app tests` và `uv run ruff format --check app tests` sạch.
3. Smoke test không hồi quy: `uv run uvicorn --app-dir be main:app` khởi động, `GET /health` trả 200.
4. `requirements.txt` và extra `be-v2` không còn; mọi gói mà `be/` và `src/` import đều có trong `pyproject.toml`.

## Câu hỏi còn mở

1. **Vị trí `.env`:** hiện `.env` nằm ở `meeting-analysis/.env` (gốc git, ngoài `meeting_analysis/`), và
   `load_dotenv()` tìm thấy nhờ dò ngược lên thư mục cha. Đề xuất: bạn tự chuyển `.env` và `.env.example` vào
   `meeting_analysis/`, vì tôi không đụng `.env`; `Settings` đọc `.env` ở thư mục đang chạy. Docker sẽ truyền
   biến qua `env_file` của compose.
2. **Thay đổi chưa commit:** `src/pipeline/shared/prompts.py` đã sửa và `src/pipeline/tests/` đã xoá. Đề xuất:
   bạn commit hai việc này trước, để baseline ở module `llm-client` ghi đúng bản prompt mới nhất.
3. **Nhánh:** làm tiếp trên `refactor/pipeline`, hay tách nhánh mới `refactor/backend-ai` từ HEAD sau khi commit?
