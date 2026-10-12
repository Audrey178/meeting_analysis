# Kiến trúc `src/agentic_v3`

Báo cáo kiến trúc pipeline agentic v3: phân tích biên bản họp (Diễn biến họp, Giao việc,
Kết luận họp, và Tiến độ các việc cần báo cáo khi phiên họp có danh sách việc) sau khi
transcript đã được tách lượt nói và cắt chủ đề.

Cập nhật: 2026-10-11 (danh sách việc cần báo cáo tiến độ: agent tiến độ, kiểm lượt nêu
trạng thái bằng Decisions API, gộp tiến độ theo việc, quan hệ việc giao với việc cũ; mục 4.6).

---

## 1. Mục tiêu và khác biệt so với v1

| | v1 (`src/agentic`) | v3 (`src/agentic_v3`) |
|---|---|---|
| Thứ tự chủ đề | Tuần tự: chủ đề N xong hẳn mới gửi N+1 | **Song song**: mọi chủ đề cùng lúc (`Send` → subgraph) |
| Ngữ cảnh giữa chủ đề | `known_names`/`known_assignments` chạy dồn | `SpeakerRegistry` của cả cuộc họp, dựng 1 lần trước |
| Gán nhãn chủ đề | Chạy hết stage07 trước | Ngay trong subgraph, chủ đề nào có nhãn thì trích xuất luôn |
| Chọn agent | Luôn chạy đủ 3 agent | **Planner** (luật, 0 token) bỏ Action/Decision khi không có cue |
| Prompt agent trích xuất | Prompt v1 | Prompt riêng của v3 (`nodes/prompts.py`), kèm người chủ trì |
| Kiểm chứng candidate nghi ngờ | Debate + Judge (3 lời gọi, chỉ đọc đoạn hiện tại) | **Verifier ReAct** có tool tra **cả cuộc họp** |
| Khi chưa chắc | Giữ theo luật an toàn | **Vòng đồng thuận** Verifier ⇄ agent trích xuất |
| Thử lại lỗi LLM | Sau chủ đề cuối (`retry_failed_topics`) | Ngay trong chủ đề (`extract_attempts`) |
| Giới hạn đồng thời | — | `LLMConcurrencyGate` dùng chung cả tiến trình |
| Việc cần báo cáo tiến độ | — | Có `*.tasks.json` thì thêm **agent tiến độ** + Decisions xét lượt nêu trạng thái (mục 4.6) |

Lý do chính: nút thắt thời gian của v1 là vòng lặp tuần tự theo chủ đề, tồn tại chỉ để
mang `known_names` sang chủ đề sau. v3 thay ngữ cảnh đó bằng danh bạ dựng sẵn nên các
chủ đề độc lập với nhau, và tổng thời gian không còn tăng tuyến tính theo số chủ đề.

v3 dùng lại các node trích xuất (phần làm sạch output) và luật hậu kiểm của v1, nhưng
qua bản CHÉP ở `src/agentic_v3/core/` chứ không import `src.agentic`: hai pipeline sửa
độc lập, **không sửa gì ở v1**. Prompt của ba agent trích xuất là bản
riêng của v3 (mục 4.2).

---

## 2. Sơ đồ tổng thể

```
                     ┌──────────────────── graph cha (graph/meeting.py) ────────────┐
                     │                                                              │
 turns + segments ──►│ START ─► plan_meeting ─► Send("topic", chủ đề i) cho MỌI i   │
                     │          (luật, 0 token)        │  │  │   (song song)        │
                     │                                 ▼  ▼  ▼                      │
                     │                       ┌── subgraph topic (graph/topic.py) ─┐ │
                     │                       │ label_topic                        │ │
                     │                       │   ├─► content_agent ──────────┐    │ │
                     │                       │   ├─► action_agent   (nếu plan)├─► evidence_check
                     │                       │   ├─► decision_agent (nếu plan)┤    │ │
                     │                       │   └─► progress_agent (nếu có    ┘    │ │
                     │                       │        danh sách việc; kiểm bằng Decisions,
                     │                       │        không đi Verifier)          │ │
                     │                       │          CLEAR ─► kết quả          │ │
                     │                       │          UNCERTAIN ─► Send ─► verifier (0..N)
                     │                       │                 (Verifier ⇄ agent trích xuất)
                     │                       └────────────────────────────────────┘ │
                     │                                 │                            │
                     │                                 ▼                            │
                     │   finalize (+ tiến độ theo việc) ─► END ─► MeetingReport   │
                     └──────────────────────────────────────────────────────────────┘
```

Graph chạy **một mạch** từ START tới END, không dừng chờ người, nên không cần checkpointer.

---

## 3. Các module

Phụ thuộc chỉ đi một chiều: `graph/` → `nodes/` → `actors/` → `schemas.py`/`config.py` → `core/`.

```
src/agentic_v3/
├── __init__.py        API công khai (MeetingAnalyzerV3, V3Config, load_attendee_roster, …)
├── config.py          V3Config
├── schemas.py         kiểu dùng chung của v3
├── runner.py          MeetingAnalyzerV3 (điểm vào cho be/)
├── core/              chép từ src/agentic (v1): schemas, deadline, turn_act, _shared,
│   └── nodes/         action/content/decision agent, debate_judge_agent
├── graph/             điều phối LangGraph
│   ├── meeting.py     graph cha
│   ├── topic.py       subgraph một chủ đề
│   └── state.py       state hai tầng
├── nodes/             logic từng bước, không biết hình dạng graph
│   ├── planner.py
│   ├── verifier.py
│   └── verifier_tools.py
├── actors/            định danh actor (người / đơn vị / unknown)
│   ├── attendees.py
│   ├── mentions.py
│   └── resolution.py
├── infra/
│   └── throttle.py
└── tests/
    ├── test_pipeline.py
    └── test_actors.py
```

