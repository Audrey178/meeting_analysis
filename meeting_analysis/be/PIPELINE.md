# Luồng xử lý transcript end-to-end của `be/`

Tài liệu mô tả đường đi của một transcript từ lúc client gọi `POST /meetings/analyze`
đến khi nhận JSON kết quả (Diễn biến họp / Giao việc / Kết luận họp).

```
HTTP POST /meetings/analyze
  │  routers/meetings.py        (validate AnalyzeRequest, tiêm adapter, map lỗi -> HTTP)
  ▼
services/pipeline.py: run_meeting_analysis_pipeline
  │
  ├─ parse_transcript_payload        payload dict -> (meeting_id, revision_id, RawTranscriptItem[])
  ├─ stage01 resolve_effective_transcript   dòng thô -> dòng hiệu lực (chồng bản sửa của người duyệt)
  ├─ stage02 build_evidence_items           dòng hiệu lực -> EvidenceItem có mã ổn định
  ├─ stage03 build_speaker_turns            evidence -> SpeakerTurn (gộp dòng liên tiếp cùng người nói)
  ├─ Cắt chủ đề trên SpeakerTurn            DialSTART | DialTreeSeg | TreeSeg -> TopicSegment[]
  ├─ stage07 label_topics                   mỗi đoạn -> TopicLabel (title + summary), gọi LLM
  ├─ LangGraph (src/agentic/graph.py)       Content / Action / Decision / Evidence-Check / Debate+Judge
  └─ Serialize                              MeetingState cuối -> dict theo AnalyzeResponse
```

Không có stage04–06 và stage08 trong luồng API: cắt chủ đề chạy thẳng trên lượt nói
(stage03), bỏ bước dựng atom để tiết kiệm chi phí. Đánh đổi: ranh giới chủ đề không
bao giờ rơi vào giữa một lượt nói dài.

---

## 1. Khởi động ứng dụng (`main.py`)

Chạy: `uvicorn --app-dir be main:app`

1. Thêm `be/`, `experiments/treeseg_turn_level/` và thư mục gốc repo vào `sys.path`
   (mọi file trong `be/` lặp lại khối này để import được `src.*` và `treeseg`).
2. `load_dotenv()` nạp `.env`.
3. `lifespan` chạy **một lần** khi khởi động, dựng các thành phần nặng dùng chung cho mọi request:
   - `app.state.embedding_adapter` ← `build_embedding_adapter()` (theo `EMBEDDING_BACKEND`).
   - `app.state.topic_segmenter` ← `build_topic_segmenter()` (theo `TOPIC_SEGMENTER`, nạp checkpoint DialSTART).
4. Gắn CORS (`ALLOWED_ORIGINS`) và hai router: `health` (`GET /health`) và `meetings`.

Các adapter LLM (gán nhãn chủ đề, agent phía sau) **không** dựng lúc khởi động mà
tạo mới cho mỗi request trong `services/dependencies.py`.

## 2. Tầng HTTP (`routers/meetings.py`, `schemas.py`)

`POST /meetings/analyze` nhận `AnalyzeRequest`:

| Trường | Kiểu | Ghi chú |
|---|---|---|
| `meeting_id` | `str \| None` | Tùy chọn; bắt buộc chỉ với dạng "native" |
| `revision_id` | `str \| None` | Tùy chọn; như trên |
| `items` | `list[dict]` | Các dòng transcript, để lỏng và chuyển nguyên cho parser |

FastAPI tiêm 4 dependency:

| Dependency | Nguồn | Vòng đời |
|---|---|---|
| `get_embedding_adapter` | `app.state.embedding_adapter` | dùng chung |
| `get_topic_segmenter` | `app.state.topic_segmenter` (None = TreeSeg) | dùng chung |
| `get_topic_label_adapter` | `StructuredLLMTopicLabeler(OpenAIChatJSONAdapter())` | mỗi request |
| `get_downstream_llm_adapters` | tuple 4 phần tử, **cùng một** `OpenAIChatJSONAdapter` | mỗi request |

Endpoint gọi `run_meeting_analysis_pipeline(request.model_dump(), ...)` (hàm đồng bộ,
chạy lâu vì gọi LLM nhiều lần) và ánh xạ lỗi:

| Ngoại lệ | Mã HTTP |
|---|---|
| `LLMUpstreamError` với `timed_out=True` | 504 |
| `LLMUpstreamError` khác | 502 |
| `ValueError` (transcript không hợp lệ) | 422 |

