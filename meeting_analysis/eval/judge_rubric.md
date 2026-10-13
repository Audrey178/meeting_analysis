# Rubric LLM-judge (Likert 1–5) cho output pipeline `be/`

Judge đọc: transcript (lượt nói `TURN_xxxxxx`), gold (`eval/synthetic/gold/`), output API.
Trước khi cho điểm Likert, judge ghép từng item gold với output (`match` / `partial` / `miss`)
và đánh dấu từng item output là `ok` / `hallucinated` / `trap` (rơi vào `negatives`) /
`wrong_actor`. Điểm Likert phải nhất quán với bảng ghép này.

## A. Cắt chủ đề (bổ sung cho Pk/WD/F1)

| Mã | Mục tiêu | 5 | 3 | 1 |
|---|---|---|---|---|
| S1 | **Vị trí ranh giới**: ranh giới dự đoán nằm ở chỗ nội dung thực sự chuyển (đổi module/hạng mục, đổi giai đoạn) | mọi ranh giới đúng hoặc lệch ≤ 1–2 lượt | khoảng một nửa đúng, số còn lại lệch nhiều hoặc rơi vào chen ngang | phần lớn ranh giới vô nghĩa |
| S2 | **Độ mịn**: số đoạn hợp với cấu trúc cuộc họp | số đoạn = gold (±0 với họp ngắn, ±1 với họp dài) | lệch 2 đoạn hoặc gộp 2 chủ đề rõ ràng khác nhau | gộp gần hết thành 1 đoạn hoặc cắt vụn |
| S3 | **Tiêu đề chủ đề**: đúng nội dung đoạn, dạng "động từ + chức năng/hạng mục đầy đủ", không chung chung | cụ thể, đúng, đúng dạng | đúng ý nhưng chung chung hoặc chỉ phản ánh một phần đoạn | sai nội dung hoặc bịa |
| S4 | **Tóm tắt chủ đề**: trung thực, nêu kết quả chính của đoạn | đủ ý chính, không sai | thiếu kết quả chính hoặc có chi tiết nhỏ sai | sai/bịa |

S3–S4 chấm trên đoạn *dự đoán* (đoạn có ranh giới sai vẫn được chấm theo nội dung thật của nó).

## B. Output cuối

| Mã | Mục tiêu | 5 | 3 | 1 |
|---|---|---|---|---|
| F1 | **Bao phủ Diễn biến họp**: các `key_points` gold có mặt trong ý thảo luận | ≥ 90% key point có mặt | ~50–70% | < 30% |
| F2 | **Trung thực Diễn biến họp**: ý thảo luận gắn đúng người tham gia, đúng nội dung, trích dẫn đỡ được ý đó | không lỗi | vài lỗi nhỏ (gán nhầm người, sai số liệu nhỏ) | nhiều lỗi/bịa |
| F3 | **Giao việc – đầy đủ**: recall gold `assignments` | ≥ 90% | ~50–70% | < 30% |
| F4 | **Giao việc – chính xác**: không bịa, không lấy `rejected_task`, `actor` đúng người (suy được từ "em/anh"), deadline đúng nếu có | mọi item đúng | 1–2 item sai actor/deadline hoặc 1 bẫy | nhiều item sai/bẫy |
| F5 | **Kết luận – đầy đủ**: recall gold `decisions` | ≥ 90% | ~50–70% | < 30% |
| F6 | **Kết luận – chính xác**: không đưa `hedged_proposal`, `superseded_decision`, không biến ý kiến thành kết luận | không lỗi | 1 lỗi | nhiều lỗi |
| F7 | **Gọn và không trùng lặp**: không lặp cùng việc/kết luận, ý thảo luận không vụn | gọn | lặp vài chỗ | lặp/vụn nhiều, khó đọc |
| F8 | **Dùng được làm biên bản**: thư ký có thể dùng sau chỉnh sửa nhẹ | dùng ngay | phải sửa đáng kể | phải làm lại |

Mốc 2 và 4 là trung gian. Mỗi điểm kèm một câu lý do nêu item cụ thể.

## Lưu ý thiên lệch

Transcript tổng hợp do Claude viết, và judge ở lần chạy này cũng là Claude (theo yêu cầu).
README của bộ test khuyến nghị judge khác họ model; kết quả Likert ở đây nên được xem là
đánh giá sơ bộ, đối chiếu thêm với proxy tự động (`evidence_overlap.json`) và metric ranh giới.
