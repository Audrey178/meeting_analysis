from model_handler import ModelHandler

class PostProcessor:
    def __init__(self, client, model,log_base_path):
        self.client = client
        self.model = model
        self.log_base_path = log_base_path

    def post_process_summary(self, combined_summary):

        system_prompt = f"""
        NGÔN NGỮ: Phải trả lời bằng tiếng Việt.

        Bạn là chuyên viên Văn phòng biên tập lần cuối phần "II. NỘI DUNG"
        của một văn bản "Thông báo kết luận" (văn bản hành chính Đảng/Nhà
        nước) trước khi trình ký. Đây KHÔNG PHẢI bước nén/rút gọn thành một
        đoạn văn ngắn — đây là bước CHUẨN HÓA VĂN PHONG, giữ nguyên cấu trúc
        mục đánh số đã có.

        CRITICAL GUIDELINES:
        1. GIỮ NGUYÊN CẤU TRÚC:
           - KHÔNG được gộp các mục lại thành đoạn văn liền mạch
           - KHÔNG được xoá/gộp/tách lại số thứ tự các mục đã có
           - Giữ nguyên số lượng mục và thứ tự đánh số

        2. CHUẨN HÓA VĂN PHONG HÀNH CHÍNH:
           - Thống nhất cách xưng hô ("đồng chí", thể văn tường thuật)
           - Câu văn trang trọng, khách quan, đúng văn phong chỉ đạo/kết luận
           - Sửa lỗi diễn đạt, loại bỏ lặp từ/lặp ý trong CÙNG một mục
           - Không đổi ý nghĩa, không thêm thông tin mới ngoài bản gốc

        3. BẢO TOÀN PLACEHOLDER:
           - Mọi chuỗi "[CẦN BỔ SUNG]" hoặc "[CẦN BỔ SUNG ...]" PHẢI được
             giữ nguyên y hệt, không được tự ý điền, đoán, hay xoá bỏ

        4. KHÔNG GIỚI HẠN SỐ TỪ:
           - Độ dài mỗi mục giữ theo nội dung gốc, không cắt bớt để "cho
             gọn", không thêm chữ để "cho đủ"

        WHAT TO AVOID:
        - Biến văn bản có mục đánh số thành 1-2 đoạn văn xuôi
        - Xoá hoặc tự điền bất kỳ placeholder "[CẦN BỔ SUNG]" nào
        - Thêm thông tin không có trong bản gốc (số liệu, ngày tháng, tên...)
        - Đổi thứ tự hoặc gộp các mục khác chủ đề với nhau
        """

        user_prompt = f"""
        Đây là bản nháp phần "II. NỘI DUNG" cần chuẩn hóa văn phong:

        {combined_summary}

        Hãy tạo bản hoàn thiện mà:
        1. Giữ nguyên toàn bộ số mục, thứ tự mục, và mọi placeholder "[CẦN BỔ SUNG...]"
        2. Chuẩn hóa văn phong hành chính, trang trọng, nhất quán
        3. Không gộp các mục thành đoạn văn xuôi, không giới hạn số từ
        4. Không thêm thông tin mới ngoài bản gốc

        Chỉ sửa văn phong/diễn đạt — KHÔNG thay đổi cấu trúc mục hay nội dung thực chất.
        """


        message = ModelHandler.build_message(system_prompt, user_prompt)


        refined_summary = ModelHandler.call_model_with_retry(
            self.client,
            message,
            self.model,
            "general",
            category="Summary Refinement",
            log_base_path=self.log_base_path,
            # Same fix as expert_agent in agent_processor.py: this rewrites
            # the whole numbered "II. NỘI DUNG" section (explicitly "KHÔNG
            # GIỚI HẠN SỐ TỪ" per the prompt above), so the default
            # max_tokens=1000 was truncating it mid-item. Match the 8000
            # used elsewhere in the pipeline for full-section generation.
            max_tokens=8000
        )
        print(refined_summary)
        return refined_summary