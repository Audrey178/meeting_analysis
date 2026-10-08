# SPEC — Downstream Meeting Reasoning Graph (MRG)

> Lớp downstream nhận output của topic segmentation và sinh ba sản phẩm: **Diễn biến họp**, **Giao việc**, **Kết luận họp**.
> Trạng thái tài liệu: bản nháp v0.2 (bước Plan). Các ngưỡng metric là giá trị khởi điểm, cần hiệu chỉnh sau pilot.
>
> **Thay đổi so với v0.1:**
>
> - Đơn vị xử lý là **unit = STT item**; bước `move_tagging` gộp vào `segment_extractor` theo kiểu trích xuất rồi grounding.
> - Topic segmentation (Stage 6–8) được dùng ở bốn chỗ: ranh giới làm đơn vị trích xuất, title/summary làm mục lục phiên họp và gợi ý Issue, `topic_map` làm ứng viên cho linker/merger, vị trí trong segment làm đặc trưng cho trạng thái Issue.
> - Thêm M0 (sửa hợp đồng dữ liệu segmentation), baseline B-LC/B-win, và metric đóng góp của segmentation cho downstream.

---

## 1. Bối cảnh và động lực

Pipeline downstream hiện tại (LangGraph: `action_agent`, `content_agent`, `decision_agent`, `check_topic_evidence`, `debate_and_judge_agent`, `advance_topic`, `retry_failed_topics`) xử lý **tuần tự từng topic, độc lập, trên văn bản phẳng**. Chạy thử trên một transcript thực cho thấy các lỗi mang tính cấu trúc:

| #   | Lỗi quan sát được                                                               | Nguyên nhân gốc                                         |
| --- | ------------------------------------------------------------------------------- | ------------------------------------------------------- |
| L1  | Gần hết turn gán cho một speaker; "Sơn" và "Phạm Hồng Sơn" bị trộn              | Không có bước resolve thực thể và vai trò               |
| L2  | Một việc (Payment) xuất hiện ở 2 topic với actor/deadline khác nhau             | Giao việc là bài toán toàn cục nhưng xử lý cục bộ       |
| L3  | Cùng một nội dung vừa là decision vừa là assignment                             | Không có ràng buộc loại trừ giữa các kiểu               |
| L4  | Issue còn mở ("một trong hai cơ chế", "đang nghiên cứu") bị ghi là "Thống nhất" | Không mô hình hóa trạng thái của vấn đề                 |
| L5  | Cùng thuật ngữ ASR ("mic tinh") ra hai dạng chuẩn hóa khác nhau                 | Không có thực thể canonical dùng chung                  |
| L6  | Báo cáo bug bị hiểu thành yêu cầu                                               | Không phân loại hành vi phát ngôn                       |
| L7  | Nội dung về giá API nằm trong topic scope POC                                   | Không có cơ chế liên kết/di chuyển nội dung xuyên topic |
| L8  | Debate chỉ kích hoạt khi gặp từ rào đón ("có thể")                              | Kích hoạt theo từ vựng, không theo mâu thuẫn            |

**Ý tưởng cốt lõi:** xây một đồ thị suy luận chung (MRG) làm shared state. Ba output là **ba phép chiếu** trên cùng đồ thị theo ba trục gom khác nhau. Luồng điều phối được dẫn dắt bởi **bất thường cấu trúc** trong đồ thị, không phải bởi vòng lặp topic cố định.

| Output        | Trục gom           | Phạm vi  |
| ------------- | ------------------ | -------- |
| Diễn biến họp | segment × speaker  | cục bộ   |
| Giao việc     | người              | toàn cục |
| Kết luận họp  | issue × trạng thái | toàn cục |

---

## 2. Phạm vi

**Trong phạm vi:**

- Nhận transcript đã segment (có label topic) và sinh ra MRG cùng 3 output.
- Suy luận bù cho lỗi diarization ở mức vai trò (ai giao, ai nhận).
- Chuẩn hóa deadline tương đối về ngày tuyệt đối dựa trên ngày họp.

**Ngoài phạm vi (v0.2):**

- Cải thiện ASR hoặc diarization ở tầng âm thanh.
- Tài liệu liên quan (văn bản đính kèm): để ở tầng hậu xử lý, thiết kế sau.
- Streaming/incremental: kiến trúc phải _cho phép_ mở rộng, nhưng v0.2 chạy batch.

---

## 3. Đầu vào

