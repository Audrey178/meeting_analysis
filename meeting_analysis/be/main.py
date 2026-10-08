"""Điểm vào của FastAPI: ghép ứng dụng (CORS, khởi động, các router).

    uvicorn --app-dir be main:app

Xem ``DESIGN.md`` về quy trình mà API này phơi ra, và ``services/pipeline.py`` cho
chính quy trình đó; module này chỉ ghép ứng dụng HTTP lại với nhau.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

# Thiết lập sys.path viết trực tiếp tại đây (không đưa vào module dùng chung) để không
# phụ thuộc việc `be/` đã import được hay chưa: phải chạy đúng dù file được tìm thấy
# theo cách nào (`--app-dir be main:app`, đứng trong `be/`, hay `be.main:app` từ thư mục
# gốc coi `be` như namespace package). `__file__` luôn phân giải đúng bất kể cách tìm
# module; mọi file khác trong `be/` cần import `src.*`/`treeseg` đều lặp lại đúng khối này.
_BE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BE_DIR.parent
_TREESEG_DIR = _REPO_ROOT / "experiments" / "treeseg_turn_level"
for _dir in (_BE_DIR, _TREESEG_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import health, meetings, meetings_v3, mrg
from services.dependencies import build_embedding_adapter, build_topic_segmenter
from services.mrg import MrgJobStore

# override=True: .env là nguồn cấu hình chuẩn, thắng các biến cũ còn export trong shell
# (đã gặp: VERIFIER_* của DeepSeek trong shell đè cấu hình gpt-4o-mini mới trong .env).
load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _read_allowed_origins_from_env() -> list[str]:
    """Đọc danh sách origin được phép gọi API từ biến môi trường ``ALLOWED_ORIGINS``.

    Giá trị là các origin cách nhau bằng dấu phẩy, mặc định ``*`` (cho phép tất cả).
    Khi dev, ``FE/vite.config.ts`` proxy cùng origin nên không cần CORS; chỉ cần khi
    frontend production nằm ở origin khác (``VITE_API_BASE_URL``) hoặc client HTTP khác.

    Đầu ra: list[str] các origin; ``["*"]`` nếu để mặc định.
    """

    raw = os.environ.get("ALLOWED_ORIGINS", "*").strip()
    if raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Chạy một lần khi ứng dụng khởi động: dựng adapter embedding và bộ cắt chủ đề dùng chung.

    Đầu vào: app - ứng dụng FastAPI; lưu ở ``app.state.embedding_adapter`` và
        ``app.state.topic_segmenter`` (None nếu ``TOPIC_SEGMENTER=treeseg``; xem ``build_topic_segmenter``),
        ``app.state.mrg_jobs`` (kho job MA-MRG; ``MRG_MAX_CONCURRENT_JOBS`` job chạy song song, mặc định 1).
    """

    app.state.embedding_adapter = build_embedding_adapter()
    app.state.topic_segmenter = build_topic_segmenter()
    app.state.mrg_jobs = MrgJobStore(max_workers=int(os.environ.get("MRG_MAX_CONCURRENT_JOBS", "1")))
    yield


app = FastAPI(title="Meeting Analysis API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_read_allowed_origins_from_env(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(meetings.router)
app.include_router(meetings_v3.router)
app.include_router(mrg.router)