## 3. Pipeline (`services/pipeline.py`)

### 3.1 Parse payload — `src/utils/adapters.py::parse_transcript_payload`

Nhận diện ba dạng đầu vào:

- **STT export**: có `items` và item có `segment`/`speaker_name` (vd. `inputs/recording_old.json`).
  Thiếu mã thì tự đặt `meeting_id="stt-export"`, `revision_id="export-0"` (hoặc `edited-<last_edited>`).
- **Native**: có `items`, bắt buộc `meeting_id` + `revision_id`.
- **Legacy**: có `meeting` + `turns`.

Kết quả: `(meeting_id, revision_id, tuple[RawTranscriptItem])`; item_id phải duy nhất.
Adapter chỉ sao chép giá trị, không chuẩn hóa text.

Config đọc từ `configs/default.json` (`load_config`), dùng `turn_builder` và `topic_labeler`.

### 3.2 Stage01 — dòng hiệu lực (`stage01_effective_transcript.py`)

Chồng các chỉnh sửa theo trường (text, người nói) của người duyệt lên bản ASR gốc,
ghi nguồn gốc bằng `FieldProvenance`. Chuẩn hóa vai trò người nói về `chair` /
`presenter` / `delegate`, nhận diện "người nói không xác định". Sau stage này không
bước nào đọc lại dòng thô.

### 3.3 Stage02 — bằng chứng (`stage02_evidence.py`)

"Đóng băng" dòng hiệu lực thành `EvidenceItem`:
- Mã evidence chỉ phụ thuộc `(meeting_id, item_id)`, nên ổn định qua các lần chạy.
- Nội dung chuẩn hóa (NFC, gộp khoảng trắng) được băm riêng thành `content_hash`;
  bản gốc giữ ở `text_exact`.
- Không stage nào sau đó được tạo, sửa hay đổi thứ tự bằng chứng.

### 3.4 Stage03 — lượt nói (`stage03_speaker_turns.py`)

Gộp các evidence liên tiếp thành `SpeakerTurn`, cố ý thận trọng. Chỉ gộp khi:
cùng speaker track, cùng vai trò, không khác `point_id`/`ref_ids`, người nói đã xác
định (trừ khi `merge_unknown_speakers`), và khoảng cách ≤ `max_gap_ms` (mặc định
5000 ms; thiếu timestamp thì theo `merge_when_timestamp_missing`, mặc định không gộp).

`turn_id` của lượt nói là thứ các agent phía sau trích dẫn làm `evidence_ids`.

### 3.5 Cắt chủ đề

Chọn bộ cắt theo kiểu của `topic_segmenter` (do `TOPIC_SEGMENTER` quyết định lúc khởi động):

| `TOPIC_SEGMENTER` | Bộ cắt | Tín hiệu dùng | Code |
|---|---|---|---|
| `dialstart` (mặc định) | `DialStartSegmenter` | điểm mạch lạc từ model DialSTART đã train | `experiments/006_dialstart/dialstart_segmenter.py` |
| `dialtreeseg` | `DialTreeSegSegmenter` | DialSTART (có tách không) + cây TreeSeg trên embedding (tách ở đâu) | `experiments/007_dialtreeseg/dialtreeseg_segmenter.py`, `methods.py` |
| `treeseg` | `segment_turns_with_treeseg` | chỉ embedding (không cần train) | `experiments/treeseg_turn_level/treeseg.py` |

**Quy ước chung cho cả ba:**

- Đầu vào là dãy `n` lượt nói của stage03. Lượt nói là đơn vị nhỏ nhất, nên ranh giới
  không bao giờ nằm giữa một lượt.
- **Khe** `g` là chỗ nối giữa lượt `g` và `g+1` (có `n-1` khe). **Ranh giới** `b` nghĩa là
  đoạn mới bắt đầu ở lượt `b`, tức khe `b-1`.
- Văn bản đưa vào model/embedding là `text_exact` của lượt, **không** kèm tên người nói.
  Còn độ dài dùng cho mọi ràng buộc ký tự (`item_chars`) được đo trên dòng
  `"speaker: text" + 1`, đúng thứ sẽ vào prompt LLM phía sau.
