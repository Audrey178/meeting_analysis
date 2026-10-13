# Kế hoạch benchmark agentic_v3 (bản mới, 2026-10-13)

Benchmark dựng lại từ đầu (không dùng `eval/bench` cũ), theo bố cục bảng của MedChain: **Bảng 1**
so ba nhóm phương pháp (Base LLM / Single-agent / Multi-agent) trên các tác vụ của biên bản họp;
**Bảng 2** đo trên họp thật tiếng Việt. Trạng thái: **Plan**, chưa implement.

## 1. Câu hỏi cần trả lời

1. agentic_v3 có tốt hơn một lời gọi LLM mạnh cho cả cuộc họp không (Base LLM)?
2. Có tốt hơn các kỹ thuật prompt một agent (few-shot, CoT, self-consistency, map-reduce) trên cùng model không?
3. Có tốt hơn các framework multi-agent tổng quát cài trên cùng model và cùng đầu vào không?
4. Kết quả trên synthetic có giữ được trên họp thật không?

## 2. Dữ liệu và chia tập

| Tập | Nội dung | Dùng cho |
|---|---|---|
| dev | `eval/synthetic` synth_001–030: 362 việc giao, 166 kết luận, 122 bẫy, 5,3k–48k ký tự | tune prompt v3 và lấy ví dụ few-shot cho baseline. **Không** báo số trong bảng |
| test | synth_031–040 (held-out): 124 việc giao, 65 kết luận, 43 bẫy, 7,2k–44,8k ký tự | **Bảng 1**. Chưa phương pháp nào được chạy lên tập này trước khi freeze (M3) |
| real | 3 cuộc họp thật có gold ranh giới chủ đề (`experiments/007_dialtreeseg/gold`): `vdt_trang` (24k ký tự), `tong_hop` (206k), `recording` (Cái Mép, ASR) | **Bảng 2** |

- Ví dụ few-shot chỉ lấy từ dev, và cố định một bộ cho mọi phương pháp có few-shot.
- Test chỉ có 10 cuộc họp, nên mọi số liệu đều kèm **95% CI bootstrap** (lấy mẫu lại theo cuộc họp, 1.000 lần).

## 3. Bảng 1: các hàng

Mọi phương pháp nhận **cùng đầu vào**: lượt nói sau stage01–03, người chủ trì nếu có, ngày họp nếu có.
Mọi phương pháp xuất **cùng schema** (mục 5). Nhóm Single-agent và Multi-agent đều chạy trên
**gemma-4-26B** như v3, để chênh lệch chỉ đến từ phương pháp. Nhóm Base LLM đổi model.

### 3.1 Base LLM: một lời gọi cho cả cuộc họp, prompt zero-shot chung

| Model | Nguồn | Ghi chú |
|---|---|---|
| gemma-4-26B-A4B-it | tự host (gateway hiện tại) | 0đ |
| model mở khác (Qwen/Llama…) | server qua SSH, chờ thông tin | 0đ |
| DeepSeek | API | cần key và trần chi phí |
| GPT (gpt-4o-mini hoặc mạnh hơn) | API OpenAI | ngân sách gần hết trần ($8,04), cần duyệt |

### 3.2 Single-agent, trên gemma

| Phương pháp | Cách làm |
|---|---|
| Zero-shot | = hàng gemma của Base LLM (không chạy lại) |
| Few-shot | thêm 2 ví dụ cố định từ dev (một họp `gov`, một họp `software_project`) |
| CoT | yêu cầu phân tích từng bước trong trường `reasoning` trước khi xuất danh sách |
| Self-consistency | 5 mẫu (temperature 0,7), gộp theo bỏ phiếu: giữ mục xuất hiện trong ≥3/5 mẫu (ghép theo lượt bằng chứng) |
| Map-reduce theo đoạn | thay cho RAG (RAG không hợp với trích xuất toàn văn): cắt cửa sổ ~8k ký tự, trích từng cửa sổ, rồi một lời gọi gộp và khử trùng |

### 3.3 Multi-agent, trên gemma, tự cài theo ý tưởng gốc của từng framework