| File | Vai trò |
|---|---|
| `config.py` | `V3Config`: các núm chỉnh (bỏ agent theo cue, số lần thử, số bước Verifier, số vòng đồng thuận, độ song song). |
| `schemas.py` | Kiểu dữ liệu riêng của v3: `SpeakerRegistry` (kèm `roster`), `ActorCandidate`, `ActionItemV3` (lớp con `ActionItemCandidate` của v1, thêm `actor_type`/`actor_candidates`/`actor_flag`/`actor_reason`), `TopicPlan`, `SkippedAgent`, `VerifierStep`, `ConsensusRound`, `VerificationRecord`, `VerifyTask`, `MeetingReport`. Candidate dùng lại kiểu của v1. |
| `runner.py` | `MeetingAnalyzerV3`: điểm vào cho tầng dịch vụ; `analyze()` trả `MeetingReport`. |
| `core/` | Bản chép các module v1 mà v3 dùng: kiểu candidate (`schemas.py`), chuẩn hoá hạn (`deadline.py`), bộ chấm lượt nói (`turn_act.py`), luật hậu kiểm (`_shared.py`), ba node trích xuất và phần dùng lại của debate/judge (`nodes/`). |
| `graph/meeting.py` | Graph cha: `plan_meeting` → dispatch song song → `finalize`. |
| `graph/topic.py` | Subgraph MỘT chủ đề: gán nhãn → trích xuất → evidence-check → Verifier. |
| `graph/state.py` | State LangGraph: `MeetingStateV3` (graph cha), `TopicInput`/`TopicOutput`/`TopicState` (subgraph). Các khoá kết quả cộng dồn bằng `operator.add`. |
| `nodes/planner.py` | Planner luật: dựng `SpeakerRegistry` và `TopicPlan` cho từng chủ đề. |
| `nodes/verifier.py` | Verifier ReAct + vòng đồng thuận với agent trích xuất. |
| `nodes/verifier_tools.py` | Tool CHỈ ĐỌC cho Verifier: `get_turn`, `search_meeting`, `lookup_speaker`. |
| `nodes/progress.py` | Agent tiến độ, kiểm cập nhật tiến độ, gộp tiến độ theo việc, quan hệ việc giao ↔ việc cũ (mục 4.6). |
| `nodes/progress_act.py` | Câu hỏi Decisions `progress_act` và `DecisionsProgressActJudge` (xét lượt nêu trạng thái). |
| `actors/attendees.py` | Danh sách người/đơn vị tham dự, đọc từ `<transcript>.attendees.json` (quy ước đặt tên). |
| `actors/agenda.py` | Danh sách việc cần báo cáo tiến độ, đọc từ `<transcript>.tasks.json` (quy ước đặt tên). |
| `actors/mentions.py` | Tách actor ghép thành các bên nhận việc kèm vai trò chủ trì / phối hợp / cùng thực hiện. |
| `actors/resolution.py` | Luật định danh actor: chấm điểm ứng viên (tên → ngữ cảnh → chức năng), `person`/`organization`/`unknown`. |
| `infra/throttle.py` | `LLMConcurrencyGate`: semaphore dùng chung bọc mọi adapter LLM. |
| `tests/test_pipeline.py` | Test end-to-end với LLM giả (không gọi mạng). |
| `tests/test_actors.py` | Test định danh actor và danh sách tham dự. |
| `tests/test_progress.py` | Test danh sách việc, agent tiến độ, kiểm bằng Decisions, gộp theo việc, quan hệ việc giao. |

---

## 4. Luồng xử lý chi tiết

### 4.1. Planner (`nodes/planner.py`) — luật, 0 token

Chạy **một lần** trước khi tách song song:

1. **`SpeakerRegistry`**: danh sách tên người nói không trùng của cả cuộc họp, theo thứ
   tự xuất hiện. Đưa vào prompt Action agent (ô `previous_context` của v1) và dùng làm
   `known_names` cho evidence-check. Khác v1: thấy cả người chỉ xuất hiện ở chủ đề sau,
   và tên do agent tự gán (có thể sai) không còn lan sang chủ đề sau. Có file
   `<transcript>.attendees.json` thì danh bạ kèm `roster` (người: họ tên, chức vị, đơn
   vị; đơn vị: tên, tên gọi tắt `aliases` tuỳ chọn, chức năng): prompt Action agent thấy cả
   đơn vị kèm tên gọi tắt, và tên người/đơn vị (cả tên gọi tắt)
   trong danh sách được coi là có căn cứ khi evidence-check (để "giao Sở Tài chính chủ
   trì" không bị loại). Việc mà actor khớp ≥ 2 ứng viên không ai đủ rõ (hai người tên
   Sơn) vẫn đi Verifier dù luật v1 coi là CLEAR.
2. **`TopicPlan`** cho từng chủ đề: chạy Action agent nếu có cụm trong `ACTION_CUES`
   ("giao", "phụ trách", "sẽ", "trước ngày"…), chạy Decision agent nếu có cụm trong
   `DECISION_CUES` ("chốt", "thống nhất", "kết luận"…). Cue cố ý **rộng**: bỏ nhầm làm
   giảm recall, còn chạy thừa chỉ tốn một lời gọi. Content agent không bao giờ bị bỏ.
   Tắt bằng `skip_agents_without_cues=False` (dùng cho ablation).
3. **Danh sách việc cần báo cáo** (`SpeakerRegistry.agenda`, file `<transcript>.tasks.json`
   hoặc `tasks` của API): có việc thì `TopicPlan.run_progress=True` ở MỌI chủ đề (agent tiến
   độ tự chọn việc nào chủ đề có nói tới, Planner không lọc theo từ khoá), và
   `format_registry_context` thêm khối "Việc cần báo cáo tiến độ" vào prompt. Action agent
   nhận thêm `ACTION_TASK_ID_RULE` và trường `task_id` trong schema (`extractors.py`) để ghi
   mã việc cũ. Không có việc thì không đổi gì: số lời gọi LLM, prompt và schema của Action
   agent đều giữ nguyên.

### 4.2. Subgraph một chủ đề (`graph/topic.py`)

1. **`label_topic`**: gán nhãn bằng stage07 (`label_topics`, có guard + fallback), dựng
   `SegmentTask` kiểu v1, ghi `SkippedAgent` cho agent bị Planner bỏ.
