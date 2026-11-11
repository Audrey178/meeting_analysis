# Meeting Analysis API (v3)

API phân tích biên bản cuộc họp từ transcript. Kết quả gồm ba document:

- **Diễn biến** (`content`): các chủ đề, ý thảo luận và lượt nói.
- **Giao việc** (`tasks`): việc mới được giao và tiến độ các việc cũ.
- **Kết luận** (`decisions`): các kết luận.

Code: router `routers/meetings_v3.py`, request `schemas.py`, response `services/documents.py`,
luồng và cache `services/pipeline_v3.py`, parser transcript `src/utils/adapters.py`.
Chạy server: `uvicorn --app-dir be main:app` (cổng mặc định 8000). Swagger ở `/docs`.
JSON mẫu đầy đủ của từng bước: `be/examples/` (xem `be/examples/README.md`).

## Mục lục

1. [Luồng chính](#1-luồng-chính)
2. [Danh sách endpoint](#2-danh-sách-endpoint)
3. [Input: body của `POST /content`](#3-input-body-của-post-content)
4. [Output: khung chung của document](#4-output-khung-chung-của-document)
5. [Kiểu dùng chung trong output](#5-kiểu-dùng-chung-trong-output)
6. [`POST /v3/meetings/content` → Diễn biến](#6-post-v3meetingscontent--diễn-biến)
7. [`GET /v3/meetings/tasks/{meeting_id}` → Giao việc](#7-get-v3meetingstasksmeeting_id--giao-việc)
8. [`GET /v3/meetings/decisions/{meeting_id}` → Kết luận](#8-get-v3meetingsdecisionsmeeting_id--kết-luận)
9. [`GET /v3/meetings/content/{meeting_id}` → Diễn biến (lấy lại)](#9-get-v3meetingscontentmeeting_id--diễn-biến-lấy-lại)
10. [Endpoint phụ](#10-endpoint-phụ)
11. [Cache](#11-cache)
12. [Mã lỗi](#12-mã-lỗi)

---

## 1. Luồng chính

```
Client                                   Server
  │ POST /v3/meetings/content (body đầy đủ)
  │ ───────────────────────────────────►  1. Cắt chủ đề + gán nhãn            → cache "đầu vào agent"
  │                                       2. Content agent                     → cache Diễn biến
  │                                       3. Lưu request làm request gần nhất của meeting_id
  │ ◄─────────────────────────────────── trả Diễn biến
  │                                       4. (chạy nền) Action agent  → cache Giao việc
  │                                                     Decision agent → cache Kết luận
  │
  │ GET /v3/meetings/tasks/{meeting_id}       ─►  có trong cache   → trả ngay (không gọi LLM)
  │ GET /v3/meetings/decisions/{meeting_id}   ─►  đang tính nền    → chờ lần tính đó rồi trả
  │                                               chưa có          → chạy riêng agent đó trên
  │                                                                  đầu vào đã cache, lưu, trả
  │                                               chưa gọi /content → 404
```

- Transcript chỉ gửi **một lần**, ở `POST /content`. Hai lời gọi sau chỉ cần `meeting_id`.
- **"Đầu vào agent"** gồm lượt nói, chủ đề, nhãn chủ đề, cùng `chair`, `meeting_date`, `attendees`,
  `tasks` của request. Nhờ đó Action agent và Decision agent chạy lại được mà không phải cắt chủ đề
  lại hay gửi lại transcript.
- `meeting_id` dùng ở GET là `meeting_id` trong response của `POST /content`. Nếu body dạng STT
  export không có `meeting_id` thì giá trị này là `"stt-export"`.
- Lỗi của bước chạy nền (bước 4) chỉ được ghi log, `POST /content` vẫn trả 200. Lần GET sau sẽ tự
  chạy lại agent đó.

## 2. Danh sách endpoint

**Luồng chính**

| Method | Path | Body | Trả về |
|---|---|---|---|
| POST | `/v3/meetings/content` | `AnalyzeV3Request` ([mục 3](#3-input-body-của-post-content)) | Diễn biến ([mục 6](#6-post-v3meetingscontent--diễn-biến)). Tính nền Giao việc và Kết luận |
| GET | `/v3/meetings/tasks/{meeting_id}` | không có | Giao việc ([mục 7](#7-get-v3meetingstasksmeeting_id--giao-việc)) |
| GET | `/v3/meetings/decisions/{meeting_id}` | không có | Kết luận ([mục 8](#8-get-v3meetingsdecisionsmeeting_id--kết-luận)) |
| GET | `/v3/meetings/content/{meeting_id}` | không có | Diễn biến, lấy lại ([mục 9](#9-get-v3meetingscontentmeeting_id--diễn-biến-lấy-lại)) |

**Endpoint phụ** ([mục 10](#10-endpoint-phụ))

| Method | Path | Mục đích |
|---|---|---|
| POST | `/v3/meetings/tasks` | Tính hoặc lấy Giao việc với body đầy đủ (ví dụ đổi danh sách `tasks`, hoặc `?refresh=true` để tính lại) |
| POST | `/v3/meetings/decisions` | Tương tự cho Kết luận |
| GET | `/health` | Kiểm tra dịch vụ còn sống |

**Query params của các POST**

| Param | Kiểu | Mặc định | Ý nghĩa |
|---|---|---|---|
| `refresh` | bool | `false` | Tính lại document của endpoint đó, vẫn dùng chủ đề và nhãn đã có |
| `refresh_base` | bool | `false` | Tính lại cả cắt chủ đề và gán nhãn. Document khác tính trên nền cũ hết dùng được và sẽ được tính lại khi được yêu cầu |

---

## 3. Input: body của `POST /content`

Body là `AnalyzeV3Request` (JSON). Ví dụ đầy đủ: `be/examples/post_content.request.json`. Các POST
phụ dùng cùng body này.

### 3.1 Trường gốc

| Trường | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `meeting_id` | string \| null | Không, nhưng **bắt buộc với dạng native** | Mã cuộc họp. Với dạng STT export, nếu thiếu thì dùng `"stt-export"`. Đi vào `analysis_key` |
| `meeting_date` | `"YYYY-MM-DD"` \| null | Không | Ngày họp. Dùng để quy hạn tương đối ("tuần sau", "cuối tháng") ra `due.date` và để tính `overdue` của việc cũ. Nếu thiếu thì hạn vẫn có `raw` và `kind` nhưng `date` có thể là null |
| `items` | array of object | **Có** | Các dòng transcript theo thứ tự thời gian. Xem [3.2](#32-items-các-dòng-transcript) |
| `attendees` | object \| null | Không | Danh sách người và đơn vị tham dự, dùng để định danh bên nhận việc. Xem [3.3](#33-attendees) |
| `chair` | object \| null | Không | Người chủ trì: `{"id": "P4", "full_name": "Phạm An"}`. `id` khớp một người trong `attendees.people` thì dùng tên trong danh sách, không thì dùng `full_name`. Tên này nếu khớp **duy nhất** một người nói trong transcript thì được quy về nhãn người nói đó và đưa vào prompt, giúp nhận ra lời giao việc và kết luận của chủ trì. Nếu null thì model tự suy ra. Gửi chuỗi thay cho object thì trả 422 |
| `tasks` | object \| null | Không | Danh sách việc cũ (backlog) cần báo cáo tiến độ. **Chỉ document `tasks` dùng.** Xem [3.4](#34-tasks-danh-sách-việc-cũ) |
| `source` | object \| null | Không | Nguồn transcript và tài liệu. Chỉ được chép vào `source` của response, không ảnh hưởng kết quả. Xem [3.5](#35-source) |

> Pydantic **bỏ qua mọi trường gốc không có trong bảng trên**. Ví dụ `metadata`, `transcript`,
> `full_text` của file STT export không tới được parser. Muốn có `meeting_id` thì đặt nó ở
> trường gốc của body.

### 3.2 `items`: các dòng transcript

Mỗi phần tử là một dòng (câu hoặc đoạn) do STT hoặc người nhập tạo ra. **Mỗi item là một đơn vị
trích dẫn**: mọi `segment_ids` trong output là `id` của item ở đây, giữ nguyên kiểu đã gửi
(chuỗi hoặc số).

Parser nhận **hai dạng** item và tự nhận diện: nếu item đầu tiên có trường `segment` hoặc
`speaker_name` thì cả mảng được đọc theo dạng **STT export**, ngược lại theo dạng **native**.
Không trộn hai dạng trong cùng một request.

#### 3.2.1 Dạng native

```json
{
  "id": "i002",
  "text": "Mục tiêu là tăng năng lực tiếp nhận tàu lớn. Về nguôn vốn, ...",
  "speaker": "Nguyễn Cường",
  "speaker_role": "presenter",
  "speaker_id": "P1",
  "start_ms": 10898,
  "end_ms": 20810,
  "point_id": null,
  "ref_id": null,
  "revision": 0,
  "review": {
    "text": "Mục tiêu là tăng năng lực tiếp nhận tàu lớn. Về nguồn vốn, ...",
    "speaker": null,
    "revision": 1
  }
}
```

| Trường | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `id` | string (không rỗng) | **Có** | Mã dòng. Dạng native **chỉ nhận chuỗi**. Có thể dùng `item_id` thay `id`. Nếu trùng mã thì item sau được đổi thành `<id>-1`, `<id>-2`… |
| `text` | string | Không (mặc định `""`) | Nội dung STT gốc. Item có nội dung hiệu lực rỗng (sau khi áp `review.text`) bị bỏ qua khi dựng lượt nói, nên không bao giờ được trích dẫn |
| `speaker` | string \| null | Không | Tên hoặc nhãn người nói. Đây là căn cứ chính để gộp lượt nói và để nhận diện chủ trì hoặc người giao việc. Tên được làm sạch (chuẩn hoá NFC và khoảng trắng) |
| `speaker_role` | string \| null | Không | Vai trò người nói: `chair` (chủ trì), `presenter` (trình bày), `delegate` (đại biểu). Nhận cả tiếng Việt có hoặc không dấu ("chủ trì", "chu tri"). Có thể dùng `role_inferred` thay thế. Hai dòng liền nhau khác vai trò thì không gộp thành một lượt |
| `speaker_id` | string \| null | Không | Mã người nói, dùng để điền `speaker_id` trong output (`source_segment_refs`, `turns`, `assigned_by_speaker_id`…). Nếu thiếu thì lấy phần tử đầu của `ref_id` |
| `start_ms` | int ≥ 0 \| null | Không | Thời điểm bắt đầu, tính bằng mili giây |
| `end_ms` | int ≥ 0 \| null | Không | Thời điểm kết thúc, tính bằng mili giây. Phải ≥ `start_ms`, nếu không thì trả 422 |
| `point_id` | string \| null | Không | Mã mục chương trình hoặc điểm thảo luận mà dòng thuộc về. Hai dòng liền nhau có `point_id` khác nhau thì không gộp thành một lượt |
| `ref_id` | string \| string[] \| null | Không | Mã tham chiếu, thường là mã người nói. Hai dòng liền nhau có phần tử đầu của `ref_id` khác nhau thì không gộp. Cũng là nguồn dự phòng cho `speaker_id` |
| `revision` | int ≥ 0 | Không (mặc định `0`) | Số phiên bản của dòng |
| `review` | object \| null | Không | Bản người duyệt sửa, được áp **đè lên** dòng gốc: |
| `review.text` | string \| null | | Nếu có thì dùng thay `text` cho mọi bước phân tích và trích dẫn (`source_segment_refs.text`, `turns.text`) |
| `review.speaker` | string \| null | | Nếu có thì dùng thay `speaker` |
| `review.revision` | int ≥ 0 | | Nếu có thì dùng thay `revision` |

Các trường khác có giá trị vô hướng (chuỗi, số, bool, null) được giữ lại làm metadata nhưng không
ảnh hưởng kết quả. Riêng `speaker_track`, nếu có, là kênh người nói và được ưu tiên hơn `speaker`
khi gộp lượt.

#### 3.2.2 Dạng STT export

Đây là dạng xuất từ hệ thống ghi âm (giống `inputs/recording_old.json`).

```json
{
  "id": 3,
  "segment": "Với cả anh Việt thì sang tuần này sẽ",
  "segment_html": "Với cả anh Việt thì sang tuần này sẽ",
  "speaker_id": "7eeb6971-97a2-46fb-983f-53ac7753a5c2",
  "speaker_name": "Phạm Hồng Sơn",
  "speaker_org_unit": "Thành uỷ HCMC",
  "start_time": 5.80221875,
  "end_time": 8.77221875,
  "point_id": "6432f8f2-db7f-410e-90bc-9708385e915e",
  "ref_id": ["dd99e490-7385-4bbf-ba75-26859c7280e9"],
  "suggested_speaker_ids": ["7eeb6971-97a2-46fb-983f-53ac7753a5c2"],
  "recording_id": null
}
```

| Trường | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `id` | int \| string (không rỗng) | **Có** | Mã dòng. **Giữ nguyên kiểu** trong output: gửi số thì `segment_ids` là số. Nếu trùng mã thì item sau được đổi thành `<id>-1`… |
| `segment` | string | Không (mặc định `""`) | Nội dung dòng (tương ứng `text` của dạng native). Được coi là bản đã hiệu lực, không có `review` |
| `segment_html` | string | Không | Bản HTML của `segment`. Bị bỏ qua |
| `speaker_name` | string \| null | Không | Tên người nói (tương ứng `speaker`), đồng thời là kênh người nói khi gộp lượt |
| `speaker_id` | string \| null | Không | Mã người nói, được điền vào `speaker_id` trong output. Nếu thiếu thì lấy phần tử đầu của `ref_id` |
| `speaker_org_unit` | string \| null | Không | Đơn vị của người nói. Lưu làm metadata |
| `start_time` | number ≥ 0 \| null | Không | Thời điểm bắt đầu, tính bằng **giây** (được đổi sang ms) |
| `end_time` | number ≥ 0 \| null | Không | Thời điểm kết thúc, tính bằng **giây**. Phải ≥ `start_time` |
| `point_id` | string \| null | Không | Như dạng native |
| `ref_id` | string \| string[] \| null | Không | Như dạng native |
| `recording_id` | string \| null | Không | Mã bản ghi âm. Lưu làm metadata |
| `suggested_speaker_ids` và các trường khác | bất kỳ | Không | Bị bỏ qua (giá trị vô hướng được giữ làm metadata) |

#### 3.2.3 Cách item được gộp thành lượt nói (`turn_id`)

Các item liền nhau được gộp vào **cùng một lượt nói** khi thoả **tất cả** điều kiện sau
(cấu hình ở `configs/default.json` → `turn_builder`):

1. Cùng kênh người nói (`speaker_track`, hoặc `speaker`/`speaker_name` đã áp review).
2. Cùng `speaker_role`.
3. Không có hai `point_id` khác nhau, và không có hai phần tử đầu của `ref_id` khác nhau.
4. Người nói có tên. Dòng không có người nói không bao giờ được gộp (`merge_unknown_speakers: false`).
5. Khoảng lặng giữa `end` của dòng trước và `start` của dòng sau ≤ **5000 ms** (`max_gap_ms`). Nếu thiếu mốc thời gian thì **không gộp** (`merge_when_timestamp_missing: false`).

Lượt nói có mã `TURN_000001`, `TURN_000002`… tăng dần theo thứ tự, chỉ tính các item có nội dung.
`turn_ids` trong output là các mã này. Lượt nói được trả đầy đủ trong `data.turns` của
`ContentDocument`.

#### 3.2.4 Ràng buộc và lỗi

- `items` phải là mảng các object. Sai kiểu thì trả 422.
- Dạng native thiếu `meeting_id` (hoặc là chuỗi rỗng) thì trả 422.
- `id` thiếu hoặc rỗng (dạng native: không phải chuỗi; dạng STT: không phải chuỗi hoặc số) thì trả 422.
- Thời gian âm, không phải số, `end < start`, hoặc `start_ms`/`end_ms` không phải số nguyên thì trả 422.
- `text`, `speaker`, `review.*` sai kiểu thì trả 422.

### 3.3 `attendees`

```json
{
  "people": [
    {"id": "P1", "full_name": "Nguyễn Cường", "position": "Chánh Văn phòng", "org_id": "O2"}
  ],
  "organizations": [
    {"id": "O2", "name": "Đảng ủy UBND Thành phố", "parent_id": "O1", "aliases": ["Đảng ủy ban"], "functions": ["xây dựng tờ trình"]},
    {"id": "O1", "name": "Thành ủy", "parent_id": null}
  ]
}
```

| Trường | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `people[]` | array | Không (mặc định `[]`) | Người tham dự |
| `people[].id` | string | Có | Mã người, nên dùng dạng `P*`. Trở thành `person_id` của bên nhận việc |
| `people[].full_name` | string | Có | Họ tên đầy đủ, dùng để khớp với người nói và người được nhắc tên |
| `people[].position` | string | Không (mặc định `""`) | Chức vụ |
| `people[].org_id` | string \| null | Không | Mã đơn vị của người đó (trỏ tới `organizations[].id`) |
| `organizations[]` | array | Không (mặc định `[]`) | Đơn vị tham dự hoặc có thể được giao việc |
| `organizations[].id` | string | Có | Mã đơn vị, nên dùng dạng `O*`. Trở thành `unit_id` |
| `organizations[].name` | string | Có | Tên đầy đủ |
| `organizations[].parent_id` | string \| null | Không (mặc định `null`) | Mã đơn vị cấp cha (trỏ tới `organizations[].id`). `null` nếu là đơn vị cấp 0 |
| `organizations[].aliases` | string[] | Không | Tên gọi tắt trong bản ghi ("Đảng ủy ban"), dùng để khớp lời giao việc |
| `organizations[].functions` | string[] | Không | Các mảng việc đơn vị phụ trách, dùng để gợi ý bên nhận việc |

Nếu không có `attendees`, bên nhận việc chỉ được quy về người nói trong bản ghi (thường thành
`target_type: "unknown"`). Danh sách sai dạng thì trả 422.

### 3.4 `tasks`: danh sách việc cũ

Đây là các việc đã giao **trước** cuộc họp và cần báo cáo tiến độ. Việc mới phát sinh trong cuộc họp
là **output**, không gửi ở đây.

```json
{
  "tasks": [
    {"id": "T1", "title": "Trình Ban Thường vụ tờ trình đề án", "owner": "O2",
     "support": [], "reporter": null, "due": "2026-01-31", "last_status": "in_progress", "source": ""}
  ]
}
```

| Trường | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `tasks[].id` | string | Có | Mã việc. Trở thành `task_id` của dòng việc cũ trong output và là `task_id` mà lời giao việc trong họp trỏ về |
| `tasks[].title` | string | Có | Tên việc |
| `tasks[].owner` | string | Có | Bên chủ trì: mã người (`P*`), mã đơn vị (`O*`) trong `attendees`, hoặc tên tự do |
| `tasks[].support` | string[] | Không | Các bên phối hợp (cùng quy ước như `owner`) |
| `tasks[].reporter` | string \| null | Không | Người hoặc đơn vị báo cáo |
| `tasks[].due` | `"YYYY-MM-DD"` \| null | Không | Hạn hiện tại. Trả về ở `progress.previous_due` |
| `tasks[].last_status` | `not_started` \| `in_progress` \| `done` \| `blocked` \| null | Không | Trạng thái gần nhất trước họp. Trả về ở `progress.previous_status` |
| `tasks[].source` | string | Không | Nguồn của việc (văn bản giao) |

Giá trị sai (ví dụ ngày sai định dạng, `last_status` lạ) thì trả 422. Nếu có `tasks`, Action
agent trích thêm tiến độ và gắn `task_id`/`relation` cho lời giao việc.

### 3.5 `source`

| Trường | Kiểu | Mô tả |
|---|---|---|
| `transcript_version_id` | string \| null | Mã phiên bản transcript ở hệ thống nguồn |
| `transcript_uri` | string \| null | URI của transcript |
| `document_uris` | string[] | URI các tài liệu kèm (tờ trình…) |

Response mang `source` của **chính request đó**. Nếu document lấy từ cache qua GET thì mang
`source` đã lưu lúc tính.

---

## 4. Output: khung chung của document

```json
{
  "schema_version": "1.0",
  "document_type": "meeting_content",
  "meeting_id": "MTG-DEMO-001",
  "artifact_revision": 1,
  "source": {"transcript_version_id": "v7", "transcript_uri": "s3://...", "document_uris": []},
  "generation": {
    "status": "complete",
    "generated_at": "2026-10-19T06:53:44+00:00",
    "coverage": {"is_complete": true, "processed_segment_count": 6, "total_segment_count": 6},
    "warnings": [],
    "confidence": null
  },
  "data": { }
}
```

| Trường | Kiểu | Mô tả |
|---|---|---|
| `schema_version` | string | Phiên bản schema document, hiện là `"1.0"` |
| `document_type` | `meeting_content` \| `meeting_tasks` \| `meeting_decisions` | Loại document |
| `meeting_id` | string | Mã cuộc họp: `meeting_id` của request, hoặc giá trị mặc định với dạng STT |
| `artifact_revision` | int | Số lần document này đã được tính trên bản phân tích, bắt đầu từ 1. Tăng sau mỗi lần `refresh` hoặc tính lại |
| `source` | object | Xem [3.5](#35-source) |
| `generation.status` | `complete` \| `partial` | `partial` khi có chủ đề mà agent vẫn lỗi sau mọi lần thử. Kết quả của chủ đề đó bị thiếu |
| `generation.generated_at` | string ISO 8601 (UTC) | Thời điểm tính document |
| `generation.coverage.is_complete` | bool | `true` nếu không có chủ đề nào lỗi |
| `generation.coverage.processed_segment_count` | int | Số **item** transcript thuộc các chủ đề đã tính xong |
| `generation.coverage.total_segment_count` | int | Tổng số item thuộc các chủ đề |
| `generation.warnings[]` | array | Mỗi chủ đề lỗi một phần tử: `code` (`"topic_failed"`), `topic_id`, `agent` (ví dụ `"decision_agent"`), `message` (lỗi) |
| `generation.confidence` | null | Dự phòng, hiện luôn là null |
| `data` | object | Nội dung riêng của từng document (mục 6, 7, 8) |

## 5. Kiểu dùng chung trong output

### 5.1 Mã định danh

| Mã | Dạng | Ý nghĩa |
|---|---|---|
| `segment_id` / `segment_ids` | kiểu `id` của item gửi lên (string hoặc int) | Item transcript được trích dẫn |
| `turn_id` / `turn_ids` | `TURN_000001` | Lượt nói (xem [3.2.3](#323-cách-item-được-gộp-thành-lượt-nói-turn_id)) |
| `topic_id` | `TOPIC_SEG_000000` | Chủ đề (đoạn sau khi cắt chủ đề), đánh số từ 0 |
| `task_id` | `task_<16 hex>` (việc mới) hoặc `id` của `tasks[]` (việc cũ) | Việc |
| `point_id` | `<topic_id>:<n>` | Ý thảo luận thứ n của chủ đề |

`task_id` của việc mới là sha256 của (meeting_id, lượt chốt, bên chính), nên ổn định qua các lần tính
lại khi lượt chốt không đổi. Kết luận được đánh số `id` từ 1 theo thứ tự trong cuộc họp.

### 5.2 `SegmentRef` (`source_segment_refs[]`)

| Trường | Kiểu | Mô tả |
|---|---|---|
| `segment_id` | string \| int | `id` gốc của item |
| `turn_id` | string | Lượt nói chứa item |
| `text` | string | Nguyên văn hiệu lực của item (đã áp `review.text`) |
| `speaker_id` | string \| null | `speaker_id` (hoặc `ref_id[0]`) của item |

### 5.3 `Due` (hạn)

| Trường | Kiểu | Mô tả |
|---|---|---|
| `raw` | string \| null | Nguyên văn hạn trong bản ghi ("trước ngày 30 tháng 9") |
| `date` | `"YYYY-MM-DD"` \| null | Ngày đã quy đổi (theo `meeting_date` nếu là hạn tương đối) |
| `kind` | `exact` \| `before` \| `end_of_period` \| `relative` \| `unknown` | Loại hạn: đúng ngày, trước ngày, cuối kỳ (tháng/quý/năm), tương đối, chưa rõ |

Nếu không có `raw` và `date` thì cả object `due` là `null`.

### 5.4 `AssignmentTarget` (bên nhận việc)

Có ba dạng, phân biệt bằng `target_type`:

```json
{"target_type": "unit",    "unit_id": "O2",   "unit_name": "Đảng ủy UBND Thành phố", "extensions": {"resolution": {}}}
{"target_type": "person",  "person_id": "P1", "person_name": "Nguyễn Cường",          "extensions": {"resolution": {}}}
{"target_type": "unknown", "name": "Sở Giao thông",                                   "extensions": {"resolution": {}}}
```

- `unit` / `person`: đã khớp với `attendees`. `unit_id`/`person_id` là mã trong `attendees` (null nếu agent biết loại nhưng không khớp được mã).
- `unknown`: chưa định danh được. `name` là cách gọi trong bản ghi.

`extensions.resolution` (null với bên lấy từ danh sách việc cũ):

| Trường | Kiểu | Mô tả |
|---|---|---|
| `mention` | string \| null | Cách gọi trong bản ghi |
| `role` | `lead` \| `support` \| `joint` | Chủ trì, phối hợp, hoặc cùng thực hiện |
| `flag` | `ambiguous` \| `missing` \| null | Nhiều ứng viên ngang nhau, hoặc không tìm thấy |
| `candidates[]` | array | Ứng viên: `{name, actor_type (person/organization/unknown), score, reason, ref_id}` |

---

## 6. `POST /v3/meetings/content` → Diễn biến

`document_type = "meeting_content"`. Đây là diễn biến cuộc họp theo chủ đề, kèm toàn bộ lượt nói để
hiển thị transcript.

- **Input**: body ở [mục 3](#3-input-body-của-post-content). Query `refresh`, `refresh_base`.
- **Output**: `ContentDocument`. Ví dụ đầy đủ: `be/examples/post_content.response.json`.
- **Tác dụng phụ**: lưu request làm request gần nhất của `meeting_id`, sau đó chạy nền Giao việc và Kết luận.

```json
"data": {
  "topics": [
    {
      "topic_id": "TOPIC_SEG_000000",
      "order": 1,
      "extracted": {
        "content": {
          "title": "Đề án phát triển Cảng Cái Mép thành cảng trung chuyển quốc tế",
          "summary": "Trình bày Tờ trình 1374 (mục tiêu, nguồn vốn), hỏi đáp về mốc báo cáo ..."
        },
        "span": {"segment_ids": ["i001", "i006"], "turn_ids": ["TURN_000001", "TURN_000005"]},
        "discussion_points": [
          {
            "point_id": "TOPIC_SEG_000000:2",
            "text": "Trần Bình hỏi mốc hoàn thành báo cáo đánh giá tác động môi trường; trả lời: trình trước ngày 30/9/2026.",
            "speakers": ["Trần Bình", "Nguyễn Cường"],
            "speaker_ids": ["P2", "P1"],
            "segment_ids": ["i003", "i004"],
            "turn_ids": ["TURN_000002", "TURN_000003"],
            "source_segment_refs": [
              {"segment_id": "i003", "turn_id": "TURN_000002", "text": "Tôi xin hỏi mốc hoàn thành ... là khi nào?", "speaker_id": "P2"},
              {"segment_id": "i004", "turn_id": "TURN_000003", "text": "Theo kế hoạch hiện tại, ... trước ngày 30 tháng 9 năm 2026.", "speaker_id": "P1"}
            ]
          }
        ]
      },
      "workflow": {"review_status": "pending", "confirmed_fields": [], "overrides": {}, "updated_at": null, "updated_by": null, "revision": 1},
      "extensions": {"segmentation_method": null, "boundary_score": null}
    }
  ],
  "turns": [
    {"turn_id": "TURN_000001", "speaker": "Nguyễn Cường", "speaker_id": "P1", "segment_ids": ["i001", "i002"],
     "text": "Tôi xin báo cáo Tờ trình 1374 ... Về nguồn vốn, đề án dự kiến kết hợp ngân sách và vốn doanh nghiệp."},
    {"turn_id": "TURN_000004", "speaker": "Lê Mai", "speaker_id": "P3", "segment_ids": ["i005"],
     "text": "Tôi đề nghị bổ sung phương án huy động vốn tư nhân ..."}
  ]
}
```

Trong ví dụ, `turns[0].text` đã dùng `review.text` của `i002` ("nguồn" thay vì "nguôn"), và
`turns[3].speaker` đã dùng `review.speaker` của `i005` ("Lê Mai" thay vì "Lê M.").

**`topics[]`**: các chủ đề theo thứ tự.

| Trường | Kiểu | Mô tả |
|---|---|---|
| `topic_id` | string | Mã chủ đề |
| `order` | int | Thứ tự, bắt đầu từ 1 |
| `extracted.content.title` | string | Tiêu đề chủ đề (do LLM gán nhãn) |
| `extracted.content.summary` | string | Tóm tắt chủ đề |
| `extracted.span.segment_ids` | `[first, last]` | Item đầu và item cuối của chủ đề |
| `extracted.span.turn_ids` | `[first, last]` | Lượt nói đầu và lượt nói cuối |
| `extracted.discussion_points[]` | array | Các ý thảo luận trong chủ đề (bảng dưới) |
| `workflow` | object | Trạng thái duyệt của người dùng, mặc định: `review_status: "pending"`, `confirmed_fields: []`, `overrides: {}`, `updated_at/updated_by: null`, `revision: 1` |
| `extensions.segmentation_method` | string \| null | Phương pháp cắt chủ đề |
| `extensions.boundary_score` | float \| null | Điểm ranh giới chủ đề |

**`discussion_points[]`**

| Trường | Kiểu | Mô tả |
|---|---|---|
| `point_id` | string | `<topic_id>:<n>` |
| `text` | string | Nội dung ý thảo luận |
| `speakers` | string[] | Tên người nêu ý |
| `speaker_ids` | (string \| null)[] | `speaker_ids[i]` là mã của `speakers[i]` (null nếu transcript không có mã) |
| `segment_ids` | (string \| int)[] | Item làm bằng chứng |
| `turn_ids` | string[] | Lượt nói chứa các item đó |
| `source_segment_refs` | SegmentRef[] | Nguyên văn từng item (xem [5.2](#52-segmentref-source_segment_refs)) |

**`turns[]`**: toàn bộ lượt nói của transcript.

| Trường | Kiểu | Mô tả |
|---|---|---|
| `turn_id` | string | `TURN_000001`… |
| `speaker` | string \| null | Người nói (đã làm sạch, đã áp `review.speaker`) |
| `speaker_id` | string \| null | `speaker_id` của item đầu trong lượt |
| `segment_ids` | (string \| int)[] | Các item thuộc lượt, theo thứ tự |
| `text` | string | Nội dung lượt: các item nối nhau bằng một dấu cách |

## 7. `GET /v3/meetings/tasks/{meeting_id}` → Giao việc

`document_type = "meeting_tasks"`.

- **Input**: path param `meeting_id`, là `meeting_id` trong response của `POST /content`. Không có body.
- **Output**: `TasksDocument`. Ví dụ đầy đủ: `be/examples/get_tasks.response.json`.
- **Cách lấy**: có trong cache thì trả ngay; đang tính nền thì chờ; chưa có thì chạy Action agent trên
  đầu vào đã cache (dùng `attendees` và `tasks` của request `/content`). Cuộc họp chưa gọi
  `POST /content` thì trả **404** (`be/examples/get_tasks.response_404.json`).

`data.tasks[]` gồm **việc giao mới** (theo thứ tự lượt nói), rồi tới **việc cũ** trong `tasks` của
request (theo thứ tự danh sách). Mọi lời giao việc trong họp về chính một việc cũ (làm tiếp, giao
lại, đổi hạn) được **gộp vào dòng của việc cũ đó**, không thành dòng riêng.

### 7.1 Cấu trúc một dòng việc (`TaskOut`)

Ví dụ một việc mới:

```json
{
  "task_id": "task_8771a22a2a3621dd",
  "source_uri": null,
  "extracted": {
    "content": {"title": "Hoàn thiện báo cáo đánh giá tác động môi trường và gửi lại ban thư ký.",
                "description": "Hoàn thiện báo cáo đánh giá tác động môi trường và gửi lại ban thư ký."},
    "assignment": {
      "primary": {
        "target_type": "unit", "unit_id": "O2", "unit_name": "Sở Giao thông vận tải",
        "extensions": {"resolution": {
          "mention": "Sở Giao thông", "role": "lead", "flag": null,
          "candidates": [{"name": "Sở Giao thông vận tải", "actor_type": "organization", "score": 1.0,
                          "reason": "khớp tên gọi tắt của đơn vị", "ref_id": "O2"}]
        }}
      },
      "collaborators": [],
      "assigned_by_speaker_id": "P4"
    },
    "due": {"raw": "trước ngày 30 tháng 9 năm 2026", "date": "2026-09-30", "kind": "before"},
    "priority": null,
    "references": {
      "segment_ids": ["i006"], "confidence": null,
      "extensions": {"source_event_id": null, "evidence_ids": ["TURN_000005"],
                     "source_segment_refs": [{"segment_id": "i006", "turn_id": "TURN_000005",
                                              "text": "Tôi giao Sở Giao thông chủ trì hoàn thiện báo cáo ...", "speaker_id": "P4"}]}
    },
    "progress": null
  }
}
```

Ví dụ phần `progress` của một việc cũ (`T1`) được báo cáo trong họp:

```json
"progress": {
  "previous_status": "in_progress", "status": "in_progress", "previous_due": "2026-09-30",
  "status_conflict": false, "uncertain": false, "overdue": false,
  "summary": "Đã trình bày Tờ trình 1374 tại phiên họp; hồ sơ tiếp tục hoàn thiện.",
  "blockers": [], "directive": "", "deadline_extended": false,
  "assignments": []
}
```

Bằng chứng của `T1` (`i001`, `i002` ở `TURN_000001`) nằm ở `extracted.references` của dòng việc.
Việc cũ `T2` không được nhắc trong họp: `progress.status = "not_reported"`, `references.segment_ids = []`,
`progress.overdue = true`.

Một dòng việc chỉ có `task_id`, `source_uri` và `extracted`.

| Trường | Kiểu | Mô tả |
|---|---|---|
| `task_id` | string | Việc mới: `task_<16 hex>`. Việc cũ: `id` của việc trong request |
| `source_uri` | null | Dự phòng |
| `extracted.content.title` | string | Việc mới: nội dung việc phải làm. Việc cũ: `title` của danh sách |
| `extracted.content.description` | string | Việc mới: như `title`. Việc cũ: tóm tắt của cập nhật quyết định, nếu không có thì lấy `title` |
| `extracted.assignment.primary` | AssignmentTarget \| null | Bên chính (chủ trì). Việc cũ: lấy `owner`, hoặc bên mới nếu có lời giao lại (`reassign`) |
| `extracted.assignment.collaborators` | AssignmentTarget[] | Các bên phối hợp hoặc cùng thực hiện |
| `extracted.assignment.assigned_by_speaker_id` | string \| null | `speaker_id` của người giao (người nói ở lượt chốt) |
| `extracted.due` | Due \| null | Hạn. Việc cũ: hạn mới (đổi hạn hoặc cập nhật), nếu không có thì giữ hạn cũ (`kind: "exact"`). Là null khi cuộc họp bỏ hạn |
| `extracted.priority` | null | Dự phòng |
| `extracted.references.segment_ids` | (string \| int)[] | Mọi item làm bằng chứng của việc (việc cũ: mọi item báo cáo tiến độ và mọi lời giao việc về nó; rỗng khi không được nhắc) |
| `extracted.references.confidence` | null | Dự phòng |
| `extracted.references.extensions.evidence_ids` | string[] | Các `turn_id` bằng chứng |
| `extracted.references.extensions.source_segment_refs` | SegmentRef[] | Nguyên văn từng item |
| `extracted.references.extensions.source_event_id` | null | Dự phòng |
| `extracted.progress` | TaskProgress \| null | **Chỉ có ở việc cũ**, việc mới là null. Xem [7.2](#72-progress-chỉ-việc-cũ) |

### 7.2 `progress` (chỉ việc cũ)

| Trường | Kiểu | Mô tả |
|---|---|---|
| `previous_status` | string \| null | `last_status` của request |
| `status` | `done` \| `in_progress` \| `cancelled` \| `mentioned` \| `not_reported` | Trạng thái sau họp: đã hoàn thành; đang thực hiện (cả vướng, làm lại, gia hạn); huỷ (cả hoãn, tạm dừng); chỉ được nhắc tới; không được báo cáo |
| `previous_due` | string \| null | `due` của request |
| `status_conflict` | bool | Có báo cáo "done" đã xác nhận đi cùng một cập nhật khác cũng đã xác nhận |
| `uncertain` | bool | Cập nhật quyết định chưa được xác nhận |
| `overdue` | bool | Hạn cũ đã qua so với `meeting_date` mà việc chưa xong |
| `summary` | string | Tóm tắt của cập nhật quyết định (lượt chỉ đạo/kết luận thắng lượt báo cáo, cùng loại thì lượt muộn hơn thắng) |
| `blockers` | string[] | Vướng mắc |
| `directive` | string | Chỉ đạo của chủ trì |
| `deadline_extended` | bool | Gia hạn: việc chưa xong, được thêm thời gian mà chưa có hạn mới (hạn vẫn là hạn cũ để người dùng sửa) |
| `assignments[]` | array | Các lời giao việc trong họp về việc này, theo thứ tự lượt nói (bảng dưới) |

**`assignments[]`**

| Trường | Kiểu | Mô tả |
|---|---|---|
| `topic_id` | string | Chủ đề |
| `relation` | `follow_up` \| `reassign` \| `reschedule` | Làm lại, bổ sung hoặc làm tiếp; giao cho bên khác; đổi hạn |
| `text` | string | Việc phải làm theo lời giao |
| `primary`, `collaborators` | AssignmentTarget | Bên nhận |
| `due` | Due \| null | Hạn trong lời giao |
| `status` | string \| null | Trạng thái agent khai: `assigned` (được giao), `self_committed` (tự nhận), `proposed` (đề xuất), `reported` (báo cáo), `unknown` |
| `verification` | string \| null | Đường vào kết quả: `rule` (luật, không cần Verifier), `consensus` (Verifier và agent đồng thuận), `verifier` (hết vòng, theo Verifier), `debate`, `fallback` (giữ theo luật an toàn) |
| `confirm_turn_id` | string \| null | Lượt chốt |
| `segment_ids`, `turn_ids` | | Bằng chứng |

## 8. `GET /v3/meetings/decisions/{meeting_id}` → Kết luận

`document_type = "meeting_decisions"`.

- **Input**: path param `meeting_id`. Không có body.
- **Output**: `DecisionsDocument`. Ví dụ đầy đủ: `be/examples/get_decisions.response.json`.
- **Cách lấy**: như [mục 7](#7-get-v3meetingstasksmeeting_id--giao-việc), nhưng chạy Decision agent. Không dùng `tasks` của request.

```json
"data": {
  "items": [
    {
      "id": 1,
      "content": "Thống nhất mốc trình báo cáo đánh giá tác động môi trường của đề án trước ngày 30/9/2026.",
      "segment_ids": ["i006"], "original_segment_ids": ["i006"], "turn_ids": ["TURN_000005"]
    }
  ]
}
```

**`items[]`**: các kết luận theo thứ tự.

| Trường | Kiểu | Mô tả |
|---|---|---|
| `id` | int | Số thứ tự, bắt đầu từ 1 |
| `content` | string | Nội dung kết luận |
| `segment_ids` | (string \| int)[] | Item làm bằng chứng (người duyệt có thể sửa) |
| `original_segment_ids` | (string \| int)[] | Trích dẫn gốc do hệ thống tạo, giữ nguyên khi người duyệt sửa `segment_ids` |
| `turn_ids` | string[] | Lượt nói chứa các item |

## 9. `GET /v3/meetings/content/{meeting_id}` → Diễn biến (lấy lại)

Trả lại Diễn biến của request `POST /content` gần nhất, ví dụ khi FE tải lại trang. Response giống
hệt response của `POST /content`. Cách lấy và lỗi như [mục 7](#7-get-v3meetingstasksmeeting_id--giao-việc).

**Lưu ý chung cho các GET theo `meeting_id`:**
- Mỗi `meeting_id` chỉ giữ **một** request: request `POST /content` gần nhất. Gọi `/content` lại với
  transcript khác (revision mới) thì các GET sau đó trả kết quả của transcript mới.
- Chỉ `POST /content` cập nhật request đã lưu. Các POST phụ thì không.
- Các body STT export không có `meeting_id` đều dùng chung `"stt-export"` nên đè lên nhau. Hãy luôn
  gửi `meeting_id` ở gốc body.
- `source` trong response là `source` của request `/content` đã lưu.
- GET không có `refresh`. Muốn tính lại thì dùng POST phụ với `?refresh=true`, hoặc gọi lại
  `POST /content?refresh_base=true`.

## 10. Endpoint phụ

### 10.1 `POST /v3/meetings/tasks`, `POST /v3/meetings/decisions`

Nhận **body đầy đủ** như `POST /content` và trả cùng document như GET tương ứng ở mục 7 và 8. Dùng khi:
- cần tính lại: `?refresh=true` (chỉ document đó) hoặc `?refresh_base=true`;
- cần kết quả với input khác request `/content` đã lưu, ví dụ một danh sách `tasks` khác.

Body trùng hoàn toàn với request `/content` thì lấy từ cache (xem [mục 11](#11-cache)). Các POST này không
cập nhật request đã lưu theo `meeting_id`.

### 10.2 `GET /health`

Luôn trả `200 {"status": "ok"}`, dùng cho load balancer hoặc giám sát.

## 11. Cache

Cache nằm trên Redis (`V3_CACHE=redis`, mặc định), TTL 7 ngày (`V3_CACHE_TTL_SECONDS`). Mọi khoá có
fingerprint của code, cấu hình và model, nên đổi prompt hoặc model thì cache cũ tự hết hiệu lực.

| Mục | Khoá | Nội dung |
|---|---|---|
| Request gần nhất của cuộc họp | `meeting_id` | Body của `POST /content` gần nhất |
| Nền (đầu vào agent) | `analysis_key` = hash(`meeting_id`, `items`) | Lượt nói, chủ đề, nhãn |
| Document | `analysis_key` + `<document>@<hash>` | Kết quả của một document |

Hash trong khoá document gồm các trường request mà document đó phụ thuộc. `source` không đi vào
khoá nào.

| Document | Trường đi vào khoá |
|---|---|
| `content` | `chair`, `meeting_date`, `attendees` |
| `decisions` | `chair`, `meeting_date`, `attendees` |
| `tasks` | `chair`, `meeting_date`, `attendees`, `tasks` |

Quy tắc:
- Mỗi mục chỉ có **một** lần tính chạy tại một thời điểm. Request trùng sẽ chờ lần tính đang chạy
  (kể cả lần chạy nền sau `POST /content`).
- Document có chủ đề lỗi (`generation.status = "partial"`) vẫn được trả về, nhưng không được dùng
  lại: lần gọi sau sẽ tính lại.
- `refresh=true` mà lần tính lại có chủ đề lỗi thì **giữ bản đầy đủ cũ** và trả 502.
- `artifact_revision` tăng sau mỗi lần tính lại document; `generation.generated_at` cho biết lúc tính.
  FE nên bỏ response có `generated_at` cũ hơn bản đang hiển thị.

## 12. Mã lỗi

Mọi lỗi có body `{"detail": "<thông điệp>"}`.

| Mã | Khi nào |
|---|---|
| 422 | Body sai schema; transcript không hợp lệ (xem [3.2.4](#324-ràng-buộc-và-lỗi)); `attendees` hoặc `tasks` sai dạng; `chair` không phải object `{id, full_name}` |
| 404 | GET theo `meeting_id`: cuộc họp chưa gọi `POST /content` (hoặc request đã lưu hết hạn) |
| 409 | Bản phân tích đang được tính lại toàn bộ liên tục bởi request khác (`refresh_base` song song). Thử lại sau |
| 502 | LLM hoặc embedding lỗi; hoặc `refresh` một document mà có chủ đề lỗi (bản cũ được giữ). Gateway trả 401/402/403 (sai key, hết tiền) thì cả lượt chạy dừng và trả 502, không trả kết quả thiếu chủ đề |
| 504 | LLM hoặc embedding quá thời gian |
| 503 | Không dùng được cache (Redis) |

Lỗi của bước chạy nền sau `POST /content` **không** làm `/content` lỗi. Nếu agent vẫn lỗi khi GET
tính lại, GET sẽ trả 502 hoặc 504.
