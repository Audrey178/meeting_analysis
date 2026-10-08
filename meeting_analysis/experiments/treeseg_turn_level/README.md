# 001 — TreeSeg, turn-level (Phase 1)

Mục tiêu: chạy TreeSeg (Gklezakos et al., 2024, arXiv:2407.12028) **đúng như bản
gốc** — input là speaker turn (không phải atom/semantic-unit) — rồi evaluate
trên ground truth thật (`web_crawl/outputs/.../*_groundtruth.docx`, 47 session,
Kỳ họp thứ ba + thứ tư, khoá XIII) bằng metric đã có sẵn trong repo
(`eval/segmentation_metrics.py`: Pk, WindowDiff, boundary F1).

Đây là bước rủi ro thấp nhất trong plan (không ngoại suy sang granularity
chưa được paper gốc kiểm chứng). Nằm ở `experiments/` (không phải `src/`) vì
đây là mã thử nghiệm, chưa phải module production — mỗi phase mới của TreeSeg
sẽ có thư mục số thứ tự riêng (`002_...`) thay vì sửa đè lên phase này, để dễ
so sánh version qua các lần chạy.

## Giả định & rủi ro đã biết (từ Plan, Bước 3-4)

- Sự thật thực nghiệm đã kiểm chứng trên dữ liệu thật (không phải giả định):
  một turn liên tục CÓ THỂ bao phủ nhiều topic thật sự (ví dụ Nguyễn Thanh
  Phương, `Buổi sáng ngày 20_06_2012`, một turn góp ý "4 vấn đề" trong đó GT
  tách thành 2 topic riêng: quy hoạch điện lực và giá điện). Turn-level
  segmentation sẽ **luôn miss** ranh giới này — đo tỷ lệ ảnh hưởng thực tế
  là một phần của eval ở đây (`turn_purity.py`), không chỉ nêu như hạn chế
  suông.
- Embedding: dùng `OpenAIEmbeddingClient` có sẵn ở `src/utils/openai_adapters.py`
  (không viết adapter mới). `.env` ở repo root đã có `OPENAI_API_KEY`.

## Cấu trúc

- `treeseg.py` — engine thuần thuật toán (block-smoothing + chia đệ quy
  cumsum-optimized + min-heap), không phụ thuộc domain, nhận vào embedding
  đã tính sẵn.
- `test_treeseg.py` — unit test: loss cumsum-optimized phải khớp brute-force.
- `gt_parser.py` — đọc `*_groundtruth.docx` + transcript thô `.doc` tương ứng,
  suy ra ranh giới topic ở mức turn (dùng lại đúng convention `@VIETTAT` +
  Heading 3 mà `.claude/skills/labeler` đã dùng để tạo các file này).
- `run_pilot.py` — chạy toàn bộ: turn → embed (OpenAI) → TreeSeg → cắt cây ở
  K = số topic thật (theo đúng phương pháp evaluate của paper gốc, §2.2) →
  Pk/WindowDiff/F1 (tái dùng `eval/segmentation_metrics.py` của repo, không
  viết lại) + tỷ lệ turn đa-topic.
- `results.md` — báo cáo, theo đúng style disclaimer trung thực đã có ở
  `eval/ablation_results.md`.