2. **Agent trích xuất** (dùng lại node v1, chạy song song theo `TopicPlan`):
   - `content_agent` → luận điểm theo người nói (Diễn biến họp),
   - `action_agent` → candidate việc giao,
   - `decision_agent` → candidate kết luận.

   Mỗi agent được bọc `_wrap_extractor`: lỗi LLM thì gọi lại tối đa `extract_attempts` lần
   ngay tại chỗ; chỉ lỗi của lần cuối được ghi vào `topic_failures`.
3. **`evidence_check`** (luật v1): tách candidate thành **CLEAR** (vào kết quả
   ngay) và **UNCERTAIN** (gửi Verifier, kèm lý do bị gắn cờ). Khi có `turn_judge`
   (`TURN_ACT_MODEL`), lượt chốt được xét theo nghĩa bằng OpenAI Decisions API
   (`core/turn_act.py`) thay cho từ khoá `_COMMIT_CUES`/`_HEDGE_CUES`:
   p_chốt ≥ 0.8 thì không gắn cờ, 0.2–0.8 gắn cờ "chưa rõ" kèm phân bố xác suất,
   < 0.2 gắn cờ "không phải lời chốt"; API lỗi thì quay về từ khoá. Đo trên 869 lượt
   gold của `eval/synthetic`: regex R=0.61 P=0.77, Decisions (p ≥ 0.5) R=0.93 P=0.86
   (`experiments/009_decisions_api`).
4. **`verifier`**: mỗi candidate UNCERTAIN được `Send` riêng, chạy song song.

Ba nhánh trích xuất nối thẳng vào `evidence_check` (không dùng join chờ đủ ba): số nhánh
thay đổi theo plan, nhưng mọi nhánh cách điểm phân nhánh đúng một bước nên LangGraph ghi
kết quả trong cùng một superstep và `evidence_check` chạy đúng một lần.

### 4.3. Verifier ReAct (`nodes/verifier.py`, `nodes/verifier_tools.py`)

ReAct dựng trên `LLMAdapter.generate_json` (một lượt hỏi–đáp JSON), **không cần provider
hỗ trợ tool calling**. Mỗi lượt model trả:

```json
{"thought", "action": "get_turn|search_meeting|lookup_speaker|final", "argument",
 "verdict": "keep|revise|drop|unresolved", "deciding_turn_id", "revised_actor",
 "revised_actor_type": "person|organization|unknown", "actor_reason", "reasoning"}
```

`deciding_turn_id` đứng trước `verdict` để model chỉ ra lượt giao/chốt trước khi kết luận.
Code chạy tool rồi đưa suy nghĩ, hành động và observation của mọi bước vào prompt lượt
sau. Tối đa `verifier_max_tool_calls + 1` lời gọi mỗi vòng; lượt cuối bắt buộc
`action="final"`. Tra lại y hệt một lần đã tra thì không chạy tool, chỉ báo lặp.

User prompt mở đầu bằng dòng người chủ trì; lý do candidate bị đánh dấu được ghi là
"cờ của bộ lọc tự động" (gợi ý, không phải bằng chứng). Tiêu chí là `VERIFY_RUBRICS`:
rubric v1 cộng `CHAIR_ASSIGNMENT_RULE`.

Tool (chỉ đọc, lỗi được trả thành observation để Verifier tự sửa, không raise):

| Tool | Chức năng |
|---|---|
| `get_turn(turn_id)` | Nguyên văn một lượt nói bất kỳ trong cả cuộc họp (cắt ở 600 ký tự). |
| `search_meeting(từ khoá)` | Top-k lượt nói khớp nhất cả cuộc họp; điểm = âm tiết nội dung trùng + 2 × cặp âm tiết trùng. |
| `lookup_speaker(cách gọi[ @turn_id])` | Ứng viên người/đơn vị cho "anh Phong", "Sơn @T12", "Sở Tài chính"… kèm điểm + lý do và dòng RÕ RÀNG/MƠ HỒ. |

**Định danh actor** (`actors/resolution.py`, luật 0 token). Điểm tên: họ tên/tên đơn
vị/tên gọi tắt trong `aliases`/tên người nói 1.0, một phần tên đơn vị 0.7, tên gọi 0.6, dạng tên đơn vị không có
trong danh sách 0.6. Ngữ cảnh (ưu tiên): người nói ngay sau lượt chốt +0.3, người giao
việc ở lượt chốt −0.3 (tự nhận thì +0.3). Chức năng (chỉ khi ngữ cảnh chưa phân định):
+0.1 mỗi âm tiết nội dung việc trùng chức vị/đơn vị/`functions`, tối đa +0.3. RÕ RÀNG
khi điểm đầu ≥ 0.6 và hơn thứ hai ≥ 0.2. Verifier chọn actor bằng `revised_actor` (đúng
tên một ứng viên) + `actor_reason`; lựa chọn ngoài danh sách ứng viên hoặc thiếu lý do
bị bỏ, dùng luật. Không rõ: `actor_type="unknown"`, giữ ứng viên, `actor_flag="ambiguous"`
(việc giao vẫn giữ). Việc không qua Verifier được định danh bằng luật ở `finalize`.

**Nhiều bên nhận việc** (`actors/mentions.py`): "Sở Tài chính chủ trì, phối hợp với Sở
Xây dựng" hoặc "Sở Tài chính (chủ trì), Sở Xây dựng (phối hợp)" → `assignees` = Sở Tài
chính (`lead`) + Sở Xây dựng (`support`); "A và B" không có từ vai trò → `joint`. Bên phối
hợp chỉ nêu trong nội dung việc được thêm nếu có trong danh sách tham dự. Tên có chữ "và"
không bị cắt: tên trong danh sách được giữ nguyên; tên ngoài danh sách thì vế sau "và"
không phải người/đơn vị nào được ghép lại. Mỗi bên định danh riêng; `actor` = tên các bên
nối ", ", `actor_type`/`actor_candidates` theo bên chính, `actor_flag` bật nếu có bên chưa
rõ. Verifier nêu nhiều bên thì MỌI bên phải là ứng viên có thật (đơn vị ngoài danh sách
phải có tên trong bản ghi), không thì bỏ cả lựa chọn.