- Kết quả cuối được đóng gói bằng `boundaries_to_topic_segments` thành `TopicSegment`
  với mã `TOPIC_SEG_000000`, `TOPIC_SEG_000001`, …; `text` là các dòng `"speaker: text"`;
  `start_ms`/`end_ms` thực chất là **chỉ số lượt** (nửa mở), không phải mili-giây.
- Cả ba đều có **trần 35 000 ký tự/đoạn**, là ràng buộc cứng để không agent nào phía sau
  nhận prompt quá lớn. Nó chỉ không tách được khi một lượt nói đơn lẻ đã dài hơn trần.

#### 3.5.1 DialSTART (`TOPIC_SEGMENTER=dialstart`, mặc định)

Model `SegModel` có hai nhánh, cùng backbone `NlpHUST/vibert4news-base-cased`, checkpoint
`experiments/006_dialstart/model_vn3/best.pt` (hoặc `DIALSTART_CHECKPOINT`). Model được
nạp một lần lúc khởi động (~1 GB), chạy trên GPU nếu có.

```
lượt nói ─► (1) chấm điểm khe ─► (2) làm mượt ─► (3) depth score ─► (4) chọn ranh giới
                                                                     a. ngưỡng depth
                                                                     b. bỏ đoạn vụn
                                                                     c. gộp đoạn giống nhau
                                                                     d. tách đoạn quá dài
```

1. **Chấm điểm mạch lạc cho từng khe** (`score_gaps_with_embeddings`):
   - *Nhánh topic*: mã hóa từng lượt (tối đa 256 token) **một lần**, lấy pooled output làm
     embedding chủ đề. Với khe `g`: trung bình embedding của `window_size=2` lượt bên trái
     so với 2 lượt bên phải → `cos(trái, phải)`.
   - *Nhánh coherence (NSP)*: cặp (ngữ cảnh trái = 2 lượt nối bằng `[SEP]`, giữ 256 token
     cuối, sát khe; lượt `g+1`, tối đa 256 token) → logit "liền mạch".
   - `score(g) = sigmoid(NSP_logit + cos)`. **Điểm thấp = dễ là ranh giới.**
   - Không cắt lượt còn 128 ký tự như lúc eval cũ, mà mã hóa giống lúc train.
2. **Làm mượt** (`smooth_scores`): trung bình trượt cửa sổ 3 khe (`_DIALSTART_SMOOTH_WINDOW`), để lấp các chỗ trũng giả
   do câu xen ngang ("Vâng", "Mời anh…"). Trên 12 cuộc họp Quốc hội có nhãn, bỏ bước này
   làm F1 giảm từ 0.418 xuống 0.297.
3. **Depth score** (`depth_scores`, kiểu TextTiling): với mỗi khe, leo sang trái và sang phải
   tới đỉnh gần nhất, `depth = ½·(đỉnh_trái + đỉnh_phải − 2·score)`. Khe càng "lõm" càng sâu.
4. **Chọn ranh giới** (`select_boundaries`), lần lượt 4 bước:

   | Bước | Hàm | Tham số (`be/services/pipeline.py`) | Làm gì |
   |---|---|---|---|
   | a | `_threshold_edges` | `threshold_std=1.0`, `min_size=4` | Giữ khe có depth > `mean + 1·std`. Duyệt depth giảm dần, bỏ khe tạo ra đoạn < 4 lượt |
   | b | `_drop_short_segments` | `min_segment_chars=_dialstart_min_segment_chars(...)` = tổng ký tự / 15, kẹp [1500, 10000] | Lặp: đoạn ngắn nhất (theo ký tự) còn dưới sàn thì xóa mép có depth thấp hơn, tức gộp vào đoạn bên cạnh |
   | c | `_merge_similar_segments` | `merge_threshold=None` (tắt) | Lặp: gộp cặp đoạn kề có cosine (embedding chủ đề trung bình) cao nhất nếu ≥ ngưỡng **và** đoạn gộp không vượt trần ký tự. Chữa trường hợp một chủ đề bị cắt đôi bởi đoạn xen ngang (+0.025 F1 trên Quốc hội) |
   | d | `_split_long_segments` | `max_segment_chars=35000` | Đoạn > 35 000 ký tự được tách tại khe depth cao nhất bên trong (ưu tiên khe vẫn giữ ≥ 8 lượt mỗi bên), lặp đến khi vừa trần |

