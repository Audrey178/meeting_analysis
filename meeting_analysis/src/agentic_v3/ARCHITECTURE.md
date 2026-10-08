# Kiến trúc `src/agentic_v3`

Báo cáo kiến trúc pipeline agentic v3: phân tích biên bản họp (Diễn biến họp, Giao việc,
Kết luận họp) sau khi transcript đã được tách lượt nói và cắt chủ đề.

Cập nhật: 2026-10-08 (đã bỏ bước duyệt người, thay bằng vòng đồng thuận Verifier ⇄ agent trích xuất).

---

## 1. Mục tiêu và khác biệt so với v1

| | v1 (`src/agentic`) | v3 (`src/agentic_v3`) |
|---|---|---|
| Thứ tự chủ đề | Tuần tự: chủ đề N xong hẳn mới gửi N+1 | **Song song**: mọi chủ đề cùng lúc (`Send` → subgraph) |
| Ngữ cảnh giữa chủ đề | `known_names`/`known_assignments` chạy dồn | `SpeakerRegistry` của cả cuộc họp, dựng 1 lần trước |
| Gán nhãn chủ đề | Chạy hết stage07 trước | Ngay trong subgraph, chủ đề nào có nhãn thì trích xuất luôn |
| Chọn agent | Luôn chạy đủ 3 agent | **Planner** (luật, 0 token) bỏ Action/Decision khi không có cue |
| Kiểm chứng candidate nghi ngờ | Debate + Judge (3 lời gọi, chỉ đọc đoạn hiện tại) | **Verifier ReAct** có tool tra **cả cuộc họp** |
| Khi chưa chắc | Giữ theo luật an toàn | **Vòng đồng thuận** Verifier ⇄ agent trích xuất |
| Thử lại lỗi LLM | Sau chủ đề cuối (`retry_failed_topics`) | Ngay trong chủ đề (`extract_attempts`) |
| Giới hạn đồng thời | — | `LLMConcurrencyGate` dùng chung cả tiến trình |

Lý do chính: nút thắt thời gian của v1 là vòng lặp tuần tự theo chủ đề, tồn tại chỉ để
mang `known_names` sang chủ đề sau. v3 thay ngữ cảnh đó bằng danh bạ dựng sẵn nên các
chủ đề độc lập với nhau, và tổng thời gian không còn tăng tuyến tính theo số chủ đề.

v3 dùng lại nguyên các agent trích xuất, rubric và luật hậu kiểm của v1 (import từ
`src.agentic`), **không sửa gì ở v1**.

---

## 2. Sơ đồ tổng thể

```
                     ┌──────────────────── graph cha (graph.py) ────────────────────┐
                     │                                                              │
 turns + segments ──►│ START ─► plan_meeting ─► Send("topic", chủ đề i) cho MỌI i   │
                     │          (luật, 0 token)        │  │  │   (song song)        │
                     │                                 ▼  ▼  ▼                      │
                     │                       ┌── subgraph topic (topic_graph.py) ─┐ │
                     │                       │ label_topic                        │ │
                     │                       │   ├─► content_agent ──────────┐    │ │
                     │                       │   ├─► action_agent   (nếu plan)├─► evidence_check
                     │                       │   └─► decision_agent (nếu plan)┘    │ │
                     │                       │          CLEAR ─► kết quả          │ │
                     │                       │          UNCERTAIN ─► Send ─► verifier (0..N)
                     │                       │                 (Verifier ⇄ agent trích xuất)
                     │                       └────────────────────────────────────┘ │
                     │                                 │                            │
                     │                                 ▼                            │
                     │                    finalize ─► END ─► MeetingReport          │
                     └──────────────────────────────────────────────────────────────┘
```

Graph chạy **một mạch** từ START tới END, không dừng chờ người, nên không cần checkpointer.

---

## 3. Các module

| File | Vai trò |
|---|---|
| `config.py` | `V3Config`: các núm chỉnh (bỏ agent theo cue, số lần thử, số bước Verifier, số vòng đồng thuận, độ song song). |
| `schemas.py` | Kiểu dữ liệu riêng của v3: `SpeakerRegistry`, `TopicPlan`, `SkippedAgent`, `VerifierStep`, `ConsensusRound`, `VerificationRecord`, `VerifyTask`, `MeetingReport`. Candidate dùng lại kiểu của v1. |
| `state.py` | State LangGraph: `MeetingStateV3` (graph cha), `TopicInput`/`TopicOutput`/`TopicState` (subgraph). Các khoá kết quả cộng dồn bằng `operator.add`. |
| `planner.py` | Planner luật: dựng `SpeakerRegistry` và `TopicPlan` cho từng chủ đề. |
| `topic_graph.py` | Subgraph MỘT chủ đề: gán nhãn → trích xuất → evidence-check → Verifier. |
| `verifier.py` | Verifier ReAct + vòng đồng thuận với agent trích xuất. |
| `tools.py` | Tool CHỈ ĐỌC cho Verifier: `get_turn`, `search_meeting`, `lookup_speaker`. |
| `graph.py` | Graph cha: `plan_meeting` → dispatch song song → `finalize`. |
| `throttle.py` | `LLMConcurrencyGate`: semaphore dùng chung bọc mọi adapter LLM. |
| `runner.py` | `MeetingAnalyzerV3`: điểm vào cho tầng dịch vụ; `analyze()` trả `MeetingReport`. |
| `tests/test_v3.py` | Test end-to-end với LLM giả (không gọi mạng). |