```json
{
  "meeting_meta": {
    "meeting_id": "string",
    "meeting_date": "YYYY-MM-DD",
    "chair": "string | null",
    "participants": ["string"]
  },
  "units": [
    {
      "unit_id": "UNIT_000001",
      "speaker_asr": "string | null",
      "text": "string",
      "t_start": 0.0,
      "t_end": 0.0,
      "source_ref": "string (ref_id của STT item)"
    }
  ],
  "segments": [
    {
      "segment_id": "TOPIC_SEG_000001",
      "unit_ids": ["UNIT_000001", "..."],
      "t_start": 0.0,
      "t_end": 0.0
    }
  ],
  "topic_labels": [
    {
      "segment_id": "TOPIC_SEG_000001",
      "title": "string",
      "summary": "string"
    }
  ],
  "topic_map": {
    "memberships": [["TOPIC_SEG_000001", "TOPIC_000001"]],
    "decisions": [
      {
        "source_segment_id": "TOPIC_SEG_000001",
        "target_segment_id": "TOPIC_SEG_000003",
        "same_topic": true,
        "relation": "string"
      }
    ]
  }
}
```

- `meeting_date` là **bắt buộc** để chuẩn hóa deadline ("thứ Hai tuần sau").
- `chair` và `participants` là tùy chọn; nếu thiếu, `entity_resolution` sẽ suy luận.
- **Đơn vị xử lý là unit = một STT item**, không phải atom và không phải speaker turn. Không dùng speaker turn vì diarization có thể gộp gần hết phiên họp vào một speaker (`inputs/recording.json`: 884/988 item cùng `speaker_id`). Khi đó một "turn" sẽ chứa cả báo cáo, đề xuất, chốt và giao việc. STT item ngắn (trung vị 35–85 ký tự), có id và timestamp thật, nên đủ mịn để làm địa chỉ evidence.
- `segments`, `topic_labels`, `topic_map` lấy từ Stage 6, 7, 8. Mỗi segment **bắt buộc** mang `segment_id` và `unit_ids` (xem M0).
- Nếu thiếu `topic_map` (chưa chạy Stage 8), linker/merger quay về lọc ứng viên bằng embedding.

---

## 4. Schema của Meeting Reasoning Graph

### 4.1 Node

| `node_type`    | Ý nghĩa                                               | Trường riêng                                                                                                             |
| -------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `Entity`       | Người, dự án, hệ thống, thuật ngữ                     | `canonical_name`, `surface_forms[]`, `entity_kind` (person/project/system/term), `role` (chair/member/external/customer) |
| `Issue`        | Vấn đề cần giải quyết                                 | `title`, `status` (xem 4.3)                                                                                              |
| `Position`     | Đề xuất hoặc phương án                                | `content`, `speaker`                                                                                                     |
| `Argument`     | Lập luận ủng hộ hoặc phản biện                        | `content`, `speaker`, `polarity` (pro/con)                                                                               |
| `StatusReport` | Báo cáo tiến độ hoặc quan sát                         | `content`, `speaker`, `progress` (done/in_progress/blocked/observation)                                                  |
| `Commitment`   | Một việc cần làm                                      | xem 4.4                                                                                                                  |
| `Constraint`   | Ràng buộc (hạn chót, ngân sách, điều kiện khách hàng) | `content`, `value`                                                                                                       |

Mọi node có các trường chung:

```json
{
  "node_id": "string",
  "node_type": "string",
  "segment_ids": ["string"],
  "evidence": [{ "unit_id": "string", "span": [0, 0], "quote": "string" }],
  "t_start": 0.0,
  "t_end": 0.0,
  "speaker_asr": "string | null",
  "speaker_inferred": "canonical_name | null",
  "speaker_confidence": 0.0,
  "confidence": 0.0,
  "created_by": "agent_name"
}
```

- `evidence.span` là vị trí ký tự trong `unit.text`. Span do `grounder` (rule) xác định bằng cách tìm `quote` trong unit, **không** lấy vị trí ký tự do LLM tự báo.
- `t_start` / `t_end` lấy từ evidence sớm nhất / muộn nhất. Thứ tự thời gian này được dùng cho luật trạng thái ở 4.3 và A4.
- `speaker_inferred` được suy từ nội dung ("em sẽ làm", "anh giao cho Sơn") khi `speaker_asr` không đáng tin. Realizer dùng `speaker_inferred` nếu có, ngược lại dùng `speaker_asr`.

### 4.2 Edge