Tên đơn vị được chuẩn hoá trước khi so: "UBND TP", "Ủy ban nhân dân Thành phố", "Ủy ban
Thành phố" cùng khớp "UBND Thành phố" (HĐND vẫn khác UBND).

**API**: `AnalyzeRequest.attendees` (tuỳ chọn, cùng dạng file `*.attendees.json`);
phản hồi `ActionItemV3Out` có `actor_type`, `actor_flag`, `actor_reason`,
`actor_candidates`, `assignees`. FE (tab Giao việc) xếp một việc dưới MỌI bên đã định danh
kèm tag vai trò, và hiện ứng viên + điểm ở nhóm "Chưa rõ người phụ trách".

**Luật hậu kiểm** (`_resolve_verdict` của v1): `keep`/`revise` mà không chỉ ra được lượt
nói giao/chốt (`deciding_turn_id` thuộc cuộc họp) thì hạ thành `drop`; `revise` chỉ nhận
actor định danh được. Khác v1: lượt chốt được phép nằm ở **chủ đề khác** vì tool thấy cả
cuộc họp.

### 4.4. Vòng đồng thuận Verifier ⇄ agent trích xuất

Thay cho bước duyệt người (đã bỏ 2026-10-08). Mỗi vòng:

```
Verifier (ReAct) ──► verdict + feedback
   │
   ├─ keep ─────────────────────────────────────► ĐỒNG THUẬN, giữ
   │
   └─ revise / drop / unresolved ─► agent trích xuất (action_llm / decision_llm)
            │
            ├─ accept ─► ĐỒNG THUẬN theo Verifier
            │             (revise: giữ bản sửa; drop/unresolved: bỏ)
            ├─ amend  ─► agent sửa candidate (text / actor / confirm_turn_id)
            │             ─► vòng sau Verifier xét bản đã sửa
            └─ defend ─► agent giữ nguyên, chỉ ra lượt chốt bị bỏ sót
                          ─► vòng sau Verifier xét lại kèm lập luận
```

- Prompt vòng sau của Verifier chứa lịch sử các vòng trước; Verifier được yêu cầu xét
  lập luận trên bản ghi, không nhượng bộ chỉ vì agent phản biện.
- Agent trích xuất thấy feedback và các bằng chứng Verifier đã tra (observation).
- Phần sửa của agent chỉ được nhận khi hợp lệ: `confirm_turn_id` phải là lượt nói thật,
  actor phải định danh được.
- `PROPOSER_SCHEMA` đặt `confirm_turn_id` trước `stance`. Khi Verifier không đề nghị
  sửa, `accept` mà vẫn chỉ ra lượt nói thật là tự mâu thuẫn (chọn nhãn trước rồi lập
  luận ngược lại) và được coi là `defend`.

**Kết thúc khi chưa đồng thuận** (hết `consensus_max_rounds`):

| Tình huống | Kết quả | `decided_by` | `verification` |
|---|---|---|---|
| Đồng thuận | keep/revise giữ, drop bỏ | `consensus` | `consensus` |
| Hết vòng, Verifier đã kết luận keep/revise/drop | theo kết luận cuối của Verifier | `verifier` | `verifier` |
| Hết vòng, Verifier vẫn `unresolved` | giữ candidate **gốc** | `fallback` | `fallback` |
| Lỗi LLM ở bất kỳ bước nào | giữ candidate **gốc** | `fallback` | `fallback` |

Nguyên tắc an toàn kế thừa từ v1: lỗi hạ tầng không được xoá nội dung đã trích. Bản agent
tự sửa mà Verifier chưa xét lại **không** được vào kết quả.

Mọi vòng được lưu trong `VerificationRecord.rounds` (`ConsensusRound`: candidate đã xét,
bước tra cứu, verdict, feedback, lượt chốt, lập trường, lập luận và lượt agent chỉ ra) để audit;
`VerificationRecord.steps` là mọi bước tra cứu nối qua các vòng.

### 4.5. `finalize` (`graph/meeting.py`)

Các chủ đề cộng dồn kết quả theo thứ tự **hoàn thành** (không xác định), nên `finalize`:

1. sắp lại mọi danh sách theo thứ tự chủ đề;
2. quy `actor` về đúng tên người nói nếu khớp duy nhất một người (`_normalize_actor`);
3. gộp việc giao / kết luận trùng giữa các chủ đề (`merge_duplicate_*` của v1, thay cho
   việc v1 truyền `known_assignments` để agent tự tránh lặp). Hai việc gắn với hai việc cũ
   khác nhau (`task_id`) không bao giờ bị gộp;
4. có danh sách việc: gán `relation` cho việc giao và gộp tiến độ theo việc (mục 4.6);
5. đóng gói `MeetingReport`.

### 4.6. Tiến độ các việc cần báo cáo (`nodes/progress.py`, `nodes/progress_act.py`)

Chỉ chạy khi phiên họp có danh sách việc (`actors/agenda.py`). Dạng file:

```json
{"tasks": [{"id": "T1", "title": "...", "owner": "O2", "support": ["O7"], "reporter": "P3",
            "due": "2026-01-31", "last_status": "in_progress", "source": "..."}]}
```

`id`/`title`/`owner` bắt buộc; `owner`/`support`/`reporter` là mã `P*`/`O*` trong attendees
(mã lạ → lỗi) hoặc tên tự do; `last_status` ∈ `not_started|in_progress|done|blocked`. Không có
trường từ khoá: việc được khớp với bản ghi theo nghĩa. Mẫu:
`inputs/bien-ban-vdt-trang-copy-v1.tasks.json`.

