from typing import List, Dict, Tuple
import json
import logging
from model_handler import ModelHandler
from utils import _clean_response

class HallucinationValidator:
    def __init__(self, client, model,log_base_path):
        """Initialize the HallucinationValidator with model settings."""
        self.client = client
        self.model = model
        self.log_base_path = log_base_path

    def validate_atomic_facts(self, atomic_facts: List[Dict], previous_chunk_context,chunk: str) -> Dict:
        """
        Đánh giá tổng thể các facts của 1 chunk so với văn bản gốc (chunk) và ngữ cảnh trước đó (previous_chunk_context).
        Validate atomic facts against original chunk using LLM.
        Returns dict with overall_score, feedback list, and summary.
        """
        system_prompt = """
        Bạn là chuyên gia phát hiện thông tin suy diễn (hallucination) trong dữ liệu trích xuất. Nhiệm vụ của bạn là xác minh tính xác thực của từng fact (sự kiện/nhận định) so với văn bản gốc.

        Thực hiện đánh giá cho từng fact theo các bước sau:
        1. So sánh mỗi fact với văn bản nguồn (SOURCE TEXT).
        2. Kiểm tra ngữ cảnh cung cấp (context) có chính xác và xuất hiện trong văn bản gốc không.
        3. Xác định liệu verbose_context có chứa thông tin không được hỗ trợ từ văn bản gốc hay không.
        4. Đánh dấu tất cả thông tin không được đề cập rõ ràng trong nguồn.

        Đối với mỗi fact, hãy xác thực:
        - Fact chính có được văn bản nguồn xác nhận không?
        - Ngữ cảnh (context) có chính xác và xuất hiện trong nguồn không?
        - Verbose_context chỉ chứa thông tin trích từ nguồn không?
        - Có giả định, suy diễn hoặc thổi phồng thông tin nào không có trong nguồn không?

        YÊU CẦU QUAN TRỌNG:
        - Đánh giá TỪNG FACT một cách riêng biệt.
        - Chỉ rõ các thông tin bị suy diễn/hallucinated.
        - Đánh dấu BẤT KỲ thông tin nào không thấy trong nguồn.
        - Kiểm tra kỹ cả trường fact và context.

        Cuối cùng, trả về kết quả dưới dạng một đối tượng JSON với cấu trúc sau (tất cả nội dung bằng tiếng Việt):

        {
          "overall_score": float (0-100, điểm càng thấp càng ít suy diễn; 0 nghĩa là hoàn toàn đúng, 100 nghĩa là fact hoàn toàn không liên quan nguồn),
          "feedback": [liệt kê cụ thể các điểm bị suy diễn/hallucinated],
          "summary": "Tóm tắt ngắn gọn về kết quả xác thực"
        }
        """

        user_prompt = f"""
        Phân tích các dữ kiện nguyên tử bên dưới so với NGUỒN:

        {previous_chunk_context}

        NGUỒN:
        {chunk}

        DỮ KIỆN NGUYÊN TỬ CẦN XÁC THỰC:
        {json.dumps(atomic_facts, indent=2)}

        Hãy xử lý cẩn thận từng dữ kiện, từng ngữ cảnh, và verbose_context.
        - Đánh dấu BẤT KỲ thông tin nào không xuất hiện trong nguồn
        - Xác định chi tiết bịa đặt/hư cấu/hallucinated cụ thể
        - Nêu rõ ngữ cảnh hoặc thông tin nền không được nguồn hỗ trợ
        - Tìm các trường hợp phóng đại hoặc suy đoán

        Trả về bản đánh giá tổng thể tập trung vào việc phát hiện thông tin bịa đặt/hallucination.
        """

        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "Fact Verification",    
                category="Fact Verification", 
                log_base_path=self.log_base_path,
                verbose=True,
                max_tokens=8000
                )

            enriched_template = _clean_response(response)

            # Parse validation results
            try:
                validation_results = json.loads(enriched_template)
                return {
                    'overall_score': validation_results.get('overall_score', 100),
                    'feedback': validation_results.get('feedback', ["Validation failed"]),
                    'summary': validation_results.get('summary', "Unable to validate properly")
                }
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing validation results: {str(e)}")
                return {
                    'overall_score': 100,
                    'feedback': ["Error parsing validation results"],
                    'summary': "Validation failed due to parsing error"
                }

        except Exception as e:
            logging.error(f"Error in hallucination validation: {str(e)}")
            return {
                'overall_score': 100,
                'feedback': [f"Validation error: {str(e)}"],
                'summary': "Validation failed due to processing error"
            }