| `edge_type`            | Nguồn → Đích                             | Ý nghĩa                             |
| ---------------------- | ---------------------------------------- | ----------------------------------- |
| `proposes`             | Position → Issue                         | Phương án cho vấn đề                |
| `supports` / `attacks` | Argument/Position → Position             | Ủng hộ / phản biện                  |
| `refines`              | Position → Position                      | Điều chỉnh phương án trước          |
| `resolves`             | Position → Issue                         | Người có thẩm quyền chốt (câu chốt) |
| `assigned_to`          | Commitment → Entity(person)              | Người thực hiện                     |
| `assigned_by`          | Commitment → Entity(person)              | Người giao                          |
| `addresses`            | Commitment → Issue                       | Việc này nhằm giải quyết vấn đề nào |
| `depends_on`           | Commitment/Issue → Constraint/Commitment | Phụ thuộc hoặc điều kiện            |
| `same_as`              | X → X (cùng loại)                        | Hai node là một, xuyên segment      |
| `mentions`             | bất kỳ → Entity                          | Tham chiếu thực thể                 |

Mọi edge có `evidence[]` và `confidence`.

### 4.3 Trạng thái Issue

| `status`               | Điều kiện                                                                               |
| ---------------------- | --------------------------------------------------------------------------------------- |
| `resolved`             | Có `resolves` từ người có thẩm quyền; không có `attacks` sau thời điểm resolve còn treo |
| `resolved_conditional` | Như `resolved` nhưng Issue hoặc Position được chọn có `depends_on` chưa thỏa            |
| `deferred`             | Có phát ngôn hoãn tường minh ("để sau POC")                                             |
| `open`                 | Chưa có `resolves`                                                                      |

### 4.4 Commitment

```json
{
  "node_type": "Commitment",
  "task": "string (động từ + đối tượng)",
  "deliverable": "string | null",
  "commitment_kind": "new_assignment | self_committed | ongoing",
  "deadline_raw": "string | null",
  "deadline_norm": "YYYY-MM-DD | null",
  "deadline_precision": "day | week | month | event | none",
  "condition": "string | null"
}
```

- `ongoing`: việc đang làm tiếp ("Sơn vẫn đang làm phần benchmark"). Nó vẫn được liệt kê, nhưng ở mục riêng trong bảng giao việc.
- "tuần này hoặc tuần sau" → `deadline_precision = week`, lấy mốc cuối.
- Quy ước chuẩn hóa: tuần bắt đầu từ thứ Hai; "tuần sau" = thứ Sáu của tuần kế tiếp; "cuối tháng" = ngày cuối tháng.
- Mốc theo sự kiện ("trước buổi kickoff", "sau POC") → `deadline_precision = event`, `deadline_norm = null`, giữ nguyên `deadline_raw`.

### 4.5 Ràng buộc toàn vẹn (dùng cho `anomaly_check`)

- R1: một span evidence không được đồng thời sinh ra `Position` được `resolves` **và** `Commitment`. Nếu nội dung là "trao đổi với khách để xin ý kiến" thì đó là Commitment `addresses` một Issue `resolved_conditional`.
- R2: mọi `Commitment` phải có đúng 1 `assigned_to` (hoặc được gắn cờ A1).
- R3: `assigned_to` ≠ `assigned_by`, trừ khi `commitment_kind = self_committed`.
- R4: các node `same_as` phải có cùng `node_type`.
- R5: `Entity(person)` chỉ có một `canonical_name`; mọi realizer dùng `canonical_name`.

---

## 5. Kiến trúc xử lý

### 5.1 Bốn pha

```
[Pha 0 — deterministic, không gọi LLM]
  input_validator     → mọi segment có segment_id + unit_ids; unit_ids phủ kín và không chồng lấn
  context_builder     → dựng "mục lục phiên họp" từ topic_labels (segment_id, title, summary,
                        topic_id từ topic_map); với mỗi segment, thêm k unit đệm ở hai đầu
                        (mặc định k = 2) để bù cho ranh giới lệch

[Pha 1 — cục bộ, song song theo segment (LangGraph Send)]
  segment_extractor   → 1 lời gọi LLM có schema cố định cho mỗi segment. Input: unit của
                        segment (kèm unit_id) + unit đệm (đánh dấu là ngữ cảnh) + mục lục phiên họp.
                        Output: node + edge nội segment (Issue, Position, Argument, StatusReport,
                        Commitment, Constraint; proposes, supports, attacks, refines, resolves,
                        assigned_to…), mỗi claim kèm {unit_ids, quote nguyên văn}.
                        Issue phải gắn vào topic của segment, hoặc khai báo rõ là Issue mới.
                        Nội dung nhắc tới topic ở segment khác → ghi `ref_segment_id` (gợi ý A7).
  grounder            → rule: tìm quote trong text của unit được trích dẫn (chuẩn hóa dấu câu,
                        khoảng trắng; fuzzy ratio ≥ 0.9) → evidence.span. Không khớp: retry
                        segment_extractor 1 lần cho claim đó; vẫn trượt thì bỏ node và ghi log.
                        Node chỉ có evidence nằm trong unit đệm → gắn cờ A7.

[Pha 2 — toàn cục]
  entity_resolution   → canonical entity, vai trò, speaker_inferred, sửa speaker nghi gộp
  issue_linker        → same_as giữa Issue xuyên segment; ứng viên lấy từ topic_map (mục 5.2)
  commitment_merger   → same_as giữa Commitment; ứng viên như trên; gộp trường
  status_resolver     → gán status cho mọi Issue
  anomaly_check       → chạy luật (mục 6), phát sinh danh sách anomaly
      ├─ có anomaly cần sửa → targeted agents (trả về patch) → quay lại anomaly_check
      └─ không còn / hết số vòng → Pha 3

[Pha 3 — chiếu]
  dien_bien_realizer | giao_viec_realizer | ket_luan_realizer
  global_consistency_check → END
```

