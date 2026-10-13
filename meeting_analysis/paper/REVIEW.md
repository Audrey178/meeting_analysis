# Review bản thảo và các thay đổi khi chuyển sang LaTeX

Bản LaTeX: `paper/main.tex` (template ACL, tiếng Việt, LuaLaTeX). Biên dịch:

```bash
cd paper && latexmk -lualatex main.tex
```

## Đánh giá tổng quát (góc nhìn reviewer ACL)

**Điểm mạnh.** Bài toán thực tế và có giá trị cho tiếng Việt. Kiến trúc hai tầng rõ ràng. Commitment Scorer có số liệu tốt và được hiệu chỉnh (F1 0.894 so với 0.682, ECE 0.040). Ý tưởng dùng xác suất hiệu chỉnh để định tuyến kiểm chứng là đóng góp gọn và dễ bảo vệ. Phân tích lỗi lối tắt trong dữ liệu tổng hợp (88% ranh giới trùng chỗ đổi đại từ) là một phát hiện trung thực, đáng giữ.

**Điểm yếu sẽ bị hỏi.** Đây là lý do bản hiện tại khó qua vòng review:

1. **Chưa có đánh giá đầu-cuối.** Bài khẳng định khung đa tác tử và Verifier tốt hơn, nhưng chưa có precision/recall của giao việc, kết luận và người nhận trên dữ liệu thật. Cũng chưa có ablation bỏ Verifier, bỏ vòng đồng thuận hay bỏ Topic Planner, và chưa so sánh với pipeline tuần tự. Đây là điểm yếu nặng nhất.
2. **Phân đoạn mâu thuẫn với lựa chọn hệ thống.** Phương pháp lai DialSTART + TreeSeg có Pk 0.224 trên gold nội bộ, nhưng hệ thống lại dùng DialSTART-VI, vốn có Pk 0.485 trên gold thật. Reviewer sẽ hỏi vì sao.
3. **Các dòng của bảng phân đoạn dùng tập dữ liệu khác nhau.** "12 cuộc họp Quốc hội" và "12 cuộc họp" chưa rõ có phải cùng một tập không, nên các số không so sánh trực tiếp được với nhau.
4. **Khả năng tái lập.** Commitment Scorer gọi OpenAI Decisions API, một dịch vụ thương mại. Phiên bản LLM cho các tác tử và cho Verifier chưa được nêu. Không có độ lệch chuẩn qua nhiều lần chạy, trong khi bài tự thừa nhận LLM dao động dù temperature bằng 0.
5. **Gold nhỏ.** Phần phân đoạn chỉ có 9 ranh giới do một người gán; phần tiến độ chỉ có 1 biên bản với 4 việc.

## Những gì đã sửa trong bản LaTeX so với bản doc

| Vấn đề | Sửa |
|---|---|
| Tiêu đề ghi "không giám sát", trong khi DialSTART-VI học từ cấu trúc ranh giới của dữ liệu tổng hợp | Bỏ "không giám sát" khỏi tiêu đề; mô tả là huấn luyện trên dữ liệu tổng hợp |
| Tóm tắt nêu con số 78 giây, vốn đo trước khi có vòng đồng thuận | Bỏ khỏi tóm tắt; trong mục 5.3 ghi rõ điều kiện đo và thêm TODO đo lại |
| Bản doc ghi "chỉ vùng giữa mới tốn chi phí Verifier". **Sai so với code**: lượt có p_c < 0.2 cũng được gửi Verifier kèm cờ "không phải lời chốt" (`_confirm_turn_reasons` trong `core/_shared.py`) | Sửa Bảng 4 và đoạn diễn giải |
| Công thức depth score dùng max trên toàn bộ dãy | Sửa theo TextTiling và theo code: đỉnh gần nhất khi đi sang hai bên trong lúc điểm còn tăng |
| Đóng góp "song song nên nhanh hơn" chưa có số đo so với baseline | Diễn đạt lại thành "loại bỏ phụ thuộc tuần tự", không khẳng định tốc độ |
| Chưa nêu model nào được dùng | Thêm mục Thiết lập thực nghiệm (dữ liệu, model, độ đo) và Phụ lục A gồm siêu tham số đầy đủ |
| ACL bắt buộc có mục Limitations | Thêm "Hạn chế" (không đánh số) và "Tuyên bố đạo đức" |
| Hình là widget SVG | Vẽ lại bằng TikZ (vector), không đặt tiêu đề trong hình, chú thích đọc độc lập được |
| Bảng | Dùng `booktabs`, có mũi tên ↑↓ chỉ chiều tốt hơn, in đậm giá trị tốt nhất |

## Trích dẫn

13 tài liệu trong `paper/references.bib`, gồm 4 tài liệu mới: TextTiling, Pk (Beeferman và cộng sự), BM25 và ECE (Guo và cộng sự). Metadata của mỗi tài liệu (tác giả, tiêu đề, nơi đăng, trang, DOI) đã được xác minh bằng tìm kiếm web trên arXiv cùng trang hội nghị hoặc nhà xuất bản. **Chưa tải được BibTeX gốc**, vì mạng của môi trường soạn chặn arXiv, ACL Anthology, doi.org và Semantic Scholar. Trước khi nộp, thay từng entry bằng BibTeX tải từ ACL Anthology hoặc doi.org.

Hai chỗ cần lưu ý:

- DialSTART: bản trên ACM SIGIR 2023 mang tên "...with Topic-aware Contrastive Learning", khác tên bản arXiv. Hãy chọn một bản để trích.
- vibert4news không có paper giới thiệu chính thức, nên được trích qua footnote trỏ tới Hugging Face.

## TODO còn lại trong `main.tex`

Các chỗ này được đánh dấu chữ đỏ `[TODO: ...]` bằng macro `\todo`. Xoá macro khi đã điền đủ.

1. Commitment Scorer: bài đã mô tả decision model ở mức khái niệm (định nghĩa, câu hỏi sáu lựa chọn, công thức p_c, năm ưu điểm) mà không nêu tên dịch vụ cụ thể. Bản cài đặt hiện gọi OpenAI Decisions API; nếu reviewer hỏi về tái lập, cân nhắc thử thay bằng một mô hình mở.
2. Phiên bản Gemma dùng cho các tác tử; model dùng cho Verifier.
3. Làm rõ tập "12 cuộc họp" và thống nhất tập dữ liệu trong Bảng 2.
4. Chạy DialSTART-VI trên gold nội bộ để so trực tiếp với phương pháp lai, và giải thích lựa chọn.
5. Đo lại độ trễ và số lời gọi LLM với cấu hình cuối.
6. Đánh giá đầu-cuối cùng các ablation, báo cáo trung bình và độ lệch chuẩn qua ít nhất 3 lần chạy.
7. Tuyên bố đạo đức: sự đồng ý của người tham dự, cách ẩn danh, và việc có công bố dữ liệu hay không.

## Lưu ý khác

- ACL yêu cầu bài viết bằng tiếng Anh. Bản này viết tiếng Việt theo lựa chọn hiện tại, nên phù hợp với hội nghị trong nước hoặc làm báo cáo nội bộ. Nếu nộp ACL, cần dịch sang tiếng Anh; cấu trúc LaTeX giữ nguyên được.
- `\usepackage[review]{acl}` đang bật chế độ ẩn danh. Đổi sang `final` khi nộp bản camera-ready.