1. **Agent tiến độ** (`make_progress_agent`, node `progress_agent` rẽ từ `label_topic` như ba
   agent kia, thử lại bằng `_wrap_extractor`): MỘT lời gọi mỗi chủ đề, nhận CẢ danh sách việc,
   trả mỗi việc được nói tới một `ProgressUpdate`: `task_id` (enum mã việc), `status`
   (`done|in_progress|blocked|returned|deferred|mentioned`), `status_turn_id` (lượt nêu trạng
   thái), bằng chứng, hạn mới (cùng quy tắc chuẩn hoá với việc giao) hoặc `deadline_removed`,
   rồi `summary`/`blockers`/`directive` (văn bản tự do đứng cuối schema, có giới hạn độ dài).
   Prompt `PROGRESS_SYSTEM_PROMPT` có `SPEAKER_LABEL_RULE`: nhãn người nói có thể gộp nhiều
   người (bản ghi Cái Mép: một nhãn gồm cả người trình bày và người chủ trì), nên xét vai của
   lượt theo nội dung. Prompt cũng yêu cầu: nhắc chung cả đề án thì không tính là nói tới
   từng việc; lượt nêu trạng thái là lượt kết luận/chỉ đạo CUỐI CÙNG của người chủ trì nếu có;
   lượt nêu hạn mới/bỏ hạn phải nằm trong bằng chứng. Parser bỏ mục có mã việc lạ hoặc không có bằng chứng, gộp mục trùng mã
   (mục có trạng thái rõ làm mục chính). LLM: `progress_llm`, mặc định `action_llm`.
2. **Kiểm trong `evidence_check`** (`check_progress_updates`): hỏi Decisions (tên việc + 2 lượt
   ngữ cảnh + lượt cần xét, MỘT câu hỏi mỗi lời gọi; `TURN_ACT_QUESTION` giữ nguyên). Lượt
   dài hơn `MAX_TURN_CHARS` (2.500 ký tự) được cắt theo câu thành nhiều đoạn, mỗi đoạn một lời
   gọi, đoạn trước làm ngữ cảnh cho đoạn sau (`judge_turn_windows`); lượt ngữ cảnh dài chỉ giữ
   phần cuối. Các cập nhật của một chủ đề được kiểm song song.

   Câu hỏi tuỳ kiểu việc. Mỗi tên việc được xếp kiểu một lần (`TASK_KIND_QUESTION`, có cache):
   - việc chỉ là báo cáo tình hình cho cuộc họp (p ≥ `REPORT_TASK_MIN` = 0.8) dùng câu hỏi
     `report_act`: xong khi lượt nói trình bày nội dung việc yêu cầu. Tình hình của đối tượng
     được báo cáo (dự án "đang làm thủ tục") là nội dung báo cáo, không phải trạng thái của việc;
   - việc còn lại dùng câu hỏi chung `progress_act`.

   Cuộc họp Cái Mép, việc "Báo cáo tình hình các dự án cảng": lượt trả lời được `progress_act`
   xếp "đang làm" 0.92, `report_act` xếp "đã báo cáo" 0.99. Câu này chỉ chắc với việc báo cáo
   (1.00); tờ trình được 0.35, tiếp thu góp ý 0.03, việc báo cáo tiến độ giả lập 0.73, nên các
   việc đó vẫn dùng câu hỏi chung.

   Cập nhật có trạng thái: xét `status_turn_id` trước, rồi các lượt bằng chứng khác từ lượt muộn
   nhất (gemma đôi khi để `status_turn_id` null, hoặc chọn lượt kết luận chung trong khi câu nêu
   trạng thái nằm ở lượt bằng chứng khác).

   | Tình huống | Kết quả |
   |---|---|
   | một đoạn của một lượt xét cho p(trạng thái agent khai) ≥ 0.8 | giữ, ghi lượt đó, `verification="decisions"` |
   | không lượt nào xác nhận, lượt xét đầu tiên có trạng thái rõ khác với p ≥ 0.8 | sửa theo Decisions, `status_flag="revised"`. Ngoại lệ: câu hỏi chung không sửa từ trạng thái báo cáo (`done/in_progress/blocked`) sang trạng thái báo cáo khác |
   | agent khai trạng thái báo cáo, câu hỏi chung không xác nhận nhưng tổng nhóm báo cáo ≥ 0.8 ở lượt xét đầu tiên | giữ trạng thái agent khai, `status_flag="kept"` (vẫn tính là đã xác nhận khi gộp) |
   | còn lại / không có lượt nào để xét | hạ về `mentioned`, `status_flag="uncertain"`, giữ `proposed_status` |
   | `mentioned`: mọi lượt bằng chứng đều p(`khac`, "không nói về việc này") ≥ 0.8 | BỎ cập nhật (agent gắn nhầm việc); ghi log |
   | `mentioned`: lượt nói về việc là BÁO CÁO (`done/in_progress/blocked`) với p ≥ 0.8 | nâng lên trạng thái đó, `proposed_status="mentioned"`, `status_flag="revised"` |
   | `mentioned`: lượt nói về việc là `returned/deferred` với p ≥ 0.8 | chỉ nâng khi `turn_judge` cũng xếp lượt là chỉ đạo/kết luận (p_commit ≥ 0.8) |
   | `mentioned`: còn lại | giữ, `verification="decisions"` |
   | Decisions tắt hoặc lỗi | giữ nguyên điều agent khai, `verification="unchecked"` (không quay về từ khoá) |

   Vì sao không cho câu hỏi chung đổi giữa các trạng thái báo cáo: nó chấm theo nội dung cả lượt
   nên hay lấy tình trạng của đề án/dự án được nhắc thay cho tình trạng của việc. Ở cuộc họp Cái
   Mép, câu "đã giải trình, tiếp thu" của việc tiếp thu góp ý nằm trong đoạn 2.388 ký tự nói đề án
   "tiếp tục hoàn thiện", và Decisions xếp "đang làm" 0.89. Thử chữa bằng cách viết lại câu hỏi đều
   không qua được 0.8:
   - thêm sản phẩm của việc vào input: còn 0.72 "đang làm";
   - quy tắc "xét sản phẩm của việc" + viết lại mô tả lựa chọn: lên "xong" 0.63, nhưng lượt "tờ
     trình phải làm lại" tụt từ 0.87 xuống 0.75;
   - đoạn 800 ký tự quanh câu đó: "xong" 0.60.

   Agent đọc cả chủ đề nên được quyết xong hay đang làm. Decisions vẫn quyết lượt là báo cáo,
   chỉ đạo hay chỉ nhắc.

   "mentioned" được xét từ lượt bằng chứng muộn nhất và dừng ở lượt đầu tiên có nói về việc.
   Báo cáo tự đứng được trong một lượt nên được nâng thẳng. Yêu cầu làm lại/hoãn thì cần biết
   người chủ trì có chấp nhận không, mà Decisions chỉ thấy 2 lượt trước; câu hỏi `turn_act` (đã
   hiệu chỉnh) phân biệt chỉ đạo của người chủ trì với kiến nghị của đại biểu, nên được dùng làm
   cổng (cuộc họp Cái Mép: đề nghị của Thông ở lượt 26 không được biến T3 đã xong thành
   "returned"). Ngưỡng 0.8 là TẠM (mượn từ `turn_act`), chưa hiệu chỉnh cho câu hỏi này. Có
   `turn_judge` thì ghi thêm `p_directive` (xác suất lượt nêu trạng thái là chỉ đạo/kết luận).
   Việc trong danh sách không bao giờ bị xoá (không còn cập nhật thì `not_reported`); pha này
   chưa đưa cập nhật tiến độ qua Verifier ReAct.