### 5.2 Cách sinh Issue (quyết định thiết kế)

**Mặc định:** Issue được sinh từ các `Position`. Trong một segment, các Position cùng hướng tới một vấn đề được gom thành một Issue. Sau đó `issue_linker` nối các Issue xuyên segment. Label topic chỉ đóng vai trò **vùng chứa**, không đồng nhất với Issue.

Lý do: một segment thường chứa nhiều Issue (ví dụ segment về tính phí chứa giá bán, phân cấp gói và cổng thanh toán). Một Issue cũng có thể trải qua nhiều segment (Payment).

**Phương án thay thế** (dùng làm baseline ablation): 1 segment = 1 Issue.

### 5.2b Tận dụng topic segmentation

| Output của Stage 6–8        | Dùng trong MRG                                                                                                                                                                                             |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ranh giới segment (Stage 6) | Đơn vị trích xuất Pha 1 (thay cho window độ dài cố định); trục gom của Diễn biến họp                                                                                                                       |
| Title + summary (Stage 7)   | (a) Mục lục phiên họp gửi kèm mọi lời gọi Pha 1, giúp LLM biết nội dung liên quan nằm ở segment nào → giảm L2, L7. (b) Gợi ý Issue: title là ứng viên Issue chính của segment                              |
| `topic_map` (Stage 8)       | Lọc ứng viên cho `issue_linker` / `commitment_merger`: chỉ so node giữa các segment cùng `topic_id` hoặc có `decisions.same_topic = true`, cộng với các cặp có `ref_segment_id`. Fallback: embedding top-k |
| Vị trí trong segment        | Đặc trưng cho `status_resolver`: câu chốt thường nằm ở phần cuối segment (chủ tọa tổng kết); đặc trưng này không phụ thuộc diarization                                                                     |

**Ranh giới sai được sửa ở mức node, không sửa lại segmentation.** Segmentation theo turn có thể bỏ sót ranh giới nằm giữa một turn. Khi đó A7 / `relocation_agent` chuyển node sang đúng segment. Log relocation cũng là **tín hiệu đánh giá gián tiếp** cho segmentation: một ranh giới có nhiều node phải chuyển có khả năng đặt sai (xem 8.2).

**Rủi ro:** nếu Stage 8 gộp quá tay (ví dụ mọi segment cùng một `topic_id`), bước lọc ứng viên mất tác dụng và chi phí quay về mức so tất cả các cặp. Khi tỷ lệ cặp ứng viên / tổng số cặp > 0.5 thì ghi cảnh báo và giới hạn thêm bằng embedding top-k.

### 5.3 LangGraph state

```python
class MeetingGraphState(TypedDict):
    """
    Chức năng: trạng thái chung của toàn bộ đồ thị xử lý downstream.
    Đầu vào: được khởi tạo từ output của topic segmentation (mục 3).
    Đầu ra: được các realizer đọc để sinh 3 sản phẩm cuối.
    """
    meeting_meta: dict
    units: dict[str, dict]           # tra cứu nhanh theo unit_id
    segments: list[dict]
    topic_labels: dict[str, dict]    # segment_id -> {title, summary}
    topic_map: dict                  # memberships + decisions từ Stage 8
    meeting_outline: str             # mục lục phiên họp (Pha 0)
    nodes: dict[str, dict]           # node_id -> node
    edges: list[dict]
    grounding_failures: list[dict]   # claim bị bỏ vì không tìm được quote
    anomalies: list[dict]            # anomaly chưa xử lý
    patches: list[dict]              # patch đã áp dụng (log có thể replay)
    resolved_anomalies: list[dict]   # log anomaly đã xử lý (phục vụ phân tích lỗi)
    repair_iteration: int            # chặn vòng lặp sửa vô hạn
    outputs: dict                    # dien_bien / giao_viec / ket_luan
```