---

## 4. Luồng xử lý chi tiết

### 4.1. Planner (`planner.py`) — luật, 0 token

Chạy **một lần** trước khi tách song song:

1. **`SpeakerRegistry`**: danh sách tên người nói không trùng của cả cuộc họp, theo thứ
   tự xuất hiện. Đưa vào prompt Action agent (ô `previous_context` của v1) và dùng làm
   `known_names` cho evidence-check. Khác v1: thấy cả người chỉ xuất hiện ở chủ đề sau,
   và tên do agent tự gán (có thể sai) không còn lan sang chủ đề sau.
2. **`TopicPlan`** cho từng chủ đề: chạy Action agent nếu có cụm trong `ACTION_CUES`
   ("giao", "phụ trách", "sẽ", "trước ngày"…), chạy Decision agent nếu có cụm trong
   `DECISION_CUES` ("chốt", "thống nhất", "kết luận"…). Cue cố ý **rộng**: bỏ nhầm làm
   giảm recall, còn chạy thừa chỉ tốn một lời gọi. Content agent không bao giờ bị bỏ.
   Tắt bằng `skip_agents_without_cues=False` (dùng cho ablation).

### 4.2. Subgraph một chủ đề (`topic_graph.py`)

1. **`label_topic`**: gán nhãn bằng stage07 (`label_topics`, có guard + fallback), dựng
   `SegmentTask` kiểu v1, ghi `SkippedAgent` cho agent bị Planner bỏ.
2. **Agent trích xuất** (dùng lại node v1, chạy song song theo `TopicPlan`):
   - `content_agent` → luận điểm theo người nói (Diễn biến họp),
   - `action_agent` → candidate việc giao,
   - `decision_agent` → candidate kết luận.

   Mỗi agent được bọc `_wrap_extractor`: lỗi LLM thì gọi lại tối đa `extract_attempts` lần
   ngay tại chỗ; chỉ lỗi của lần cuối được ghi vào `topic_failures`.
3. **`evidence_check`** (luật v1, 0 token): tách candidate thành **CLEAR** (vào kết quả
   ngay) và **UNCERTAIN** (gửi Verifier, kèm lý do bị gắn cờ).
4. **`verifier`**: mỗi candidate UNCERTAIN được `Send` riêng, chạy song song.

Ba nhánh trích xuất nối thẳng vào `evidence_check` (không dùng join chờ đủ ba): số nhánh
thay đổi theo plan, nhưng mọi nhánh cách điểm phân nhánh đúng một bước nên LangGraph ghi
kết quả trong cùng một superstep và `evidence_check` chạy đúng một lần.

### 4.3. Verifier ReAct (`verifier.py`, `tools.py`)

ReAct dựng trên `LLMAdapter.generate_json` (một lượt hỏi–đáp JSON), **không cần provider
hỗ trợ tool calling**. Mỗi lượt model trả:

```json
{"thought", "action": "get_turn|search_meeting|lookup_speaker|final", "argument",
 "verdict": "keep|revise|drop|unresolved", "deciding_turn_id", "revised_actor", "reasoning"}
```

Code chạy tool rồi đưa observation vào prompt lượt sau. Tối đa
`verifier_max_tool_calls + 1` lời gọi mỗi vòng; lượt cuối bắt buộc `action="final"`.

Tool (chỉ đọc, lỗi được trả thành observation để Verifier tự sửa, không raise):

| Tool | Chức năng |
|---|---|
| `get_turn(turn_id)` | Nguyên văn một lượt nói bất kỳ trong cả cuộc họp (cắt ở 600 ký tự). |
| `search_meeting(từ khoá)` | Top-k lượt nói khớp nhất cả cuộc họp; điểm = âm tiết nội dung trùng + 2 × cặp âm tiết trùng. |
| `lookup_speaker(cách gọi)` | Quy "anh Phong", "Sơn"… về người nói thật trong danh bạ. |

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
bước tra cứu, verdict, feedback, lượt chốt, lập trường và lập luận của agent) để audit;
`VerificationRecord.steps` là mọi bước tra cứu nối qua các vòng.

### 4.5. `finalize` (`graph.py`)