| Framework | Cách cài cho bài toán này |
|---|---|
| Multi-agent debate (Du et al. 2023) | 3 agent trích độc lập cả cuộc họp, 2 vòng xem đáp án của nhau rồi sửa, gộp bằng bỏ phiếu |
| AutoGen-style (Wu et al. 2023) | hội thoại extractor ↔ critic, tối đa 3 vòng, dừng khi critic trả `APPROVE` |
| Self-Refine (Madaan et al. 2023) | một agent: trích → tự phê bình → sửa, 2 vòng |
| MetaGPT-style SOP (Hong et al. 2023) | chuỗi vai cố định: thư ký (chia chủ đề và tóm tắt) → trích việc giao → trích kết luận → kiểm tra viên |
| **agentic_v3 (ours)** | pipeline production: DialSTART, 3 agent trích xuất theo chủ đề, evidence-check, Verifier ReAct; Verifier chạy trên gemma |

Các baseline cài lại dùng chung phần định nghĩa nghiệp vụ trong prompt: thế nào là việc giao, kết luận,
bẫy. Prompt của chúng viết theo định nghĩa trong `eval/synthetic/README.md`, **không** chép prompt đã tune
của v3, để không cho baseline lợi thế từ việc tune trên dev. Baseline **không** được ngân sách tune prompt
riêng (quyết định 2026-10-13). Ghi rõ điều này trong Limitations.

Mọi phương pháp, kể cả Base LLM, đều được yêu cầu xuất `topics`, nên cột Seg Pk có số cho mọi hàng.

## 4. Bảng 1: các cột (metric)

Metric được chốt trước khi chạy, không đổi sau khi đã thấy kết quả.

| Cột | Định nghĩa |
|---|---|
| Seg Pk↓ | Pk trên ranh giới chủ đề. Output có `topics` rỗng thì coi như cả cuộc họp là một chủ đề |
| Assign F1 | F1 việc giao so với gold, ghép theo mục 6 |
| Assign F1 (actor) | như Assign F1, nhưng một cặp ghép chỉ tính TP khi người phụ trách cũng đúng (so sau khi chuẩn hoá tên, mục 6) |
| Actor | tỉ lệ đúng người phụ trách trên các cặp đã ghép. Chỉ để tham khảo, **không** tính vào Average |
| Deadline | tỉ lệ có hoặc không có hạn khớp gold trên các cặp đã ghép |
| Decision F1 | F1 kết luận so với gold |
| Coverage | tỉ lệ ý chính (`key_points`) được một ý thảo luận trích đúng lượt và đúng người nói |
| Trap↓ | tỉ lệ mục dính bẫy trên **tổng số mục đã xuất** (việc giao + kết luận). Bẫy gồm `rejected_task`, `unassigned_task` có gán người, `hedged_proposal`, `superseded_decision`. Phương pháp không xuất mục nào thì ghi "–", không phải 0 |
| **Average** | trung bình của Assign F1 (actor), Decision F1, Coverage, (1 − Trap rate). Không tính Pk vì là đo phân đoạn, không phải đo trích xuất |
| Cost / Time | lời gọi LLM, token vào/ra, USD (API), phút trên mỗi cuộc họp. Ghi ở bảng phụ, kèm hình Average theo tổng token (compute parity) |

So sánh có ý nghĩa: **paired bootstrap** giữa v3 và baseline mạnh nhất trên Average, Assign F1 (actor) và
Decision F1. "Baseline mạnh nhất" được **chọn theo Average trên dev ở M1**, không chọn trên test. Các so sánh
v3 với từng baseline còn lại cũng báo, kèm hiệu chỉnh Holm. Chỉ viết "v3 tốt nhất" khi 95% CI của hiệu số không chứa 0. Nếu một baseline thắng v3 thì
báo ngay để xem lại framing bài báo, không uốn câu chữ.

## 5. Schema output chung

```json
{"topics": [{"start_turn": "TURN_000001", "title": "..."}],
 "assignments": [{"actor": "...", "task": "...", "deadline": "...|null", "evidence_turn_ids": ["TURN_..."]}],
 "decisions": [{"text": "...", "evidence_turn_ids": ["TURN_..."]}],
 "discussion": [{"text": "...", "speakers": ["..."], "evidence_turn_ids": ["TURN_..."]}]}
```

Evidence bắt buộc là turn_id có thật. Mục có evidence sai bị loại bởi cùng một luật cho mọi phương pháp.
Output của v3 được chuẩn hoá sang schema này.

## 6. Chấm tự động và kiểm chứng bộ chấm

