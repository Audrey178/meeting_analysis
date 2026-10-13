### Mục tiêu

Đo chất lượng biên bản (Giao việc, Kết luận, Diễn biến) và chất lượng cắt chủ đề của pipeline
**DialSTART + agentic_v3**, so với baseline một prompt (B0) và các biến thể bỏ/thay từng thành
phần (ablation). Mọi arm chạy trên cùng mã nguồn đã đóng băng (tag git `bench-freeze-v2`; bảng
"Nguồn gốc" bên dưới ghi commit thật của từng arm).

### Hệ thống đề xuất (arm `v3`)

1. **Dựng lượt nói**: stage01–03 của pipeline quy bản ghi về dãy `SpeakerTurn`.
2. **Cắt chủ đề (DialSTART)**: mô hình DialSTART, backbone `NlpHUST/vibert4news-base-cased`, checkpoint
   `experiments/dialstart/model_vn3/best.pt`. Điểm mạch lạc mỗi khe giữa hai lượt
   = sigmoid(logit NSP + cos embedding chủ đề trái/phải), cửa sổ 2 lượt mỗi phía. Chọn ranh giới:
   làm mượt điểm (cửa sổ 3) → depth score kiểu TextTiling → giữ khe có depth > mean + 1,0·std →
   mỗi đoạn ≥ 4 lượt và ≥ max(1500, min(10000, tổng ký tự / 15)) ký tự → tách đoạn > 35000 ký tự.
   Không gộp đoạn theo cosine.
3. **Gán nhãn chủ đề**: LLM chính sinh tiêu đề + tóm tắt cho mỗi đoạn.
4. **Planner**: dựng danh bạ người nói của cả cuộc họp bằng luật (0 token).
5. **Trích xuất song song theo chủ đề**: Content agent (Diễn biến), Action agent (Giao việc),
   Decision agent (Kết luận), agent tiến độ (chỉ khi phiên họp có danh sách việc). Mỗi agent tối đa
   2 lượt thử.
6. **Evidence-check** (tách CLEAR / UNCERTAIN, không loại thẳng candidate nào): luật kiểm bằng chứng
   (người nhận có căn cứ trong danh bạ/danh sách tham dự, không mơ hồ giữa nhiều ứng viên) cộng xét lượt
   chốt bằng OpenAI Decisions API (`gpt-6-luna`), phân loại hành vi lời nói của lượt ra p_commit.
   p_commit ≥ 0,8 và luật không gắn cờ: CLEAR, vào kết quả ngay. Còn lại (0,2 ≤ p_commit < 0,8 là
   "chưa rõ", p_commit < 0,2 là "không phải lời chốt", hoặc luật gắn cờ): UNCERTAIN, chuyển Verifier kèm
   lý do. Lượt dài hơn 2500 ký tự được xét theo từng đoạn, lấy p_commit cao nhất.
7. **Verifier (ReAct)**: `gpt-4o-mini` kiểm chứng candidate UNCERTAIN, được gọi tool
   `search_meeting` (top-5 lượt, tối đa 3 lần), trao đổi lại với agent trích xuất tối đa 3 vòng tới khi
   đồng thuận.

### Model và giải mã

| Vai trò | Model | Nơi chạy | Giá |
|---|---|---|---|
| LLM chính (gán nhãn, agent trích xuất, B0) | `google/gemma-4-26B-A4B-it` | tự host, endpoint tương thích OpenAI | 0 |
| Verifier | `gpt-4o-mini` (structured output `json_schema`) | OpenAI API | $0,15 / $0,075 (cache) / $0,60 mỗi 1M token vào/ra |
| Evidence-check | `gpt-6-luna` qua Decisions API | OpenAI API | $0,10 mỗi 1M token vào, output miễn phí |
| Cắt chủ đề | DialSTART (ViBERT4news) | CPU/GPU local | 0 |
| Judge | Claude Opus (`claude-opus-5-5`) | phiên Claude Code, chấm mù | ngoài ngân sách OpenAI |

Nhiệt độ 0 cho mọi lời gọi LLM. Gemma vẫn không tất định hoàn toàn khi chạy song song, nên
B1 được chạy 3 lần để ước lượng độ dao động giữa các lần chạy.

### Thiết kế so sánh

- **B0 (`b0_single_prompt`)**: một lời gọi gemma cho cả cuộc họp, tự chia chủ đề và sinh mọi phần
  của biên bản, dùng **cùng các quy tắc nghiệp vụ** (quy tắc giao việc/kết luận của chủ toạ, ngôi thứ
  ba) lấy thẳng từ prompt của v3. Chênh lệch v3 − B0 vì vậy đo phần kiến trúc, không đo chênh lệch prompt.
- **Ablation**: mỗi arm đổi đúng một thành phần so với `v3` (bảng "Các arm").
- **Cắt chủ đề dùng chung**: ranh giới + nhãn chủ đề tính MỘT lần cho mỗi bộ cắt và dùng lại ở mọi
  arm cùng bộ cắt, nên các arm DialSTART chỉ khác nhau ở thành phần đang thử, không lẫn nhiễu của bộ
  gán nhãn.