Tham số tune chung trên gold thật đã duyệt (`experiments/007_dialtreeseg/gold`, 3 cuộc họp) và
`eval/synthetic` (30 transcript): thật 0.637, synth 0.686 (điểm = (F1@2k + F1@5k + 2 − 2·Pk) / 4; bộ
cũ: 0.392 / 0.336). Synth tương quan yếu với thật (Spearman 0.56) nên ưu tiên gold thật. Muốn nhiều
đoạn hơn thì tăng `_DIALSTART_MIN_SEGMENT_FRACTION` hoặc giảm `_DIALSTART_THRESHOLD_STD`.
DialSTART **không** dùng `embedding_adapter` của backend.

#### 3.5.2 DialTreeSeg (`TOPIC_SEGMENTER=dialtreeseg`)

Kết hợp hai tín hiệu: **TreeSeg đề xuất tách ở đâu, DialSTART quyết định có tách hay
không**. `DialTreeSegSegmenter` bọc chính instance `DialStartSegmenter` ở trên. Phương pháp
và mọi tham số đọc từ `experiments/007_dialtreeseg/config.json`; muốn đổi thì sửa file đó
rồi khởi động lại backend. Hiện `backend.method = "I3+I5"`.

```
lượt nói ─┬─► DialSTART: điểm khe ─► logit ─► depth ─► depth_z ─► ứng viên ranh giới
          │                                                          │
          └─► embedding backend (lượt + 5 lượt trước) ───────────────┤
                                                                     ▼
                                               cây chia dần TreeSeg, chỉ tách tại ứng viên,
                                               dừng khi depth_z ≤ k_stop
                                                                     ▼
                                               tách tiếp đoạn > 35 000 ký tự
```

1. **Đặc trưng** (`predict_boundaries`):
   - Gọi `dialstart.score_gaps_with_embeddings` để lấy điểm khe (bước 1 của 3.5.1).
   - Đổi điểm sang thang **logit** (`dialstart_score_scale="logit"`, tránh bão hòa gần 1.0),
     làm mượt với `dialstart_smooth_window=1` (tức không làm mượt), tính depth rồi
     **chuẩn hóa z** trên toàn cuộc họp → `depth_z`.
   - Embedding backend (`embedding_adapter`, dùng `embed_many` nếu có để gom batch) của
     mỗi lượt kèm `bge_context_turns=5` lượt đứng trước.
2. **Ứng viên ranh giới** (`candidate_boundaries`): khe là cực đại cục bộ của `depth_z` và
   `depth_z > k_cand = 0.0`. Ngưỡng này cố tình thấp để lấy dư ứng viên; với dải bằng nhau
   chỉ lấy khe cuối dải.
3. **Cây chia dần có cổng** (`gated_divisive_split`), bắt đầu từ cả cuộc họp `[0, n)`:
   - Trong nút `[lo, hi)`, xét các ứng viên nằm bên trong mà hai phía đều ≥ `min_chars = 2000` ký tự.
   - TreeSeg chọn ứng viên có tổng bình phương sai trong cụm (SS) của embedding hai phía
     nhỏ nhất (`shortlist=1`).
   - Chỉ tách nếu `depth_z` tại điểm đó > `k_stop = 1.0`; nếu không, nút dừng lại thành một đoạn.
   - Tách được thì đẩy hai nút con vào hàng đợi và lặp lại.
4. **Tách đoạn quá dài** (`split_oversized_segments`, `backend.max_segment_chars = 35000`):
   đoạn vượt trần được tách tại ứng viên DialSTART có SS hai phía nhỏ nhất. Hết ứng viên
   hợp lệ thì xét mọi ranh giới lượt, hai phía vẫn phải ≥ 2000 ký tự.

Trần ký tự ở đây do `DialTreeSegSegmenter` tự áp từ config; `be/services/pipeline.py` chỉ
truyền `item_chars` và không truyền `_TREESEG_MAX_SEGMENT_CHARS`.

Các phương pháp khác trong `methods.py` có thể chọn qua `backend.method`: `T` (TreeSeg
riêng), `D` (DialSTART riêng theo `depth_z > k_stop`), `I7` (TreeSeg rồi dời ranh giới về
đỉnh depth trong ±`snap_chars`), `I4` (như I3+I5 nhưng lá là các đơn vị cắt tại mọi ứng
viên), `I3+SL` (như I3+I5 nhưng DialSTART chọn trong `shortlist` vị trí SS tốt nhất).