- Ghép dự đoán với gold: lượt bằng chứng của dự đoán phải rơi vào khoảng lượt của gold, nới thêm **±1 lượt**
  (một việc giao thường trải qua đề xuất → đồng ý → chốt hạn ở các lượt liền nhau). M0 kiểm chứng mức nới
  này, nếu cần thì đổi thành ±2 trước khi freeze. Ứng viên còn phải có độ trùng âm tiết nội dung (Dice)
  ≥ 0,15, để một mục nói chuyện khác ở cùng lượt không được tính TP; M0 hiệu chỉnh ngưỡng này. Trong các cặp như vậy, cặp nào
  độ trùng âm tiết nội dung cao hơn được ghép trước, mỗi mục ghép tối đa một lần. Bẫy chỉ tính cho mục
  **không** ghép được với gold mà trùng lượt với một bẫy.
- **Actor:** chuẩn hoá tên trước khi so (bỏ dấu câu, chữ thường, bỏ danh xưng như "anh/chị/ông/bà"; tên
  vai trò như "phòng IT" so khớp nguyên cụm).
- **Deadline:** quy hạn tương đối ("thứ Sáu tuần sau") ra ngày tuyệt đối theo ngày họp. Khớp khi cùng ngày,
  hoặc cả hai đều không có hạn. Synthetic không có ngày họp, nên gold và dự đoán cùng neo vào một ngày giả
  (2026-11-25), dùng luật `src/agentic_v3/core/deadline.py`. Hạn không quy được ra ngày thì so chuỗi
  (Dice ≥ 0,5).
- **Coverage:** một `key_point` được tính là phủ khi có một mục `discussion` ghép được với nó theo đúng luật
  lượt bằng chứng ở trên, và `speakers` của mục đó chứa ít nhất một người nói của `key_point`.
- **Kiểm chứng bộ chấm trước khi tin số (M0):** đọc tay 60 cặp ghép và 40 mục không ghép được, lấy từ
  output dev của 3 phương pháp. Yêu cầu bộ chấm đúng ≥ 90% với nhận định của người đọc. Không đạt thì sửa
  luật ghép rồi kiểm lại.
- Rủi ro đã biết: độ chi tiết của gold. Gold có thể gộp nhiều điểm chốt thành một kết luận, nên precision
  của phương pháp tách nhỏ bị đánh thấp oan. Có thể báo thêm biến thể "nhiều–một" (cho phép nhiều dự đoán
  khớp cùng một gold, chỉ đếm 1 TP) như một kiểm tra độ nhạy.

## 7. Bảng 2: họp thật tiếng Việt

Không có gold việc giao, kết luận hay ý chính, nên Bảng 2 có các cột:

| Cột | Cách đo |
|---|---|
| Seg Pk↓ / WD↓ | so với gold ranh giới của 3 cuộc họp |
| Faithfulness, Completeness, Actor (Likert 1–5) | LLM judge **Claude Opus**, chấm **mù** (ẩn tên phương pháp, xáo thứ tự), rubric viết mới cho benchmark này. Mỗi cuộc họp chấm 2 lần độc lập để đo self-agreement (κ) |
| Progress acc | riêng `vdt_trang`: có `progress-gold` cho tiến độ việc cũ (chỉ v3 có tính năng này, ghi chú riêng) |
| Cost / Time | như Bảng 1 |

- Chỉ chạy các hàng mạnh nhất của Bảng 1 (Base gemma, phương pháp single-agent tốt nhất, multi-agent tốt nhất, v3), để tiết kiệm thời gian và GPU.
- `tong_hop` dài 206k ký tự (khoảng 60–70k token), **có thể vượt context của gemma** khi chạy một lời gọi. Hàng nào không chạy được ghi "–" và chú thích "vượt context". Không cắt bớt đầu vào riêng cho một phương pháp.
- Chỉ có 3 cuộc họp, nên Bảng 2 chỉ mang tính định tính, ghi rõ trong phần Limitations.

## 8. Hạ tầng chạy

Thư mục `meeting_analysis/benchmark/`:

```
benchmark/
  PLAN.md
  config.yaml          # model/endpoint mỗi hàng, concurrency, trần USD mỗi hàng
  methods/             # mỗi phương pháp một module: run(meeting) -> output theo schema chung
  run.py               # chạy một (hàng, tập); bỏ qua cuộc họp đã có output; ghi ledger
  score.py             # chấm Bảng 1 + bootstrap CI + paired bootstrap
  judge/               # rubric + dựng packet mù cho Bảng 2
  report.py            # sinh bảng Markdown + LaTeX (bố cục như MedChain)
  results/<run_id>/    # output, ledger, manifest (git sha, hash prompt, model, nhiệt độ)
```

