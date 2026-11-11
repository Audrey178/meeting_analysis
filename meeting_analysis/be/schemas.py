"""Schema request của HTTP API (xem ``routers/meetings_v3.py``); ba document trả về nằm ở
``services/documents.py``."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from services.documents import SourceIn


class AttendeePersonIn(BaseModel):
    """Một người tham dự (cùng dạng file ``<transcript>.attendees.json``); ``id`` là ``ref_id`` của
    người đó trong transcript."""

    id: str
    full_name: str
    position: str = ""
    org_id: str | None = None


class AttendeeOrganizationIn(BaseModel):
    """Một đơn vị tham dự hoặc có thể được giao việc; ``parent_id`` là mã đơn vị cấp cha (None nếu
    là đơn vị cấp 0), ``functions`` là các mảng việc phụ trách, ``aliases`` là các tên gọi tắt
    trong bản ghi ("Đảng ủy ban")."""

    id: str
    name: str
    parent_id: str | None = None
    functions: list[str] = []
    aliases: list[str] = []


class AttendeesIn(BaseModel):
    """Danh sách người/đơn vị tham dự phiên họp (chỉ pipeline v3 dùng để định danh actor)."""

    people: list[AttendeePersonIn] = []
    organizations: list[AttendeeOrganizationIn] = []


class AnalyzeRequest(BaseModel):
    """Phần transcript của request phân tích cuộc họp (``AnalyzeV3Request`` kế thừa).

    Cùng dạng với JSON transcript gốc (``inputs/sample_transcript.json``) và được chuyển
    nguyên vẹn cho ``parse_transcript_payload``. Vì vậy ``items`` cố ý để lỏng (``list[dict]``) thay vì
    khai lại từng trường, tránh lệch so với parser.

    ``meeting_id`` PHẢI được khai báo (khác ``items``) vì Pydantic âm thầm bỏ mọi trường
    không khai báo trên model; thiếu nó thì ``request.model_dump()`` chỉ đưa
    ``{"items": [...]}`` cho ``parse_transcript_payload``.

    ``meeting_id`` TÙY CHỌN: ``parse_transcript_payload`` nhận diện danh sách item xuất từ
    STT (item có ``segment``/``speaker_name``, như ``inputs/recording_old.json``) và tự
    dùng ``"stt-export"`` khi thiếu. Chỉ dạng "native" mới bắt buộc trường này, và
    ``_parse_native_payload`` tự báo lỗi rõ ràng. Từng bắt buộc nó vô điều kiện ở đây làm
    hỏng trường hợp STT export (payload thật giống ``recording_old.json``); lỗi này chỉ phát
    hiện khi thử payload thật vào endpoint đang chạy, vì transcript mẫu của test tình cờ đã có sẵn.

    Các trường:
        meeting_id: mã cuộc họp (tùy chọn).
        meeting_date: ngày họp (tùy chọn), neo để quy hạn chót của việc giao ("tuần sau")
            về ``deadline_date``; thiếu thì vẫn có ``deadline_kind``.
        items: danh sách các dòng transcript ở dạng dict.
        attendees: danh sách người/đơn vị tham dự (tùy chọn); thiếu thì actor
            chỉ được quy về người nói trong bản ghi.
    """

    meeting_id: str | None = None
    meeting_date: date | None = None
    items: list[dict]
    attendees: AttendeesIn | None = None


class TaskIn(BaseModel):
    """Một việc cần báo cáo tiến độ (cùng dạng file ``<transcript>.tasks.json``).

    ``owner``/``support``/``reporter`` là mã người (``P*``) hoặc đơn vị (``O*``) trong
    ``attendees``, hoặc tên tự do. ``due`` là ngày "YYYY-MM-DD"; ``last_status`` là một trong
    "not_started", "in_progress", "done", "blocked". Phần kiểm giá trị nằm ở
    ``src/pipeline/shared/meeting_inputs/agenda.py`` (sai thì trả 422).
    """

    id: str
    title: str
    owner: str
    support: list[str] = []
    reporter: str | None = None
    due: str | None = None
    last_status: str | None = None
    source: str = ""


class TasksIn(BaseModel):
    """Danh sách việc cần báo cáo tiến độ trong phiên họp (chỉ pipeline v3 dùng)."""

    tasks: list[TaskIn] = []


class ChairIn(BaseModel):
    """Người chủ trì: ``id`` là mã người trong ``attendees``; khớp thì dùng tên trong
    danh sách, không thì dùng ``full_name``."""

    id: str
    full_name: str


class AnalyzeV3Request(AnalyzeRequest):
    """Đầu vào của ``POST /v3/meetings/tasks|decisions|content``: transcript
    (như ``AnalyzeRequest``) + người chủ trì, danh sách việc, nguồn.

    Các trường thêm:
        chair: người chủ trì ``{id, full_name}`` (tùy chọn). v3 lấy tên theo ``id`` trong ``attendees``
            và đưa vào prompt của agent trích xuất và Verifier, để nhận ra
            lời giao việc/kết luận của chủ trì. None hoặc rỗng thì model tự suy ra từ bản ghi.
        tasks: danh sách việc cần báo cáo tiến độ (tùy chọn, chỉ document Giao việc dùng). Có thì
            Action agent v3 trích thêm tiến độ: mọi lời nói về một việc cũ vào dòng của việc đó.
        source: nguồn transcript/tài liệu (tùy chọn), chỉ chép vào ``source`` của document, không
            ảnh hưởng kết quả nên không vào khoá cache.
    """

    chair: ChairIn | None = None
    tasks: TasksIn | None = None
    source: SourceIn | None = None
