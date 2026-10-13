# Bộ test tổng hợp (30 transcript) cho pipeline `be/`

Mục tiêu: đánh giá pipeline ở 2 chỗ mà **không cần gán nhãn tay**:

1. **Cắt chủ đề**: so ranh giới dự đoán với gold (Pk, WD, F1@2k/5k của
   `experiments/007_dialtreeseg/metrics.py`), cộng LLM judge.
2. **Output cuối** (Diễn biến họp / Giao việc / Kết luận họp): so với gold việc giao,
   quyết định và ý chính cài sẵn, cộng LLM judge chấm Likert.

Toàn bộ transcript do Claude Code viết. Gold được **cài sẵn lúc viết**: ranh giới chủ đề,
tiêu đề, việc giao, quyết định và các "bẫy". Vì vậy gold biết chính xác, không phải suy
luận ngược.

## Cấu trúc

```
eval/synthetic/
  specs/synth_XXX.md        # nguồn viết tay: meta + chủ đề + lượt nói + gold
  build.py                  # spec -> transcripts/ + gold/ + manifest.json (tất định)
  transcripts/synth_XXX.json  # đúng schema inputs/bien-ban-*-v1.json, gửi thẳng vào API
  gold/synth_XXX.json
  manifest.json
```

`python eval/synthetic/build.py [synth_XXX ...]`

`build.py` chạy chính stage01–03 của pipeline để quy lượt nói viết tay về `TURN_xxxxxx`,
và báo lỗi nếu stage03 gộp hoặc tách lượt ngoài ý muốn. Nhờ vậy `gold.boundaries` (chỉ số
`SpeakerTurn`) và `evidence_turn_ids` so thẳng được với output API (`turns`, `evidence_ids`).

## Quy ước gold

**Chủ đề** (khớp định nghĩa của 007): ranh giới đặt ở chỗ nội dung thực sự chuyển, tức
đổi module/hạng mục trong họp nhiều hạng mục, hoặc đổi giai đoạn (trình bày → góp ý →
kết luận) trong họp một đề án. Chỉ tính các đoạn liền mạch.
- Chen ngang ngắn (≤ 3 lượt, thủ tục, "mời anh…", hỏi giờ) **không** là ranh giới.
- Một chủ đề quay lại sau đó là **một đoạn mới** với cùng tiêu đề (`meta.revisits`).
- Tiêu đề: động từ + hạng mục đầy đủ, ví dụ "Xây dựng chức năng AI tự động đánh giá câu trả lời kiến nghị".
- Kích thước chủ đề: ~1,5–6k ký tự ở S và M (phần lớn 2–4k), ~3,5–7k ký tự ở L (chỉ L gần với kích thước chủ đề của dữ liệu thật).

**Việc giao** (`assignments`): chỉ tính khi có người nhận hoặc được chỉ định rõ.
Mỗi việc gồm `actor` (tên như trong `speakers`, hoặc tên người được nhắc), `actor_aliases`
(cách xưng hô trong transcript), `task`, `deadline` (hoặc `null`) và `turns`.

**Quyết định** (`decisions`): chỉ những gì đã **chốt**. Nếu bị đảo lại sau đó thì chỉ lấy bản cuối.

**Bẫy** (`negatives`): thứ pipeline **không** được đưa ra. `type` là một trong:
- `hedged_proposal`: đề xuất chưa được chấp nhận; không được vào `decisions`.
- `superseded_decision`: đã chốt rồi bị đảo lại; bản cũ không được vào `decisions`.
- `unassigned_task`: việc cần làm nhưng không ai nhận. Được phép xuất hiện nếu `actor = null`,
  sai nếu gán cho một người cụ thể.
- `rejected_task`: việc được nêu rồi bị gạt đi; không được vào `assignments`.

**Ý chính** (`key_points`): 1–3 ý bắt buộc cho mỗi người nói chính của mỗi chủ đề, dùng
để đo độ bao phủ của phần Diễn biến họp.

## Định dạng spec

````
```json meta
{"meeting_id": "synth_001", "title": "...", "meeting_type": "software_project",
 "length_bucket": "M", "tags": ["pronoun_actor"],
 "speakers": {"CT": "Anh Tuấn (Giám đốc dự án)", "NAM": "Nam (Backend)"},
 "revisits": {"4": 1}}
```
## TOPIC | Xây dựng chức năng ... | Tóm tắt 1-2 câu
@CT: lượt nói ...
@NAM #a1: lượt nói có tag để gold tham chiếu
```json gold
{"assignments": [{"actor": "Nam (Backend)", "actor_aliases": ["em"], "task": "...", "deadline": "thứ Sáu", "turns": ["a1"]}],
 "decisions": [...], "negatives": [{"type": "hedged_proposal", "text": "...", "turns": [...]}],
 "key_points": [{"speaker": "Nam (Backend)", "point": "...", "turns": [...]}]}
```
````

