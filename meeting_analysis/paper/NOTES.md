# Bản nháp paper: phần Method của agentic_v3

- `main.tex`: khung paper theo template ACL (chỉ mới có phần Method và Phụ lục A).
- `sections/method.tex`: §Method — luồng agent của `src/agentic_v3`.
- `sections/appendix_progress.tex`: Phụ lục A — theo dõi tiến độ việc cũ.
- `figures/pipeline.tex`: Hình 1 (TikZ), sơ đồ graph cha + subgraph chủ đề.
- `references.bib`: 10 trích dẫn, metadata đã đối chiếu qua web; BibTeX ghép tay vì sandbox không tới được doi.org/arXiv — cần export lại trước khi nộp.
- `acl_latex.tex`, `acl.sty`, …: template gốc, giữ nguyên để tham khảo.

Biên dịch: `latexmk -pdf main.tex` (cần TikZ, vntex, algorithmicx).

## Số liệu dùng trong Method

- Bảng 1 (lượt chốt): chạy lại `python experiments/009_decisions_api/analyze.py`, 869 lượt của synth_001–030 (tập dev).
- Ngưỡng gộp trùng (12 cặp, 11 đúng) và ngưỡng amend 0.5: lấy từ comment trong code (`core/_shared.py`, `nodes/verifier.py`), chưa có script tái lập trong repo.
- Mọi siêu tham số khác: giá trị mặc định trong `config.py` và hằng số trong code.
- Không có số nào từ tập test.

## Còn thiếu / cần quyết định

- Tên hệ thống: đang để placeholder `\method` = AgenticV3.
- Tên chính xác của bộ phân loại lượt chốt (hosted endpoint) (mục Evidence check và Implementation).
- Phân bố số vòng / số lời gọi tool mỗi candidate (TODO trong mục Verifier), lấy từ verification records khi chạy test.
- Abstract, Introduction, Related Work, Experiments, Limitations.