- `ec_off` (bỏ evidence-check, mọi candidate qua Verifier) không chạy ở bench_v2: đắt nhất (~$1,5) và câu
  hỏi của nó đã được `verif_keep`/`verif_drop` trả lời một phần.
- `v3_oracle` dùng ranh giới gold: cận trên, đo lỗi cắt chủ đề làm mất bao nhiêu ở hạ nguồn.
- Held-out (`synth_031`–`040`) được viết sau, chưa từng dùng để chỉnh pipeline; chỉ chạy sau khi đóng
  băng mã. Báo cáo dev và held-out riêng.

### Metric

**Tự động (không cần judge)**

- **Pk, WindowDiff** (thấp là tốt): như segeval nhưng trên khối lượng ký tự (đơn vị 10 ký tự), cửa
  sổ = nửa độ dài đoạn gold trung bình; trung bình theo cuộc họp.
- **F1@2k**: F1 ranh giới, ghép một-một các cặp ranh giới lệch ≤ 2000 ký tự.
- **|ΔK|**: |số chủ đề dự đoán − số chủ đề gold|.
- **Chạm giao / kết luận / ý chính**: tỷ lệ mục gold có ít nhất một lượt bằng chứng được output trích
  dẫn (micro). Đây là proxy rẻ cho recall: trích đúng lượt chưa chắc đúng nội dung hay người nhận.
- **Chạm bẫy** (thấp là tốt): tỷ lệ bẫy gold (đề xuất chưa chốt, quyết định bị đảo, việc bị gạt, việc
  không ai nhận) mà output trích dẫn lượt của bẫy ở đúng phần (Giao việc/Kết luận). Chỉ là dấu hiệu lỗi.
- **Giao/họp, KL/họp**: số mục output trung bình mỗi cuộc họp (so với số mục gold ở bảng dữ liệu).
- **$/họp, Giây/họp**: chi phí OpenAI và thời gian chạy (wall-clock) mỗi cuộc họp.

**Judge (metric chính)**: Claude Opus đọc packet mù (transcript + gold + output, không có tên hệ thống
hay dấu vết kiến trúc), ghép từng mục gold với mục output theo nội dung và gán nhãn từng mục output
(`ok`, `extra_valid`, `duplicate`, `trap`, `not_assignment`/`not_decision`, `hallucinated`) theo
`eval/bench/JUDGE_PROTOCOL.md`.
- P = (ok + extra_valid) / số mục output; R = (match + 0,5·partial) / số mục gold; F1 điều hoà; cộng
  đếm trên mọi cuộc họp (micro), riêng cho Giao việc (A) và Kết luận (D).
- Đúng người / đúng hạn: trên các việc giao nhãn `ok`. Dính bẫy: tỷ lệ bẫy gold bị output rơi vào.
- So sánh với `v3`: bootstrap ghép cặp theo cuộc họp, 10 000 lần, khoảng tin cậy 95%; ▲/▼ khi CI không
  chứa 0.
- Tiêu chí chốt trước khi chạy: một thành phần được coi là có tác dụng khi CI của chênh lệch không chứa
  0 **và** chênh lệch lớn hơn độ dao động giữa 3 lần chạy của B1.

### Ngân sách và tái lập

- Trần chi OpenAI cho cả nghiên cứu: $8,04, cộng dồn qua mọi run trong `eval/results/spend_ledger.jsonl`;
  `run.py` dừng trước cuộc họp tiếp theo khi chạm trần. M3 (ablation phụ) chạy theo thứ tự ưu tiên tới
  khi hết ngân sách.
- Mỗi arm ghi `manifest.json`: commit git, cây làm việc có sạch không, cấu hình arm, `V3Config`, model,
  fingerprint mã nguồn + biến môi trường của pipeline (chạy tiếp bị chặn nếu fingerprint đổi).
- Lệnh chạy: `bash eval/bench/run_bench_v2.sh m2|m3`; bảng này: `python eval/bench/report.py --run bench_v2 --split dev|heldout`.
- Lỗi mạng tạm thời (connection reset) được adapter tự thử lại (tối đa 6 lần); một chủ đề chỉ tính lỗi
  khi mọi lượt thử đều hỏng (cột "CĐ lỗi/họp").

### Giới hạn

- Transcript tổng hợp do Claude viết: văn "sạch" và đều hơn họp thật; chỉ bucket L có kích thước chủ đề
  gần dữ liệu thật.
- Judge (Claude Opus) cùng họ model với người viết transcript; README của bộ dữ liệu khuyến nghị tránh
  điều này. Độ tự nhất quán của judge đo ở `bench_v1` là κ = 0,961; chưa có đối chứng với người chấm trên
  toàn bộ tập.
- Đa số arm chỉ chạy 1 lần; độ dao động giữa các lần chạy lấy từ B1 (3 lần), chưa đo riêng cho Verifier.
- Dữ liệu thật (`private_test/`) không có gold việc giao/kết luận nên không nằm trong bảng này.