- Các node Pha 1 ghi vào `nodes` và `edges` qua reducer hợp nhất theo `node_id`.
- `repair_iteration` tối đa **3**; vượt ngưỡng thì anomaly còn lại được đưa vào output dưới dạng cảnh báo.
- Targeted agent **không sửa graph trực tiếp**. Agent trả về danh sách patch `{op: add|remove|update, target: node|edge, id, fields, reason, anomaly_id}`; một node rule áp dụng patch và kiểm tra lại R1–R5. Nhờ vậy mọi thay đổi đều audit và replay được.

### 5.4 Danh sách node LangGraph

| Node                       | Loại           | Ghi chú                                                                                                                               |
| -------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `input_validator`          | rule           | Chặn chạy nếu segment thiếu `segment_id` / `unit_ids`                                                                                 |
| `context_builder`          | rule           | Mục lục phiên họp + unit đệm                                                                                                          |
| `segment_extractor`        | LLM, song song | Thay cho `move_tagging` + `build_segment_graph`; schema cố định; few-shot tiếng Việt hội họp; rule kiểm tra hướng và kiểu edge hợp lệ |
| `grounder`                 | rule           | Quote → span; bỏ claim không tìm được quote                                                                                           |
| `entity_resolution`        | lexicon + LLM  | Lexicon ASR (vd. "mic tinh" → meeting, "pi" → PII) + suy vai trò từ xưng hô và cấu trúc giao việc                                     |
| `issue_linker`             | rule + LLM     | Ứng viên từ `topic_map` (fallback embedding), LLM xác nhận `same_as`                                                                  |
| `commitment_merger`        | rule + LLM     | Như trên; hợp nhất trường, ghi nhận xung đột                                                                                          |
| `status_resolver`          | rule + LLM     | Rule theo 4.3 + đặc trưng vị trí trong segment; LLM chỉ phân xử khi có hedge hoặc `attacks` mơ hồ                                     |
| `anomaly_check`            | rule thuần     | Deterministic, không gọi LLM                                                                                                          |
| `attribution_agent`        | LLM            | Xử lý A1, A2, A8                                                                                                                      |
| `status_agent`             | LLM            | Xử lý A4, A6                                                                                                                          |
| `conflict_agent`           | LLM (debate)   | Xử lý A3, A9: support / oppose / judge trên **subgraph** có evidence của cả hai phía                                                  |
| `relocation_agent`         | LLM            | Xử lý A7                                                                                                                              |
| 3 realizer                 | LLM            | Chỉ được dùng nội dung trong graph, không đọc lại transcript tự do                                                                    |
| `global_consistency_check` | rule           | Đối chiếu chéo 3 output                                                                                                               |

---

## 6. Luật phát hiện bất thường

| ID  | Luật                                                                                                                              | Mức               | Agent xử lý                                 |
| --- | --------------------------------------------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------- |
| A1  | `Commitment` không có `assigned_to`                                                                                               | sửa               | `attribution_agent`                         |
| A2  | `assigned_to == assigned_by` và không phải `self_committed`                                                                       | sửa               | `attribution_agent`                         |
| A3  | Hai `Commitment` `same_as` nhưng lệch actor hoặc deadline                                                                         | sửa               | `conflict_agent`                            |
| A4  | Issue `resolved` nhưng có `attacks` sau thời điểm resolve                                                                         | sửa               | `status_agent`                              |
| A5  | Issue `open` không có `Commitment` nào `addresses`                                                                                | **cờ**, không sửa | đưa vào kết luận: "chưa có người phụ trách" |
| A6  | `resolves` có ngôn ngữ rào đón hoặc chưa dứt khoát                                                                                | sửa               | `status_agent`                              |
| A7  | Node có evidence chỉ nằm trong unit đệm / ngoài segment chứa nó, có `ref_segment_id`, hoặc liên kết mạnh với Issue ở segment khác | sửa               | `relocation_agent`                          |
| A8  | Một người có nhiều `surface_form` mâu thuẫn, hoặc một speaker chiếm > 80% turn (nghi gộp)                                         | sửa               | `attribution_agent`                         |
| A9  | Cùng span sinh ra các node vi phạm R1                                                                                             | sửa               | `conflict_agent`                            |

A5 là **thông tin có giá trị cho người chủ trì**, không phải lỗi hệ thống.

---

## 7. Đặc tả ba output

### 7.1 Diễn biến họp

Quy tắc chiếu:

- Với từng segment, gom node theo `speaker`, sắp theo thời gian.
- Ưu tiên `Position` và `Argument`; `StatusReport` được rút gọn thành một dòng.
- Mỗi ý kiến kèm quan hệ với ý kiến khác (`supports`, `attacks`, `refines`).

