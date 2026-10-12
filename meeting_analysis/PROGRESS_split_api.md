# Tiến độ: tách `/v3/meetings/analyze/{part}` thành 3 API (tasks / decisions / content)

Cập nhật: 2026-10-12 (lần 4). Đây là file ghi chú tạm, xoá khi xong việc.

## Mục tiêu

- `POST /v3/meetings/tasks`: gộp việc giao mới và cập nhật tiến độ việc cũ (backlog). Output theo `outputs/giaoviec.json`.
- `POST /v3/meetings/decisions`: output theo `outputs/ketluan.json`.
- `POST /v3/meetings/content`: output tự thiết kế, cùng khung envelope với `giaoviec.json`.
- Metadata của cuộc họp theo `giaoviec.json`. Envelope gồm:
  - `schema_version`, `document_type`, `meeting_id`, `artifact_revision`
  - `source`, `generation`, `data`, `extensions`
- Trích dẫn ở mức item thô: `segment_ids` là `id` của item trong `inputs/bien-ban-vdt-trang-v1.json`, kèm `turn_ids`.

Lưu ý: `outputs/giaoviec.json` hiện không phải JSON hợp lệ (dư dấu phẩy ở dòng ~124).

## Quyết định mặc định (user chưa trả lời, đang dùng đề xuất của Claude)

- **Phần header của decisions:** giữ biên bản header trong `data.header`.
  - `ngay_hop` lấy từ `meeting_date`.
  - `chu_tri` lấy từ `chair`.
  - Các số đếm lấy từ `attendees`.
- **Assignment theo loại:**
  - `follow_up` thành task riêng, có `dependency_task_ids: [backlog id]`.
  - `reassign` và `reschedule` gộp vào task backlog tương ứng.
- **Trích dẫn:** LLM chỉ trích `segment_ids`; `turn_ids` do luật suy ra.
- **Endpoint cũ:** tạm giữ `/analyze` và `GET /analyses/{key}` cho FE; bỏ `/analyze/{part}`.
- **Span của topic:** `span.segment_ids` là `[first, last]`.

## Đã xong (bước 1: trích dẫn mức item)

- **`src/utils/contracts.py`:** `SpeakerTurn.source_items: tuple[(item_id, text), ...]`.
- **`src/stages/stage03_speaker_turns.py`:** điền `source_items` khi gộp item thành lượt nói.
- **`src/agentic_v3/core/_shared.py`:**
  - `validate_evidence_by_turn_ids` được thay bằng `validate_evidence_by_segment_ids(turns, claimed, required_turn_ids)`, trả về `(evidence_ids, quotes, segment_ids)`.
  - Hàm này vẫn nhận turn_id; khi gặp turn_id thì mở rộng ra mọi item của lượt đó.
  - Thêm `_merge_evidence`, dùng chung cho `merge_duplicate_assignments` và `merge_duplicate_decisions`.
  - Thêm `format_turn_text`. Prompt hiển thị dạng `[TURN|speaker] <id> câu <id> câu`.
- **`segment_ids` trên các schema:** đã thêm vào:
  - `core/schemas.py`: `DiscussionPoint`, `DecisionCandidate`, `ActionItemCandidate`
  - `agentic_v3/schemas.py`: `ProgressUpdate`
- **Các agent đã đổi schema, prompt và cách parse sang `evidence_segment_ids`:**
  - `content_agent.py`
  - `action_agent.py`
  - `decision_agent.py`
  - `nodes/progress.py`: `_merge_same_task` gộp thêm `segment_ids`, lượt bắt buộc là `status_turn_id`.
- **`nodes/prompts.py`:**
  - `EVIDENCE_RULE` và `TURN_ID_RULE` giải thích mã `<item_id>`.
  - Các câu "Phải là một trong evidence_turn_ids" đổi thành "Phải là lượt chứa một trong evidence_segment## Đã xong (bước 3–7: tách API, 244 test pass)

- **Bước 1 khép lại:** fake LLM và docstring đã đổi từ trước; nhánh amend của verifier thêm bằng
  chứng qua `_evidence_with_turn`. `_format_turn_snippet` của verifier giữ nguyên: verifier chỉ trả
  `confirm_turn_id` (mức lượt), thêm mã item chỉ tốn ký tự trong đoạn cắt.
- **Cache (`pipeline_v3.py`, `analysis_cache.py`):**
  - `analysis_key` = hash(fingerprint + `meeting_id`, `revision_id`, `items`). Hai id có trong hash
    vì `meeting_id` vào mã evidence và `meeting_id` của document.
  - Mục `base` thêm `items` (id gốc + `speaker_id`). `_restore_dataclass` khôi phục tuple lồng nhau.
  - Mỗi document là mục `"{doc}@{sha256(inputs)[:16]}"`. Regex tên mục: `^[a-z_]+(@[0-9a-f]{16})?$`.
  - **Quyết định thêm:** content và decisions chạy với `task_agenda=None`. Lý do: danh sách việc
    nằm trong khối danh bạ của prompt mọi agent, mà khoá của hai document này không gồm `tasks`.
  - Mục document lưu `context` (`chair`, `meeting_date`, `attendees`, `tasks`, `source`) để GET
    dựng lại được document mà không cần request. POST trả `source` của chính request.
