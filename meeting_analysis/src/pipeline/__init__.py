"""Pipeline phân tích cuộc họp, chia thành sáu bước chạy nối tiếp:

    Bước 1  tách bản ghi thành các lượt nói
    Bước 2  chia các lượt nói thành từng đoạn theo chủ đề
    Bước 3  đặt tên ngắn cho từng đoạn chủ đề
    Bước 4  mỗi chủ đề có các agent đọc và trích ra: ý thảo luận, kết luận, việc được giao,
            tiến độ các việc cũ
    Bước 5  kiểm lại những gì đã trích: mục chắc chắn giữ ngay, mục còn nghi ngờ thì nhờ
            một agent kiểm chứng đọc lại
    Bước 6  gộp kết quả mọi chủ đề thành một báo cáo cuộc họp

Bước 1-3 chạy một lần để dựng "nền" của cuộc họp; bước 4-6 chạy trên nền đó, các chủ đề được
xử lý song song.
"""