3. **Gộp theo việc trong `finalize`** (`summarize_task_progress`): mỗi việc một `TaskProgress`.
   Cập nhật thắng: trong các cập nhật có trạng thái rõ, lượt chỉ đạo/kết luận
   (`p_directive` ≥ 0.8) thắng lượt báo cáo, cùng loại thì lượt muộn hơn thắng; **không dựa
   vào tên người nói**. `status_conflict` chỉ khi có báo cáo `done` đã xác nhận cùng một trạng
   thái rõ khác (vd. báo cáo xong rồi chủ trì yêu cầu làm lại); "đang làm" rồi bị trả lại là
   diễn tiến, không phải mâu thuẫn. `not_reported` khi không chủ đề nào nói tới; `overdue` khi
   hạn cũ < ngày họp mà việc chưa xong.
4. **Việc giao ↔ việc cũ** (`link_assignment_to_agenda`): có danh sách việc thì Action agent nhận
   `ACTION_TASK_ID_RULE` và trường `task_id` (enum mã việc + `"new"`, đứng ngay sau `text`); parser
   đổi `"new"` thành None. Chỉ ghi mã khi việc giao là CHÍNH việc đó: làm tiếp, làm lại cả việc,
   giao bên khác, đổi hạn. Nội dung, phân tích hay sản phẩm mới phát sinh trong phiên là `"new"`,
   kể cả khi phục vụ việc cũ. Ở Cái Mép, bản luật cũ có chữ "bổ sung" nên mọi yêu cầu bổ sung đề
   án đều bị gắn vào việc trình tờ trình; người gán gold coi đó là việc mới của phiên.
   `finalize` gán `relation` theo các trường, không so khớp chữ: không
   có/mã lạ → `new`; việc do người khác giao (không phải `self_committed`/`reported`) mà mọi bên
   nhận việc đã định danh đều ngoài bên chủ trì/phối hợp cũ → `reassign`; hạn mới khác hạn cũ →
   `reschedule`; còn lại → `follow_up`. Định danh actor không cộng điểm cho bên chủ trì cũ (để
   không che mất trường hợp giao lại).

Chi phí: thêm 1 lời gọi LLM mỗi chủ đề. Decisions:
- mỗi lượt được xét tốn 1 lời gọi cho mỗi đoạn (dừng sớm khi xác nhận được, hoặc khi gặp lượt
  nói về việc với "mentioned");
- thêm 1 lời gọi xếp kiểu việc cho mỗi việc được xét;
- thêm `turn_judge` cho lượt nêu trạng thái (có cache).

Cuộc họp Cái Mép (32 lượt, 3 chủ đề, 4 việc): 20 lời gọi Decisions cả cuộc họp, so với 13 khi
không có danh sách việc.

---

## 5. Dữ liệu và state

### 5.1. State

- **`MeetingStateV3`** (graph cha): đầu vào (`meeting_id`, `revision_id`, `meeting_date`,
  `chair`, `segments`, `turns_by_id`, `attendee_roster`, `task_agenda`), kết quả Planner (`registry`, `plans`), các khoá cộng dồn của
  `TopicOutput`, và `report`.
- **`TopicInput`** (gói `Send`): `segment`, `turns` của chủ đề, `meeting_turns` của cả
  cuộc họp (cho tool Verifier), `registry`, `plan`.
- **`TopicOutput`** (khoá subgraph trả về, reducer `operator.add`): `labels`,
  `meeting_development`, `verified_assignments`, `verified_decisions`,
  `verification_records`, `topic_failures`, `skipped_agents`, `progress_updates` (đã kiểm).
- **`TopicState`**: thêm `task` (SegmentTask v1), `action_candidates_raw`,
  `decision_candidates_raw`, `progress_updates_raw`, `pending_verify` (ghi đè).

### 5.2. `MeetingReport` (đầu ra)

| Trường | Nội dung |
|---|---|
| `labels` | Nhãn chủ đề theo thứ tự |
| `meeting_development` | Luận điểm theo người nói (Diễn biến họp) |
| `assignments` | Việc giao đã kiểm chứng (Giao việc) |
| `decisions` | Kết luận đã kiểm chứng (Kết luận họp) |
| `verification_records` | Bản ghi kiểm chứng + các vòng đồng thuận |
| `failures` | Lời gọi trích xuất vẫn lỗi sau mọi lượt thử |
| `skipped_agents` | Agent bị Planner bỏ qua (để đo recall) |
| `task_progress` | Tiến độ từng việc trong danh sách việc cần báo cáo (rỗng nếu không có danh sách) |

Giá trị `verification` của candidate: `rule` (CLEAR qua evidence-check), `consensus`,
`verifier`, `fallback`.

---

## 6. Đồng thời và hiệu năng

Hai lớp giới hạn độc lập:

1. **`V3Config.max_concurrency`** → `max_concurrency` của LangGraph: số task (chủ đề +
   verifier) chạy cùng lúc mỗi superstep.
2. **`LLMConcurrencyGate`** (`infra/throttle.py`): `BoundedSemaphore` dùng chung bọc **mọi**
   adapter (gán nhãn, 3 agent, Verifier, trả lời feedback). Đây mới là giới hạn số lời gọi
   LLM thực sự. Verifier có thể có gate riêng (`verifier_llm_concurrency`) khi trỏ tới
   backend khác.