```json
{
  "segment_id": "string",
  "title": "string",
  "flow": [
    {
      "speaker": "canonical_name",
      "opinion": "string",
      "opinion_type": "position | argument | status_report",
      "relations": [
        {
          "type": "supports | attacks | refines",
          "target_speaker": "string",
          "target_opinion_ref": "node_id"
        }
      ],
      "evidence": [{ "unit_id": "string", "span": [0, 0] }]
    }
  ],
  "issues_in_segment": ["node_id"]
}
```

### 7.2 Giao việc

Quy tắc chiếu:

- Gom `Commitment` theo `assigned_to` trên **toàn phiên họp**, sau khi đã hợp nhất `same_as`.
- Mỗi người có hai nhóm: `new_or_self_committed` và `ongoing`.
- Sắp xếp theo `deadline_norm` tăng dần; việc không có hạn xếp cuối.

```json
{
  "person": "canonical_name",
  "role": "chair | member | external | customer",
  "tasks": [
    {
      "task": "string",
      "deliverable": "string | null",
      "commitment_kind": "new_assignment | self_committed",
      "assigned_by": "string | null",
      "co_actors": ["string"],
      "deadline_raw": "string | null",
      "deadline_norm": "YYYY-MM-DD | null",
      "condition": "string | null",
      "addresses_issue": "node_id | null",
      "segments": ["string"],
      "evidence": [{ "unit_id": "string", "span": [0, 0] }]
    }
  ],
  "ongoing": [{ "task": "string", "segments": ["string"], "evidence": [] }]
}
```

### 7.3 Kết luận họp

Quy tắc chiếu:

- `resolved` → mục **Các vấn đề đã thống nhất**.
- `resolved_conditional` → mục **Thống nhất có điều kiện**, kèm điều kiện và người theo dõi.
- `deferred` → mục **Tạm hoãn**, kèm mốc xem xét lại nếu có.
- `open` → mục **Vấn đề còn tồn đọng**, bắt buộc kèm danh sách `Commitment` giải quyết nó; nếu không có thì ghi `owner_missing = true` (A5).

```json
{
  "resolved": [
    {
      "issue": "string",
      "conclusion": "string",
      "resolved_by": "string",
      "evidence": []
    }
  ],
  "resolved_conditional": [
    {
      "issue": "string",
      "conclusion": "string",
      "condition": "string",
      "follow_up": ["commitment_ref"]
    }
  ],
  "deferred": [{ "issue": "string", "until": "string | null", "evidence": [] }],
  "open": [
    {
      "issue": "string",
      "follow_up": ["commitment_ref"],
      "owner_missing": false,
      "evidence": []
    }
  ],
  "warnings": [{ "anomaly_id": "string", "message": "string" }]
}
```

Bản văn "Thông báo kết luận" theo thể thức hành chính được sinh từ JSON này bằng template đã có (`Prompt_sinh_thong_bao_ket_luan_hop.md`).

### 7.4 Kiểm tra nhất quán chéo (`global_consistency_check`)

- Mọi `follow_up` trong kết luận phải xuất hiện trong giao việc.
- Không Commitment nào xuất hiện ở hai người khác nhau.
- Mọi Issue được nhắc trong diễn biến phải có mặt ở đúng một mục trong kết luận.

---

## 8. Đánh giá

### 8.1 Dữ liệu

- **Gold:** tập nhỏ biên bản họp được gán nhãn thủ công ở tầng Issue / trạng thái / Commitment (không gán toàn bộ edge). Gán nhãn độc lập với nguồn silver để tránh vòng lặp.
- **Silver:** bộ ba tài liệu phiên họp Quốc hội (chương trình, bản tổng hợp thảo luận, thông cáo), neo vào phần kết luận của chủ tọa.
- **Pilot:** 1–2 transcript nội bộ (như transcript đã chạy thử) để kiểm tra định tính trước khi gán nhãn quy mô.

### 8.2 Metric và ngưỡng khởi điểm