#### 3.5.3 TreeSeg (`TOPIC_SEGMENTER=treeseg`)

Thuật toán không cần train (Gklezakos et al., 2024): phân cụm chia dần trên embedding,
dựng cây phân hoạch nhị phân rồi cắt cây theo ngưỡng gain. Không nạp DialSTART.

```
lượt nói ─► (1) embedding kèm ngữ cảnh ─► (2) dựng cây đầy đủ ─► (3) cắt cây theo gain + trần ký tự
```

1. **Embedding** (`embed_items_with_preceding_context`): khối của lượt `t` là
   `texts[t-5 .. t]` (`width=5`) nối bằng dấu cách, gọi `embedding_adapter.embed` một lần
   cho mỗi khối.
2. **Dựng cây** (`build_partition_tree`, `min_size=4`):
   - Loss khi tách `[lo, hi)` tại `i` = SS(trái) + SS(phải), với
     SS = tổng bình phương khoảng cách tới tâm cụm. Nhờ bảng tổng tích lũy, SS của mọi
     đoạn tính trong O(1).
   - Dùng heap: luôn tách chiếc lá có điểm tách loss nhỏ nhất, mỗi phía ≥ 4 lượt, cho đến
     khi không lá nào tách được. Mỗi lần tách ghi lại `gain = SS(cha) − loss`.
3. **Cắt cây** (`cut_tree_by_gain_threshold`):
   - Mở rộng các nút theo gain giảm dần, giữ lần tách nếu
     `gain ≥ min_relative_gain · SS(cả cuộc họp)` với `min_relative_gain = 0.022`.
   - Ngưỡng này là **toàn cục**, nên với cuộc họp dài có thể để lại đoạn khổng lồ
     (1259 lượt / 205k ký tự chỉ ra 2 đoạn). Vì vậy nút có tổng ký tự > 35 000 **vẫn bị tách**
     dù gain dưới ngưỡng, cho đến khi vừa trần hoặc không tách được nữa (< 2·`min_size` lượt).
   - Các lá chưa được mở rộng là các đoạn cuối cùng.

Tăng `_TREESEG_MIN_RELATIVE_GAIN` để có ít đoạn to hơn, giảm để có nhiều đoạn nhỏ hơn.

#### 3.5.4 So sánh nhanh

| | DialSTART | DialTreeSeg (I3+I5) | TreeSeg |
|---|---|---|---|
| Cần model train | Có (checkpoint ~1 GB) | Có (dùng lại DialSTART) | Không |
| Dùng `embedding_adapter` | Không | Có | Có |
| Quyết định có ranh giới | depth > mean + 6·std | `depth_z` > 1.0 tại điểm TreeSeg chọn | gain ≥ 0.022·SS gốc |
| Quyết định vị trí | khe depth cao | ứng viên DialSTART có SS hai phía nhỏ nhất | điểm có SS hai phía nhỏ nhất |
| Kích thước tối thiểu | 8 lượt, rồi 10 000 ký tự | 2000 ký tự mỗi phía | 4 lượt |
| Hậu xử lý | gộp đoạn kề cosine ≥ 0.65 | — | — |
| Trần ký tự | 35 000 (`pipeline.py`) | 35 000 (`007/config.json`) | 35 000 (`pipeline.py`) |
| Tham số nằm ở | hằng số `_DIALSTART_*` trong `pipeline.py` | `experiments/007_dialtreeseg/config.json` | hằng số `_TREESEG_*` + `width=5`, `min_size=4` trong `pipeline.py` |

Lỗi gọi embedding (TreeSeg, DialTreeSeg) là bước **duy nhất** trong pipeline không có
dự phòng; nó nổi lên thành `LLMUpstreamError` và router trả 502/504.


### 3.6 Stage07 — gán nhãn chủ đề (`stage07_topic_labeling.py::label_topics`)

Với từng đoạn, theo thứ tự (đoạn và nhãn liền trước được đưa vào làm ngữ cảnh):

1. **LLM** (`StructuredLLMTopicLabeler`) đề xuất `title` + `summary`.
2. **Kiểm tra cấu trúc** (`_validate_label_structure`) và **grounding guard**
   (`_find_label_grounding_issues`, chỉ so chuỗi, 0 token): loại tiêu đề nêu tên riêng
   không có trong đoạn hoặc cụm chung chung bị cấm.