- **Tải lên gateway gemma:** tối đa 2 cuộc họp song song và 6 lời gọi đồng thời. Khi tải cao hơn, server đã sập/khởi động lại nhiều lần (2026-10-13). Lỗi JSON của Verifier đã được khắc phục bằng `JSON_ONE_LINE_RULE`. Mọi baseline cũng dùng structured output kèm luật này.
- **Tái lập:** mỗi run ghi manifest; output được cache theo (hàng, cuộc họp, hash prompt) nên chạy lại không tốn thêm.
- **Chi phí API:** mỗi hàng API có trần USD riêng trong `config.yaml`; `run.py` dừng khi chạm trần.

## 9. Milestone (theo thứ tự rủi ro)

| # | Việc | Xong khi |
|---|---|---|
| M0 | Bộ chấm + kiểm chứng tay (mục 6); thử độ dài context: chạy Base gemma trên cuộc họp dev dài nhất (48k ký tự) và trên `tong_hop` | bộ chấm đúng ≥ 90%; biết hàng nào vượt context |
| M1 | Cài 4 baseline single-agent + 4 baseline multi-agent; chạy thử trên 3 cuộc họp dev (S/M/L) rồi chấm | mọi phương pháp ra JSON hợp lệ trên cả 3 cuộc họp; JSON lỗi < 5% số lời gọi; chốt baseline mạnh nhất theo Average trên dev |
| M2 | Chốt v3: lấy kết quả tune prompt (arm `base` và `tuned` đang chạy trên dev) | chọn bản v3; toàn bộ test pass |
| M3 | **Freeze**: tag git `bench-v3-freeze`, khoá prompt và config của mọi hàng | tag đã đẩy; từ đây không sửa prompt |
| M4 | Chạy Bảng 1 trên test (10 cuộc họp) cho mọi hàng | 100% cuộc họp có output, hoặc lý do lỗi được ghi |
| M5 | Bảng 2: chạy 4 hàng trên 3 cuộc họp thật + judge mù | κ self-agreement ≥ 0,6, nếu thấp hơn thì báo cáo kèm |
| M6 | `report.py` sinh bảng Markdown/LaTeX + bảng chi phí | bảng khớp số trong `results/` |

Ước lượng thời gian GPU (gemma, mức tải ở trên): v3 khoảng 5–8 phút mỗi cuộc họp. Baseline một lời gọi
khoảng 1–2 phút. Self-consistency và debate gấp 3–5 lần. Bảng 1 tổng cộng khoảng 10–15 giờ GPU.

## 10. Giả định và rủi ro

| Rủi ro | Ảnh hưởng | Cách xử lý |
|---|---|---|
| Gateway gemma không ổn định | run dở dang, số không đầy đủ | resume theo cache; giới hạn tải; ghi log lỗi theo cuộc họp |
| Test chỉ 10 cuộc họp | CI rộng, khó kết luận | paired bootstrap; báo CI; không tuyên bố khi CI chứa 0 |
| Synthetic do Claude viết, prompt v3 cũng do Claude tune | thiên lệch có lợi cho v3 | baseline dùng định nghĩa nghiệp vụ trong README, không dùng prompt tune; Bảng 2 trên họp thật; ghi vào Limitations |
| Bộ chấm ghép nhầm | sai số liệu | kiểm chứng tay ở M0; kiểm tra độ nhạy "nhiều–một" |
| Vượt context (`tong_hop`) | thiếu ô trong Bảng 2 | ghi "–" kèm lý do; không cắt đầu vào riêng |
| Baseline không được tune prompt, còn v3 thì có | reviewer coi baseline là strawman | prompt baseline viết theo định nghĩa chung; công khai prompt; báo số dev của baseline; ghi vào Limitations |
| Ngân sách API | không chạy được hàng GPT/DeepSeek | trần USD mỗi hàng; chạy hàng API sau cùng |

## 11. Còn chờ

- Thông tin SSH và tên model của server mở thứ hai.
- Key DeepSeek; chọn model GPT và trần USD cho mỗi hàng API.
- Kết quả tune prompt (arm `base` vs `tuned` trên dev) để chốt bản v3 ở M2.