| Output                    | Metric                                                                                                 | Ngưỡng khởi điểm                             |
| ------------------------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------- |
| Trích xuất                | P/R theo node Issue và Commitment (so khớp với gold theo nội dung + evidence)                          | R ≥ 0.75, P ≥ 0.70                           |
| Trích xuất                | Accuracy loại node (Position / StatusReport / Commitment…) trên node khớp gold                         | ≥ 0.70 (thay Macro-F1 move tagging của v0.1) |
| Diễn biến                 | Độ đúng gán ý kiến ↔ speaker, tính riêng trên tập unit có speaker tin cậy                              | ≥ 0.80                                       |
| Diễn biến                 | Độ đúng gán ý kiến ↔ speaker, toàn bộ (báo cáo, không đặt ngưỡng)                                      | —                                            |
| Diễn biến                 | Độ đúng quan hệ (supports/attacks/refines)                                                             | ≥ 0.60                                       |
| Giao việc                 | F1 bộ ba (actor, task, deadline) sau gộp                                                               | ≥ 0.65                                       |
| Giao việc                 | Tỷ lệ việc trùng hoặc bị tách sai                                                                      | ≤ 10%                                        |
| Kết luận                  | Accuracy trạng thái Issue (4 lớp)                                                                      | ≥ 0.75                                       |
| Kết luận                  | **Recall vấn đề tồn đọng**                                                                             | ≥ 0.85 (ưu tiên hơn precision)               |
| Toàn hệ thống             | Tỷ lệ output vi phạm 7.4                                                                               | 0%                                           |
| Grounding                 | Tỷ lệ claim có span evidence hợp lệ                                                                    | ≥ 0.95                                       |
| Grounding                 | Tỷ lệ claim bị `grounder` bỏ                                                                           | ≤ 5% (cao hơn → xem lại prompt)              |
| Segmentation (downstream) | Tỷ lệ node bị relocation (A7)                                                                          | báo cáo, không đặt ngưỡng                    |
| Segmentation (downstream) | Tương quan giữa số node relocation tại một ranh giới và việc ranh giới đó sai so với gold segmentation | báo cáo                                      |

Bỏ sót một vấn đề tồn đọng gây hại nhiều hơn tóm tắt thiếu chi tiết, vì vậy recall của mục `open` được đặt ngưỡng cao nhất.

Hai metric segmentation là **đánh giá gián tiếp**: chúng đo segmentation có ích cho downstream đến đâu, bổ sung cho Pk / WindowDiff / boundary F1 (`eval/segmentation_metrics.py`).

### 8.3 Ablation

| Cấu hình | Mô tả                                                                                        |
| -------- | -------------------------------------------------------------------------------------------- |
| B0       | Pipeline hiện tại (agent phẳng theo topic)                                                   |
| B-LC     | 1 lời gọi long-context đọc toàn transcript, sinh thẳng 3 output (không graph, không segment) |
| B1       | MRG, 1 segment = 1 Issue, không có Pha 2                                                     |
| B2       | MRG đầy đủ Pha 1 + 2, không có vòng sửa anomaly                                              |
| B3       | MRG đầy đủ                                                                                   |

Ablation riêng cho **đóng góp của topic segmentation** (đều trên nền B3):

| Cấu hình  | Đơn vị trích xuất Pha 1           | Mục lục phiên họp | Ứng viên linker/merger |
| --------- | --------------------------------- | ----------------- | ---------------------- |
| S-win     | window độ dài cố định, có overlap | không             | embedding              |
| S-seg     | segment                           | không             | embedding              |
| S-seg+ctx | segment                           | có                | embedding              |
| S-full    | segment                           | có                | `topic_map`            |
| S-gold    | segment gold                      | có (title gold)   | `topic_map` gold       |

- S-full − S-win: đóng góp tổng của segmentation cho downstream.
- S-gold − S-full: phần còn lại có thể cải thiện nếu segmentation tốt hơn.
- B-LC là mốc bắt buộc: transcript pilot chỉ khoảng 8k–15k token, vừa context. Nếu B3 không vượt B-LC thì Pha 2 chưa có lý do tồn tại.

---

## 9. Milestone (xếp theo rủi ro giảm dần)

| #   | Milestone                                                                        | Tiêu chí hoàn thành                                                                                                                                                                                                                              |
| --- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| M0  | Hợp đồng dữ liệu segmentation + `input_validator`, `context_builder`, `grounder` | Output TreeSeg / Stage 6–8 mang `segment_id`, `unit_ids`, `topic_map` (hiện `outputs/stage_8_treeseg.json` có `segment_id = null`, `atom_ids = null` và không có `topic_map`); 100% segment truy ngược được về STT item; `grounder` có unit test |
| M1  | `segment_extractor` + `status_resolver` trên pilot                               | Đạt ngưỡng 8.2 cho trích xuất, grounding và trạng thái Issue trên pilot đã gán nhãn                                                                                                                                                              |
| M1b | Chạy B-LC trên pilot                                                             | Có con số mốc để quyết định mức đầu tư cho Pha 2                                                                                                                                                                                                 |
| M2  | `entity_resolution` + `commitment_merger`                                        | Pilot: không còn L1, L2; A8 phát hiện đúng speaker gộp                                                                                                                                                                                           |
| M3  | `issue_linker` với ứng viên từ `topic_map` (quyết định 5.2, 5.2b)                | So sánh 5.2 mặc định với B1; kiểm tra Stage 8 có gộp quá tay không trên transcript nhiều chủ đề                                                                                                                                                  |
| M4  | `anomaly_check` + các targeted agent                                             | Mọi luật A1–A9 có unit test; vòng sửa hội tụ trong ≤ 3 lần trên pilot                                                                                                                                                                            |
| M5  | 3 realizer + `global_consistency_check`                                          | Output đúng schema mục 7; 0 vi phạm 7.4                                                                                                                                                                                                          |
| M6  | Đánh giá gold/silver + ablation B0–B3, B-LC, S-\*                                | Có bảng kết quả đầy đủ mục 8                                                                                                                                                                                                                     |