Lưu ý: gate phải ≤ `OPENAI_MAX_CONNECTIONS` của client httpx, nếu không gate lớn hơn cũng
vô tác dụng. Thời gian "LLM call done in Xs" trong log gồm cả thời gian chờ gate.

**Ngân sách LLM mỗi candidate UNCERTAIN**: tối đa
`consensus_max_rounds × (verifier_max_tool_calls + 2)` lời gọi (mặc định 3 × 5 = 15).
Thường ít hơn nhiều: Verifier hay kết luận sau 1–2 lời gọi và agent trích xuất thường
`accept` ngay vòng đầu.

**Số đo** (2026-10-08, `inputs/bien-ban-tong-hop-v1.json`, 1259 lượt, 14 chủ đề, **trước**
khi có vòng đồng thuận, Verifier = DeepSeek): ~78 s tổng (cắt chủ đề dialstart 12 s).
Chưa đo lại với vòng đồng thuận và Verifier gpt-4o-mini.

---

## 7. Cấu hình

### 7.1. `V3Config`

| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `skip_agents_without_cues` | `True` | Planner bỏ Action/Decision khi không có cue |
| `extract_attempts` | `2` | Số lần gọi tối đa mỗi agent trích xuất |
| `verifier_max_tool_calls` | `3` | Số lần gọi tool mỗi vòng Verifier |
| `search_top_k` | `5` | Số lượt nói `search_meeting` trả về |
| `consensus_max_rounds` | `3` | Số vòng Verifier ⇄ agent trích xuất tối đa |
| `max_concurrency` | `16` | Số task LangGraph song song |

### 7.2. Biến môi trường (tầng dịch vụ `be/services/pipeline_v3.py`)

| Biến | Ý nghĩa |
|---|---|
| `V3_SKIP_AGENTS_WITHOUT_CUES`, `V3_EXTRACT_ATTEMPTS`, `V3_VERIFIER_MAX_TOOL_CALLS`, `V3_CONSENSUS_MAX_ROUNDS`, `V3_MAX_CONCURRENCY` | Ghi đè `V3Config` |
| `V3_LLM_CONCURRENCY` | Kích thước gate dùng chung (mặc định 8) |
| `VERIFIER_MODEL_NAME`, `VERIFIER_BASE_URL`, `VERIFIER_API_KEY` | Backend riêng cho Verifier (để trống = dùng chung LLM chính) |
| `VERIFIER_RESPONSE_MODE` | `json_schema` (OpenAI strict) hoặc `json_object` |
| `VERIFIER_LLM_CONCURRENCY` | Gate riêng của Verifier |
| `VERIFIER_THINKING` | `enabled`/`disabled` cho DeepSeek; để trống với OpenAI |
| `TURN_ACT_MODEL` | Model Decisions (`gpt-6-luna`) xét lượt chốt theo nghĩa, và lượt nêu trạng thái tiến độ (chung client); để trống = luật từ khoá cho lượt chốt, tiến độ giữ trạng thái agent khai (`unchecked`) |
| `TURN_ACT_API_KEY`, `TURN_ACT_BASE_URL`, `TURN_ACT_TIMEOUT_SECONDS` | Key (mặc định `VERIFIER_API_KEY` rồi `OPENAI_API_KEY`), endpoint (mặc định `api.openai.com`), timeout (10s) |

Cấu hình hiện tại: agent trích xuất + gán nhãn = gemma (server riêng), Verifier =
`gpt-4o-mini` (`json_schema`). `be/main.py` nạp `.env` với `override=True` nên `.env`
thắng biến cũ còn export trong shell.

---

## 8. Tích hợp

- **Điểm vào**: `MeetingAnalyzerV3(content_llm, action_llm, decision_llm, verifier_llm,
  labeler, …, progress_llm=None, progress_judge=None).analyze(meeting_id, revision_id, meeting_date,
  chair, turns, segments, attendee_roster=None, task_agenda=None) -> MeetingReport`.
  `chair` (tùy chọn) là tên người chủ trì; `task_agenda` (tùy chọn) bật agent tiến độ.
  Graph compile một lần, dùng cho mọi cuộc họp; analyzer sống suốt vòng đời ứng dụng
  để mọi request dùng chung một gate.
- **API**: `POST /v3/meetings/analyze` (`be/routers/meetings_v3.py`) nhận `AnalyzeV3Request`
  (transcript + `meeting_date`, `chair`, `attendees`, `tasks` tùy chọn) → `AnalyzeV3Result`
  (`topics`, `verified_assignments` kèm `task_id`/`relation`, `verified_decisions`,
  `task_progress`, `turns`, `failed_topics`, `verification_records` kèm `rounds`,
  `skipped_agents`). `attendees`/`tasks` sai dạng (vd. mã đơn vị không có) → 422, kiểm trước
  khi cắt chủ đề. Cắt chủ đề (stage01–03 +
  segmenter) dùng chung với v1 qua `segment_meeting`.
- **FE**: ô "Chủ trì" ở màn nhập (dùng chung với MA-MRG) gửi kèm `chair`; `useV3Analysis` gọi một lần; `VerifierRecordsBlock` hiển thị chuỗi tra cứu và
  các vòng feedback, có bộ lọc "Chưa đồng thuận". Ô "Việc cần báo cáo tiến độ" (JSON/tệp
  `*.tasks.json`) gửi kèm `tasks`; tab "Tiến độ" (`TaskProgressBlock`) hiện mỗi việc một thẻ
  (trạng thái cũ → mới, hạn, cờ mâu thuẫn/chưa xác nhận/quá hạn, các cập nhật bấm được để tô
  bằng chứng); tab Giao việc có nhãn quan hệ (Việc mới / Tiếp nối / Giao lại / Đổi hạn).

---

## 9. Kiểm thử

