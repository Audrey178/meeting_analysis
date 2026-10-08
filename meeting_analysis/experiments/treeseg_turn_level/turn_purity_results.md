# Turn purity — Phase 1, M3

**Chặn dưới bảo thủ (pigeonhole), không phải con số tuyệt đối** — xem docstring `turn_purity.py`. Đo trên corpus GT thật (không phải dataset tổng hợp): mọi session ở `web_crawl/outputs/Quốc hội khoá XIII/` có cả raw `.doc` khớp trong `downloads/`.

**Quan trọng: tách riêng chủ tọa (Chủ tịch/Phó Chủ tịch Quốc hội) khỏi đại biểu thường.** Chủ tọa xuất hiện dưới nhiều topic một cách CẤU TRÚC (câu dẫn dắt/chuyển mục ngắn ở đầu mỗi topic), khác về bản chất so với một đại biểu trình bày nhiều điểm thực chất trong 1 lượt phát biểu. Cột 'non-chair' mới là con số đáng tin cho câu hỏi "đại biểu có thực sự nói nhiều vấn đề trong 1 turn không".

- Số session phân tích được: 47
- Session có bằng chứng >=1 turn đa-topic — TẤT CẢ vai trò: 43 (91.5%) — CHỈ đại biểu (bỏ chủ tọa): 43 (91.5%)
- Tổng số turn: 1174, tổng số cặp (speaker, session): 1092
- Đa-topic (chặn dưới) — TẤT CẢ vai trò: 544 (49.8%) — CHỈ đại biểu: 541 (49.5%)
- Số lần chuyển topic bị 'nuốt' trong turn (chặn dưới) — TẤT CẢ vai trò: 1016 — CHỈ đại biểu: 1011

## Theo từng session