- **`be/services/documents.py`:** đủ model Pydantic và builder như mục 4 của kế hoạch.
  `build_document` validate qua model nên dict của service trùng với response của API.
  Phần thêm so với kế hoạch:
  - `extensions.document_key` (tên mục cache) dùng cho GET.
  - `extensions.audit` gồm `verification_records`, `skipped_agents`, `failed_topics`.
  - `data.turns` của content để FE hiển thị transcript.
  - `source_segment_refs` = `[{segment_id, turn_id, text}]`.
  - `target_type` có thêm `unknown`.
  - Backlog: `execution_status` suy từ status sau họp; `reassign` đổi bên chính,
    `reschedule` đổi hạn; `extensions.merged_relations` ghi lại các quan hệ đã gộp.
- **Router:**
  - Thêm `POST /v3/meetings/tasks|decisions|content` (`refresh`, `refresh_base`) và
    `GET /v3/meetings/analyses/{key}/{document_key}`. Đã bỏ `/analyze/{part}`.
  - `/analyze` cũ ghép ba document thành `AnalyzeV3Result`. `GET /analyses/{key}` cũ dùng mục
    trỏ `analyze` nằm dưới khoá hash của cả request (không gồm `source`).
- **FE tạm:** `reloadMeetingV3Part` gọi `POST /{doc}?refresh=true` rồi `/analyze` (lấy từ cache).
  Chạy lại Giao việc thì Tiến độ cũng được tính lại.
- **Test và docs:**
  - `be/test_api_v3.py` có test hình dạng 3 document, test id số của STT, test cache theo
    document và test cho endpoint cũ.
  - Đã cập nhật `be/PIPELINE.md` và `ARCHITECTURE.md` §8 / §8.1.
- **Chạy thật** (gemma, `bien-ban-vdt-trang-v1` + attendees/tasks của bản copy):
  - Cả 3 document `complete`, phủ 237/237 item.
  - Trích dẫn: 25/30 mục chọn từng item, 5 mục trích cả lượt (4 ý thảo luận, 1 tiến độ).

## Đã xong (bước 8: FE theo document, bỏ endpoint cũ)

- **FE viết lại view theo document:**
  - `hooks/useMeetingDocuments.ts` gọi 3 POST song song.
  - "Chạy lại toàn bộ": content gửi `refresh_base` trước, hai document kia gửi sau.
  - Khôi phục phiên bằng `GET .../{document_key}`.
  - `ResultView` có các tab Diễn biến / Giao việc (task mới) / Tiến độ (task cũ) / Kết luận
    (kèm thẻ biên bản) / Kiểm chứng / JSON.
  - Transcript tô ở mức dòng (item).
  - Đã xoá `V3ResultView.tsx`, `v3Selection.ts`, `useV3Analysis.ts`.
- **Backend:**
  - Bỏ `/analyze`, `GET /analyses/{key}`, phần ghép kết quả cũ, mục trỏ `analyze` và các schema
    `*Out` cũ.
  - `ProgressStepOut` thêm `p_directive` và `deciding`.
- **Kiểm tra:**
  - 232 test pass; `tsc` và `oxlint` sạch.
  - Chạy thử bằng Chrome với LLM thật: 3 document hiện đúng; tô item đúng; tải lại trang lấy từ
    cache; "Chạy lại Kết luận" lên lần tính #2; console không có lỗi.

## Đã xong: bỏ lớp dữ liệu trung gian dạng cũ

- `documents.build_document_entry(document, MeetingReport, MeetingContext)` dựng `data` + `audit` +
  `coverage` + `warnings` thẳng từ dataclass. Mục cache lưu đúng nội dung đó;
  `build_document` chỉ bọc khung và validate qua model.
- Đã xoá khỏi `pipeline_v3.py`: các hàm `_serialize_*`, `_group_meeting_development_by_topic`,
  `_build_part_data` và `_document_context`. `audit` giờ có model riêng
  (`VerificationRecordOut`, `SkippedAgentOut`, `FailedTopicOut`).
- Việc cũ: bên chủ trì và các bên phối hợp lấy từ `TaskAgenda` (`TaskParty.ref_id`, tra loại người/đơn
  vị trong roster). Trước đây `collaborators` luôn rỗng.
- `eval/run_pipeline_eval.py` và `eval/build_judge_packet.py` vẫn dùng `services.pipeline` của v1
  (đã xoá từ trước), nên đang hỏng sẵn, không liên quan thay đổi này.

## Việc còn lại

1. **Đánh giá chất lượng prompt** (bước 2 cũ):
   - Chạy probe lặp theo topic, kèm file gold progress (`bien-ban-vdt-trang-copy-v1.progress-gold.json`
     ứng với transcript 32 item của bản copy).
   - Theo dõi tỉ lệ trích cả lượt.
2. **`task_id` có hậu tố:** nhiều việc cùng lượt chốt và cùng bên chính thì ra `_2`, `_3`…
   (bản chạy thật có 4 việc cùng `TURN_000030` / Đảng ủy UBND). Hậu tố phụ thuộc thứ tự LLM trả,
   nên không ổn định qua các lần chạy lại. Cân nhắc thêm vào hash: item chốt đầu tiên, hoặc nội dung.