`src/agentic_v3/tests/test_pipeline.py` (13 test, LLM giả nhận vai qua schema/system prompt):
Planner bỏ agent đúng chỗ; tool đọc cả cuộc họp và trả lỗi thành observation; chủ đề chạy
song song nhưng không vượt gate; Verifier tra tool rồi kết luận; luật hạ `keep` không có
lượt chốt thành `drop`; agent `amend` rồi Verifier đồng ý; agent `accept` thì bỏ; hết vòng
thì theo Verifier; vẫn `unresolved` thì giữ fallback; lỗi LLM giữ bản gốc; thử lại agent
tại chỗ; agent trích xuất chạy với prompt v3; người chủ trì được quy về người nói và có
trong prompt; kết quả sắp theo thứ tự chủ đề.

`src/agentic_v3/tests/test_progress.py`: đọc danh sách việc (tra mã, tên tự do, các lỗi, quy
ước đặt tên, file mẫu khớp attendees mẫu); Planner chỉ bật agent tiến độ khi có danh sách;
parser agent tiến độ (mã lạ, lượt ngoài chủ đề, gộp trùng, lỗi LLM); kiểm bằng Decisions (giữ /
sửa / hạ / lỗi → `unchecked`); gộp theo việc (chỉ đạo thắng báo cáo, lượt muộn thắng, mâu
thuẫn, `not_reported`, quá hạn); `relation`; không gộp việc giao của hai việc cũ khác nhau;
end-to-end có/không có danh sách việc (không có thì không thêm lời gọi nào).

`be/test_api_v3.py`: wiring HTTP end-to-end, gồm luồng đồng thuận trong một request,
`chair` tới được mọi prompt, `tasks` → `task_progress` + `relation`, và `tasks` sai dạng → 422.

---

## 10. Rủi ro và việc còn mở

1. **Chưa đo chất lượng trên gold thật** (`experiments/007_dialtreeseg/gold`). Các giả định
   rủi ro nhất chưa được kiểm:
   - `SpeakerRegistry` thay `known_names` chạy dồn không làm giảm chất lượng actor;
   - bỏ agent theo cue không mất recall (đo bằng `skip_agents_without_cues=False`);
   - vòng đồng thuận không khiến agent "nhượng bộ" sai, hoặc Verifier nhượng bộ trước
     agent phản biện.
2. **Agent trả lời feedback chạy trên gemma**, từng gặp lỗi JSON: trích nguyên văn bằng
   `"`, và sinh khoảng trắng vô tận khi trường văn bản tự do không đứng cuối schema.
   Đã giảm bằng prompt (≤ 2 câu, không dùng dấu nháy kép) và đặt `argument` cuối
   `PROPOSER_SCHEMA` (`confirm_turn_id` đứng đầu, là mã ngắn nên không gây lỗi này). Phương án dự phòng: cho bước này chạy trên `gpt-4o-mini`, đổi lại
   agent trả lời không còn là chính model đã trích ra candidate.
3. **Chi phí**: vòng đồng thuận có thể tăng số lời gọi lên tới 15 mỗi candidate nghi ngờ;
   cần đo phân bố số vòng thực tế.
4. **Lỗi 402 (hết số dư) vẫn bị retry** ở adapter dù không bao giờ thành công; nên coi
   402 là lỗi không retry.
5. Prompt của Verifier khá dài (20–40 nghìn ký tự với chủ đề lớn) vì chứa nguyên bản ghi
   đoạn và lịch sử tra cứu; có thể cắt bớt nếu chi phí là vấn đề.
6. **Tiến độ mới có gold cho MỘT cuộc họp** (`inputs/bien-ban-vdt-trang-copy-v1.progress-gold.json`).
   - **Input v1 sai:** 3 trong 6 việc (Cần Giờ, cơ chế đặc thù, ĐMC) thực ra là việc phát sinh
     trong chính phiên họp, mình đã chiếu ngược thành "việc cũ". Input v2 (2026-10-12) chỉ giữ việc
     có dấu vết được giao trước phiên (T1, T3, T5), cộng X1 là việc giả lập không có trong cuộc họp
     để đo `not_reported`. Nội dung Cần Giờ và cơ chế đặc thù chuyển thành việc giao `new` trong gold.
   - **Kết quả trên input v2:**
     - 3 lần gọi lặp agent trên chủ đề đã cắt sẵn và 1 lần chạy cả pipeline đều khớp 4/4 việc;
     - việc giao: "làm lại tờ trình" ra `follow_up T1`, các việc phát sinh trong phiên ra `new`.
   - **Kết quả trên input v1 (đã bỏ):** ba lần chạy cả pipeline đều khớp 3/6 việc nhưng không cùng 3
     việc. Gemma dao động dù temperature 0, và mỗi lần chạy lại cắt chủ đề nên prompt cũng đổi.
     Muốn so hai bản prompt thì gọi lặp agent trên cùng chủ đề đã cắt sẵn. Decisions thì cho cùng
     kết quả với cùng input.
   - **Còn mở:**
     - Ngưỡng `progress_act` và `REPORT_TASK_MIN` (0.8) chưa hiệu chỉnh. Ngưỡng kiểu việc mới đo
       trên vài tên việc.
     - Với việc làm ra sản phẩm, xong hay đang làm giờ do agent quyết (cờ `kept`) khi Decisions
       chỉ xác nhận là báo cáo, nên lỗi của gemma ở chỗ này không còn bị bắt.
     - Ranh giới "chính việc đó" và "việc mới phục vụ việc đó" trong `ACTION_TASK_ID_RULE` mới
       được người gán xác nhận trên một cuộc họp.
7. **Nhãn người nói gộp nhiều người** (vấn đề có sẵn của diarization): xếp ưu tiên theo loại
   lượt (Decisions) chỉ giảm ảnh hưởng, không sửa gốc; một lượt dài có thể chứa cả câu hỏi của
   chủ trì lẫn câu trả lời của người trình bày. Dòng "Người chủ trì" trong prompt cũng khiến lời
   người trình bày cùng nhãn bị đọc như lời chủ trì.
8. **Pha 2 (chưa làm)**: Verifier thêm loại "progress" (kết luận giữ / đổi trạng thái / thiếu
   căn cứ, không bao giờ xoá việc; tool `lookup_task`), và lọc việc theo chủ đề bằng Decisions
   nếu danh sách việc quá dài (> ~30 việc).