3. Không đạt → thử lại, kèm hướng dẫn nêu đúng lỗi lần trước (tối đa `max_retry_attempts`).
4. Vẫn không đạt / adapter lỗi → **fallback tất định**: trích tiêu đề/tóm tắt từ đầu văn bản đoạn.

Stage này không làm hỏng request khi LLM lỗi. Kết quả: `labels_by_segment[segment_id] -> TopicLabel`.

### 3.7 Graph agent (`src/agentic/graph.py`)

`build_graph(content_llm, action_llm, decision_llm, debate_judge_llm)` rồi `graph.invoke(state)`
với `MeetingState` ban đầu gồm `segments`, `labels_by_segment`, `turns_by_id` và các
trường điều khiển/kết quả rỗng.

```
START / advance_topic ──gửi chủ đề i──► content_agent  ──┐
                                   ├──► action_agent   ──┼──► check_topic_evidence
                                   └──► decision_agent ──┘            │
                                                        candidate UNCERTAIN?
                                                     có ▼                 │ không
                                         debate_and_judge_agent (0..N)    │
                                                        ▼                 ▼
                                                     advance_topic ◄──────┘
                                      còn chủ đề → lặp i+1 │ hết → retry_failed_topics → END
```

**Chủ đề được xử lý tuần tự**; trong một chủ đề, ba agent trích xuất chạy song song (`Send`).

| Node | Loại | Việc làm | Ghi vào |
|---|---|---|---|
| `content_agent` | LLM | Trích luận điểm của từng người nói trong đoạn | `meeting_development` (thẳng, không kiểm chứng) |
| `action_agent` | LLM | Trích phát biểu giao việc (actor + việc + bằng chứng) | `action_item_candidates_raw` |
| `decision_agent` | LLM | Trích kết luận/chốt phương án | `decision_candidates_raw` |
| `check_topic_evidence` | Luật, 0 token | Action: UNCERTAIN nếu `actor` là None hoặc không định danh được ("nhóm", "một thành viên"). Decision: UNCERTAIN nếu có từ ngữ đề xuất/hedge. CLEAR → vào kết quả đã kiểm chứng; UNCERTAIN → `DebateTask` | `verified_assignments` / `verified_decisions`, `pending_debate_tasks` |
| `debate_and_judge_agent` | 3 lời gọi LLM | Agent A ủng hộ, Agent B phản biện, Judge phân xử giữ/bỏ. LLM lỗi → **giữ** candidate | kết quả đã kiểm chứng (nếu giữ), `debate_records` |
| `advance_topic` | Luật | Khi cả 3 nhánh + mọi debate của chủ đề xong: tăng `next_segment_index`, cộng tên/việc **đã kiểm chứng** vào `known_names` / `known_assignments` | trường điều khiển |
| `retry_failed_topics` | LLM | Chạy lại **một lần** các lời gọi content/action/decision đã lỗi, áp evidence-check bằng luật (không debate) | kết quả phục hồi, `unrecovered_failures` |

Một số điểm quan trọng:

- **Ngữ cảnh chạy dồn**: `known_names`/`known_assignments` được đưa vào prompt của chủ đề
  sau (`previous_context`) để quy các cách xưng hô "em"/"anh"/"bọn em" về tên thật đã biết.
  Đây là lý do không chạy song song mọi chủ đề.
- **Kiểm chứng trích dẫn** (`_shared.validate_evidence_with_quotes`): chỉ giữ `turn_id`
  thuộc đúng đoạn đang xét; câu trích chỉ được tin nếu là chuỗi con thật của
  `text_exact`, ngược lại thay bằng nguyên văn cả lượt nói.
- **Lỗi LLM không làm hỏng request**: agent trích xuất lỗi trả kết quả rỗng kèm
  `TopicFailure`; phần không phục hồi được sau retry báo ra ở `failed_topics`.
- **Chi phí**: `3N + 3M` lời gọi LLM cho graph (N = số chủ đề, M = số candidate
  UNCERTAIN), cộng N lời gọi (hoặc hơn nếu retry) của stage07.
- Hiện cả 4 vai trò LLM dùng chung một instance, chấp nhận rủi ro thiên vị tự đồng ý
  giữa bước trích xuất và bước kiểm chứng để giảm chi phí.

### 3.8 Serialize kết quả