| Session | #turn | #topic | #speaker | đa-topic (tất cả) | đa-topic (chỉ đại biểu) | extra transitions (chỉ đại biểu) |
|---|---:|---:|---:|---:|---:|---:|
| Buổi chiều ngày 11_06_2012 | 17 | 18 | 17 | 15 | 15 | 65 |
| Buổi sáng ngày 23_05_2012 | 31 | 8 | 29 | 25 | 25 | 64 |
| Buổi chiều ngày 24_10_2012 | 26 | 10 | 26 | 20 | 20 | 47 |
| Buổi chiều ngày 19_06_2012 Thảo luận ở hội trường về dự án Luật sửa đổi, bổ sung một số điều của Luật luật sư | 27 | 7 | 25 | 21 | 21 | 46 |
| Buổi chiều ngày 25_05_2012 | 25 | 6 | 23 | 21 | 20 | 44 |
| Buổi chiều ngày 30_05_2012 | 23 | 7 | 24 | 19 | 19 | 43 |
| Buổi chiều ngày 05_06_2012 | 27 | 28 | 26 | 20 | 20 | 41 |
| Buổi sáng ngày 04_06_2012 | 29 | 5 | 30 | 20 | 20 | 40 |
| Buổi chiều ngày 23_05_2012 | 24 | 7 | 22 | 17 | 17 | 39 |
| Buổi sáng ngày 07_06_2012 | 40 | 8 | 41 | 22 | 22 | 39 |
| Buổi sáng ngày 19_06_2012 Thảo luận ở hội trường về dự án Luật hợp tác xã (sửa đổi) | 28 | 8 | 28 | 20 | 20 | 39 |
| Buổi chiều ngày 29_05_2012 | 27 | 6 | 25 | 22 | 21 | 37 |
| Buổi chiều ngày 22_05_2012 | 24 | 8 | 23 | 17 | 17 | 35 |
| Buổi sáng ngày 22_05_2012 | 35 | 9 | 33 | 20 | 20 | 34 |
| Buổi chiều ngày 01_06_2012 | 29 | 21 | 25 | 17 | 17 | 31 |
| Buổi sáng ngày 29_05_2012 | 35 | 6 | 34 | 20 | 20 | 31 |
| Buổi chiều ngày 07_06_2012 | 28 | 23 | 26 | 17 | 17 | 30 |
| Buổi sáng ngày 20_06_2012 Thảo luận ở hội trường về dự án Luật sửa đổi, bổ sung một số điều của Luật điện lực | 16 | 5 | 15 | 14 | 14 | 28 |
| Buổi sáng ngày 30_05_2012 | 23 | 7 | 23 | 16 | 16 | 27 |
| Buổi chiều ngày 12_06_2012 Thảo luận ở hội trường về dự án Luật sửa đổi, bổ sung một số điều của Luật quản lý thuế | 15 | 11 | 15 | 11 | 11 | 26 |
| Buổi sáng ngày 28_05_2012 | 31 | 9 | 31 | 18 | 18 | 24 |
| Buổi sáng ngày 25_10_2012 | 24 | 9 | 25 | 13 | 13 | 24 |
| Buổi sáng ngày 05_06_2012 | 24 | 8 | 23 | 13 | 13 | 21 |
| Buổi sáng ngày 25_05_2012 | 30 | 11 | 29 | 14 | 14 | 19 |
| Buổi chiều ngày 23_10_2012 | 27 | 7 | 24 | 13 | 13 | 19 |
| Buổi sáng ngày 27_10_2012 | 26 | 7 | 27 | 14 | 14 | 19 |
| Buổi sáng ngày 23_10_2012 | 33 | 7 | 28 | 13 | 13 | 18 |
| Buổi sáng ngày 18_06_2012 Thảo luận ở hội trường về dự án Luật xuất bản (sửa đổi) | 27 | 7 | 25 | 11 | 11 | 13 |
| Buổi chiều ngày 25_10_2012 | 28 | 5 | 26 | 11 | 11 | 13 |
| Buổi chiều ngày 31_05_2012 | 26 | 5 | 24 | 10 | 10 | 12 |
| Buổi sáng ngày 15_11_2012 | 19 | 8 | 15 | 8 | 8 | 11 |
| Buổi sáng ngày 12_06_2012 Thảo luận ở hội trường về dự thảo Nghị quyết về ban hành một số giải pháp tháo gỡ khó khăn cho sản xuất, kinh doanh và hỗ tr | 23 | 5 | 20 | 5 | 5 | 6 |
| Buổi sáng ngày 5_11_2012 | 26 | 6 | 31 | 6 | 6 | 6 |
| Buổi sáng ngày 08_06_2012 | 32 | 5 | 31 | 5 | 5 | 5 |
| Buổi chiều ngày 30_10_2012 | 29 | 8 | 27 | 3 | 3 | 3 |
| Buổi sáng ngày 30_10_2012 | 38 | 8 | 35 | 3 | 3 | 3 |
| Buổi sáng ngày 29_10_2012 | 12 | 6 | 13 | 2 | 2 | 2 |
| Buổi sáng ngày 31_10_2012 | 30 | 17 | 29 | 2 | 2 | 2 |
| Buổi chiều ngày 08_06_2012 | 25 | 2 | 25 | 1 | 1 | 1 |
| Buổi chiều ngày 20_06_2012 Biểu quyết thông qua_ Luật giá; Luật công đoàn (sửa đổi); Luật giám định tư pháp; Luật phổ biến, giáo dục pháp luật; Luật x | 19 | 5 | 8 | 1 | 1 | 1 |
| Buổi chiều ngày 21_05_2012 | 10 | 5 | 8 | 1 | 1 | 1 |
| Buổi chiều ngày 21_06_2012 Quốc hội họp Thông qua_ Nghị quyết về Đề án tiếp tục đổi mới, nâng cao chất lượng, hiệu quả hoạt động của Quốc hội; Nghị qu | 16 | 5 | 10 | 1 | 1 | 1 |
| Buổi sáng ngày 21_05_2012 | 11 | 2 | 7 | 2 | 1 | 1 |
| Buổi chiều ngày 18_06_2012 Quốc hội biểu quyết thông qua_ Luật bảo hiểm tiền gửi; Luật phòng, chống rửa tiền; Luật giáo dục đại học; Luật phòng, chống | 13 | 5 | 5 | 0 | 0 | 0 |
| Buổi sáng ngày 26_10_2012 | 13 | 5 | 9 | 0 | 0 | 0 |
| Buổi sáng ngày 7_11_2012 | 26 | 6 | 23 | 0 | 0 | 0 |
| Buổi sáng ngày 8_11_2012 | 27 | 6 | 24 | 0 | 0 | 0 |