M0 đi trước vì không có `unit_ids` thì không grounding được, và mọi metric evidence đều vô nghĩa. M1 tiếp theo vì nếu trích xuất node và trạng thái vấn đề không đủ tốt thì toàn bộ graph phía sau sai theo.

---

## 10. Giả định và rủi ro

| Loại     | Nội dung                                                          | Giảm thiểu                                                                                                                                                                                                        |
| -------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Giả định | Một segment (kèm unit đệm) vừa một lời gọi LLM                    | Segment quá dài (> N token) được chia thành window con có overlap; node trùng giữa các window gộp bằng `commitment_merger` / `issue_linker`                                                                       |
| Giả định | Ranh giới segment đủ đúng để làm đơn vị trích xuất                | Unit đệm + A7 relocation; đo bằng ablation S-win / S-gold                                                                                                                                                         |
| Rủi ro   | LLM diễn đạt lại thay vì trích quote nguyên văn → grounding trượt | Prompt yêu cầu quote nguyên văn; fuzzy match ≥ 0.9; theo dõi tỷ lệ claim bị bỏ                                                                                                                                    |
| Rủi ro   | Stage 8 gộp quá tay → lọc ứng viên mất tác dụng                   | Ngưỡng cảnh báo ở 5.2b; fallback embedding top-k                                                                                                                                                                  |
| Giả định | Có `meeting_date`                                                 | Nếu thiếu: giữ `deadline_raw`, `deadline_norm = null`                                                                                                                                                             |
| Rủi ro   | Diarization quá tệ, suy luận vai trò không bù được                | Giới hạn mục tiêu ở mức vai trò (người giao / người nhận); báo cáo riêng tỷ lệ unit có speaker tin cậy                                                                                                            |
| Rủi ro   | Lan truyền lỗi từ `segment_extractor`                             | Rule kiểm tra kiểu edge; confidence thấp → không tạo edge                                                                                                                                                         |
| Rủi ro   | Chi phí LLM cao (nhiều lời gọi)                                   | Batch theo segment; rule/embedding làm lọc trước, LLM chỉ xử lý ca mơ hồ                                                                                                                                          |
| Rủi ro   | Gán nhãn gold toàn đồ thị quá tốn công                            | Chỉ gán tầng Issue / trạng thái / Commitment                                                                                                                                                                      |
| Rủi ro   | Over-engineering                                                  | MVP chỉ dùng node `Issue`, `Position`, `StatusReport`, `Commitment`, `Entity` (`StatusReport` cần cho Diễn biến họp) và edge `resolves`, `attacks`, `assigned_to`, `same_as`; mở rộng khi ablation chứng minh cần |

---

## 11. Câu hỏi mở

1. Thẩm quyền "chốt" (`resolves`) xác định thế nào khi không biết trước chủ tọa? Hướng v0.2: kết hợp cue chốt ("thống nhất", "vậy nhé", "chốt") với vị trí cuối segment, rồi LLM xác nhận; speaker chỉ là tín hiệu phụ vì diarization không đáng tin. Cần kiểm chứng trên pilot.
2. Khi `conflict_agent` không phân xử được (A3), output nên giữ cả hai phương án kèm cảnh báo, hay chọn phương án có evidence muộn hơn?
3. Mở rộng streaming: Pha 2 chạy lại toàn bộ sau mỗi segment mới, hay chỉ trên vùng đồ thị bị ảnh hưởng?
4. Tài liệu liên quan (khi đưa vào sau) sẽ vào graph dưới dạng node `Constraint` / `Entity`, hay chỉ dùng ở realizer để sửa tên riêng và số liệu?
5. Khi Stage 8 và `issue_linker` bất đồng (Stage 8 nói khác topic, nhưng hai Issue rõ ràng là một), có nên phản hồi ngược để sửa `topic_map` không?