## Ma trận 30 transcript

Loại họp mô phỏng 3 dạng dữ liệu thật:
- `gov`: đề án trình Thường vụ/UBND, theo giai đoạn (giống `vdt_trang`).
- `software_project`: rà soát nhiều module phần mềm (giống `tong_hop`).
- `stt_diarized`: STT chỉ có nhãn diarization `SPEAKER_0X`, không có tên, nhiều lỗi nhận dạng (giống `recording`); danh tính người nhận việc phải suy từ lời thoại.
- `ops`: giao ban định kỳ của đơn vị.

Độ dài (số đo thực tế trong `manifest.json`): **S** (`short_meeting`) 1–5 chủ đề, mỗi chủ đề ~1,5–4,5k ký tự, cả cuộc họp ~5–12,5k (8 transcript, đo riêng hành vi với họp ngắn) · **M** 4–6 chủ đề, mỗi chủ đề ~1,5–6k ký tự, cả cuộc họp ~11–25k · **L** 8–10 chủ đề, mỗi chủ đề ~3,5–7k ký tự, cả cuộc họp ~44–48k. Chỉ L có kích thước chủ đề gần với dữ liệu thật.

| ID | Loại | Độ dài | Chủ đề | Điểm cần kiểm tra (tags) |
|---|---|---|---|---|
| 001 | software_project | S | 5 | `pronoun_actor`, `dense_actions_closing` |
| 002 | gov | S | 3 (giai đoạn) | `phase_structure`, `hedged_proposal` |
| 003 | stt_diarized | S | 4 | `asr_noise`, `pronoun_actor` |
| 004 | ops | M | 5 | `aside_interruption`, `unassigned_task` |
| 005 | software_project | L | 9 | `long`, `similar_adjacent_topics` |
| 006 | gov | M | 4 | `superseded_decision`, `phase_structure` |
| 007 | software_project | S | 2 | `similar_adjacent_topics` |
| 008 | ops | S | 1 | `single_topic` (gold không có ranh giới) |
| 009 | gov | L | 8 | `long`, `topic_revisit` |
| 010 | software_project | M | 5 | `topic_revisit`, `rejected_task` |
| 011 | stt_diarized | M | 4 | `asr_noise` |
| 012 | ops | M | 6 | `dense_actions_closing`, `deadline_variety` |
| 013 | gov | S | 2 | `no_actions` (họp báo cáo, không giao việc) |
| 014 | software_project | M | 4 | `unknown_speaker`, `hedged_proposal` |
| 015 | ops | L | 10 | `long`, `many_speakers` |
| 016 | gov | M | 5 | `aside_interruption`, `pronoun_actor` |
| 017 | software_project | M | 6 | `many_topics_medium` |
| 018 | stt_diarized | L | 8 | `asr_noise`, `long` |
| 019 | ops | S | 3 | `superseded_decision`, `unassigned_task` |
| 020 | gov | M | 4 | `long_monologue_turns` (lượt nói > 3k ký tự) |
| 021 | software_project | L | 8 | `topic_revisit`, `dense_actions_closing` |
| 022 | ops | M | 5 | `pronoun_actor`, `rejected_task` |
| 023 | gov | M | 4 | `phase_structure`, `hedged_proposal` |
| 024 | software_project | M | 5 | `asr_noise`, `similar_adjacent_topics` |
| 025 | ops | M | 4 | `no_actions`, `aside_interruption` |
| 026 | stt_diarized | M | 5 | `superseded_decision` |
| 027 | gov | L | 9 | `long`, `many_speakers`, `unassigned_task` |
| 028 | software_project | S | 3 | `pronoun_actor` |
| 029 | ops | M | 5 | `unknown_speaker`, `deadline_variety` |
| 030 | gov | M | 6 | `topic_revisit`, `superseded_decision` |

Phân bố: S 8 (001, 002, 003, 007, 008, 013, 019, 028) · M 16 · L 6; loại gov 9 · software_project 9 · ops 8 · stt_diarized 4. Mọi transcript S có thêm tag `short_meeting`.

## Giới hạn đã biết

- Văn do LLM viết thường "sạch" và đều hơn họp thật. Nên giữ 3 transcript thật
  (`vdt_trang`, `tong_hop`, `recording`, đã có gold user duyệt) làm tập đối chứng để đo
  khoảng cách giữa dữ liệu tổng hợp và dữ liệu thật.
- Người viết transcript (Claude) và LLM judge không nên cùng họ model.