Các chủ đề cộng dồn kết quả theo thứ tự **hoàn thành** (không xác định), nên `finalize`:

1. sắp lại mọi danh sách theo thứ tự chủ đề;
2. quy `actor` về đúng tên người nói nếu khớp duy nhất một người (`_normalize_actor`);
3. gộp việc giao / kết luận trùng giữa các chủ đề (`merge_duplicate_*` của v1, thay cho
   việc v1 truyền `known_assignments` để agent tự tránh lặp);
4. đóng gói `MeetingReport`.

---

## 5. Dữ liệu và state

### 5.1. State

- **`MeetingStateV3`** (graph cha): đầu vào (`meeting_id`, `revision_id`, `segments`,
  `turns_by_id`), kết quả Planner (`registry`, `plans`), các khoá cộng dồn của
  `TopicOutput`, và `report`.
- **`TopicInput`** (gói `Send`): `segment`, `turns` của chủ đề, `meeting_turns` của cả
  cuộc họp (cho tool Verifier), `registry`, `plan`.
- **`TopicOutput`** (khoá subgraph trả về, reducer `operator.add`): `labels`,
  `meeting_development`, `verified_assignments`, `verified_decisions`,
  `verification_records`, `topic_failures`, `skipped_agents`.
- **`TopicState`**: thêm `task` (SegmentTask v1), `action_candidates_raw`,
  `decision_candidates_raw`, `pending_verify` (ghi đè).

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

Giá trị `verification` của candidate: `rule` (CLEAR qua evidence-check), `consensus`,
`verifier`, `fallback`.

---

## 6. Đồng thời và hiệu năng

Hai lớp giới hạn độc lập:

1. **`V3Config.max_concurrency`** → `max_concurrency` của LangGraph: số task (chủ đề +
   verifier) chạy cùng lúc mỗi superstep.
2. **`LLMConcurrencyGate`** (`throttle.py`): `BoundedSemaphore` dùng chung bọc **mọi**
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

Cấu hình hiện tại: agent trích xuất + gán nhãn = gemma (server riêng), Verifier =
`gpt-4o-mini` (`json_schema`). `be/main.py` nạp `.env` với `override=True` nên `.env`
thắng biến cũ còn export trong shell.

---

## 8. Tích hợp

- **Điểm vào**: `MeetingAnalyzerV3(content_llm, action_llm, decision_llm, verifier_llm,
  labeler, …).analyze(meeting_id, revision_id, turns, segments) -> MeetingReport`.
  Graph compile một lần, dùng cho mọi cuộc họp; analyzer sống suốt vòng đời ứng dụng
  để mọi request dùng chung một gate.
- **API**: `POST /v3/meetings/analyze` (`be/routers/meetings_v3.py`) → `AnalyzeV3Result`
  (`topics`, `verified_assignments`, `verified_decisions`, `turns`, `failed_topics`,
  `verification_records` kèm `rounds`, `skipped_agents`). Cắt chủ đề (stage01–03 +
  segmenter) dùng chung với v1 qua `segment_meeting`.
- **FE**: `useV3Analysis` gọi một lần; `VerifierRecordsBlock` hiển thị chuỗi tra cứu và
  các vòng feedback, có bộ lọc "Chưa đồng thuận".

---

## 9. Kiểm thử

`src/agentic_v3/tests/test_v3.py` (13 test, LLM giả nhận vai qua schema/system prompt):
Planner bỏ agent đúng chỗ; tool đọc cả cuộc họp và trả lỗi thành observation; chủ đề chạy
song song nhưng không vượt gate; Verifier tra tool rồi kết luận; luật hạ `keep` không có
lượt chốt thành `drop`; agent `amend` rồi Verifier đồng ý; agent `accept` thì bỏ; hết vòng
thì theo Verifier; vẫn `unresolved` thì giữ fallback; lỗi LLM giữ bản gốc; thử lại agent
tại chỗ; kết quả sắp theo thứ tự chủ đề.

`be/test_api_v3.py` (2 test): wiring HTTP end-to-end, gồm luồng đồng thuận trong một request.

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
   `PROPOSER_SCHEMA`. Phương án dự phòng: cho bước này chạy trên `gpt-4o-mini`, đổi lại
   agent trả lời không còn là chính model đã trích ra candidate.
3. **Chi phí**: vòng đồng thuận có thể tăng số lời gọi lên tới 15 mỗi candidate nghi ngờ;
   cần đo phân bố số vòng thực tế.
4. **Lỗi 402 (hết số dư) vẫn bị retry** ở adapter dù không bao giờ thành công; nên coi
   402 là lỗi không retry.
5. Prompt của Verifier khá dài (20–40 nghìn ký tự với chủ đề lớn) vì chứa nguyên bản ghi
   đoạn và lịch sử tra cứu; có thể cắt bớt nếu chi phí là vấn đề.