`MeetingState` cuối chính là kết quả; graph không có node "assemble". Tầng `services/`
chỉ lắp ráp dữ liệu (0 token):

- `topics`: `meeting_development` (phẳng) được nhóm theo `segment_id` và ghép
  `title`/`summary` từ stage07, theo đúng thứ tự đoạn.
- `verified_assignments`, `verified_decisions`: danh sách phẳng; `actor` nằm trên
  từng item, **không** gộp theo người (việc gộp để hiển thị thuộc về frontend).
- `turns`: lượt nói rút gọn để frontend tra ngược `evidence_ids`.
- `failed_topics`, `debate_records`: phục vụ audit.

## 4. Đầu ra (`AnalyzeResponse`)

```jsonc
{
  "meeting_id": "...",
  "revision_id": "...",
  "topics": [                       // Diễn biến họp
    {
      "segment_id": "...", "title": "...", "summary": "...",
      "speakers": [
        { "initials": "...", "full_name": "...",
          "points": [ { "text": "...", "evidence_ids": ["turn-..."], "quotes": ["..."], "citation_count": 1 } ] }
      ]
    }
  ],
  "verified_assignments": [         // Giao việc
    { "segment_id": "...", "actor": "..." /* hoặc null */, "text": "...", "evidence_ids": [], "quotes": [], "citation_count": 0 }
  ],
  "verified_decisions": [           // Kết luận họp
    { "segment_id": "...", "text": "...", "evidence_ids": [], "quotes": [], "citation_count": 0 }
  ],
  "turns": [ { "turn_id": "...", "speaker": "...", "text": "..." } ],
  "failed_topics": [ { "segment_id": "...", "agent": "action_agent", "error": "..." } ],
  "debate_records": [
    { "segment_id": "...", "kind": "action|decision", "candidate_text": "...", "reasons": [],
      "support_argument": "...", "oppose_argument": "...", "kept": true, "reasoning": "..." }
  ]
}
```

`evidence_ids` và `quotes` luôn cùng độ dài, cùng thứ tự.

## 5. Biến môi trường

| Biến | Mặc định | Dùng ở |
|---|---|---|
| `TOPIC_SEGMENTER` | `dialstart` | chọn bộ cắt chủ đề (`dialstart` / `dialtreeseg` / `treeseg`) |
| `DIALSTART_CHECKPOINT` | `experiments/006_dialstart/model_vn3/best.pt` | checkpoint DialSTART |
| `EMBEDDING_BACKEND` | `local` | `local` (sentence-transformers) hoặc `openai` |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` / `text-embedding-3-small` | model embedding |
| `EMBEDDING_DEVICE`, `EMBEDDING_MAX_SEQ_LENGTH`, `EMBEDDING_TEXT_PREFIX` | auto / 1024 / rỗng | chỉ backend `local` |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | — | client LLM/embedding |
| `MODEL_NAME` | `gpt-4o-mini` | model chat cho stage07 và các agent |
| `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES` | xem `src/utils/openai_adapters.py` | timeout/retry của client |
| `ALLOWED_ORIGINS` | `*` | CORS |

## 6. Kiểm thử

`be/test_api.py` chạy một transcript thật qua toàn bộ luồng (stage01–03 → TreeSeg →
stage07 → graph → HTTP) với mọi adapter được thay bằng fake (không gọi mạng). Nó kiểm
tra việc nối dây end-to-end, không đánh giá chất lượng đầu ra của model.

## 7. Bản đồ file

| File | Vai trò |
|---|---|
| `be/main.py` | Tạo app FastAPI, lifespan, CORS, router |
| `be/routers/meetings.py` | Endpoint `/meetings/analyze`, ánh xạ lỗi |
| `be/routers/health.py` | `GET /health` |
| `be/schemas.py` | Schema request/response |
| `be/services/dependencies.py` | Dựng/cung cấp adapter và bộ cắt chủ đề |
| `be/services/pipeline.py` | Điều phối pipeline, hằng số cắt chủ đề, serialize |
| `src/utils/adapters.py` | Parse payload transcript |
| `src/stages/stage01..03_*.py`, `stage07_topic_labeling.py` | Các stage tiền xử lý và gán nhãn |
| `src/agentic/graph.py`, `state.py`, `nodes/*` | Graph agent LangGraph |
| `experiments/006_dialstart`, `007_dialtreeseg`, `treeseg_turn_level` | Các bộ cắt chủ đề |
