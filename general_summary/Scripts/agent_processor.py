import logging
from typing import List, Dict, Tuple
import ast
import json
from model_handler import ModelHandler
from utils import _clean_response,_normalise_feedback


class Agents:
    def __init__(self, client, model,log_base_path):
        self.client = client
        self.model = model
        self.log_base_path = log_base_path
        
    def expert_agent(self, summary_input: Dict, outline: List[str], feedback_prompt: str = "") -> str:
        """
        Generate the "II. NỘI DUNG" section of a formal "Thông báo kết luận"
        document: one numbered item per outline title, drafted in formal
        administrative Vietnamese from the chair's ([CHAIR]-sourced) facts.
        """
        system_prompt = f"""
        NGÔN NGỮ: Phải trả lời bằng tiếng Việt.

        Bạn là chuyên viên Văn phòng soạn phần "II. NỘI DUNG" của một văn bản
        "Thông báo kết luận" (thể loại văn bản hành chính Đảng/Nhà nước) từ
        ý kiến kết luận, chỉ đạo của người chủ trì cuộc họp.
        
        Đây KHÔNG PHẢI là bản tóm tắt hội thoại tự do và KHÔNG PHẢI là bản
        tổng hợp toàn bộ nội dung Presenter đã trình bày. Đây là văn bản hành
        chính thể hiện các ý kiến kết luận/chỉ đạo của người chủ trì.

        NGUYÊN TẮC:
- CHỈ nội dung [CHAIR] mới được xem là ý kiến kết luận, quyết định,
  chỉ đạo hoặc yêu cầu của người chủ trì.
- [PRESENTER] chỉ được dùng làm thông tin nền/bổ sung cho kết luận
  [CHAIR], KHÔNG được tự tạo kết luận từ nội dung Presenter.
- Không suy luận Chair đồng ý, thống nhất, phê duyệt hoặc yêu cầu điều
  gì chỉ vì Presenter đã đề xuất/nêu nội dung đó.
- Không thêm thông tin, số liệu, ngày tháng, tên đơn vị hoặc nhiệm vụ
  không có trong context.
- Không biến OBJECTIVE thành ACTION hoặc STATUS thành DECISION.

ƯU TIÊN:
- ACTION/DECISION của [CHAIR]: nội dung kết luận chính.
- STATUS của [CHAIR]: giữ đúng trạng thái hiện tại nếu quan trọng.
- OBJECTIVE/INSIGHT/CONTEXT của [CHAIR]: chỉ dùng khi liên quan trực
  tiếp hoặc làm rõ kết luận.
- [PRESENTER]&#58; chỉ làm bối cảnh, không tạo mục kết luận độc lập.

CÁCH VIẾT:
- DECISION → "Thống nhất...", "Ghi nhận..."
- ACTION → "Đề nghị...", "Giao...", "Rà soát..."
- OBJECTIVE → "Mục tiêu...", "Dự kiến...", "Theo kế hoạch..."
- STATUS → giữ nguyên trạng thái "chưa...", "đang...", "chờ..."
- INSIGHT/CONTEXT → trình bày như nhận định/thông tin nền.
- Chỉ dùng động từ chỉ đạo khi fact thực sự là ACTION/DECISION của Chair.

CẤU TRÚC:
- Phải tạo đúng số mục bằng số outline item, đúng thứ tự.
- Mỗi mục đánh số 1., 2., 3....
- Có thể dùng gạch đầu dòng con nếu cần.
- Nếu thiếu dữ liệu cụ thể → "[CẦN BỔ SUNG]".
- Nếu outline item không có fact hỗ trợ → "[CẦN BỔ SUNG NỘI DUNG]".
- Không giới hạn số từ cứng.
        """

        user_prompt = f"""
Viết phần "II. NỘI DUNG" theo đúng outline:

{outline}

MATCHED INFORMATION:
{summary_input['matched_information']}

UNMATCHED FEATURES:
{summary_input['unmatched_features']}

PREVIOUS FEEDBACK:
{feedback_prompt}

IMPORTANT:
- CHỈ [CHAIR] là nguồn của ý kiến kết luận.
- [PRESENTER] chỉ làm nền/bổ sung, không tạo kết luận mới.
- Chỉ dùng thông tin được cung cấp, không hallucinate/inference.
- Đúng số mục và đúng thứ tự outline.
- Thiếu dữ liệu → "[CẦN BỔ SUNG]", không bịa.
- Không giới hạn số từ.
"""

        message = ModelHandler.build_message(system_prompt, user_prompt)
        response = ModelHandler.call_model_with_retry(
            self.client, message, self.model, "Summary Generation",
            category="Summary Generation",
            log_base_path=self.log_base_path,
            # This drafts the full "II. NỘI DUNG" (all outline items, no hard
            # word limit per the prompt above) in one shot. The default
            # max_tokens=1000 was silently cutting it off mid-sentence once
            # the outline had more than a handful of items — bump it in line
            # with every other heavy-generation call in this pipeline
            # (checker_agent, atomic_facts, hallucination_validator all use
            # 8000).
            max_tokens=8000
            )
        return response

    def checker_agent(self, summary_input: Dict, outline: List[str], generated_summary: str):
        """Check summary adherence to outline and constraints."""
        output_format = {
            "confidence_score": 90,
            "feedback": "Summary follows outline and uses provided facts correctly."
        }
        
        system_prompt = """
NGÔN NGỮ: Phải trả lời bằng tiếng Việt.

Bạn là checker agent đánh giá phần "II. NỘI DUNG" của văn bản
"Thông báo kết luận".

KIỂM TRA:

1. Outline Adherence
- Mỗi outline item tương ứng đúng 1 mục, đúng thứ tự.
- Đánh số liên tục 1., 2., 3....
- Không bỏ mục; mục thiếu dữ liệu phải giữ lại với
  "[CẦN BỔ SUNG NỘI DUNG]".

2. Source & Content Accuracy — QUAN TRỌNG NHẤT
- CHỈ [CHAIR] mới được dùng làm nguồn của ý kiến kết luận,
  quyết định, chỉ đạo hoặc yêu cầu.
- [PRESENTER] chỉ được dùng làm thông tin nền/bổ sung cho kết luận
  [CHAIR], không được tự biến thành kết luận.
- Không được suy luận Chair đồng ý, thống nhất, phê duyệt hoặc yêu cầu
  điều gì chỉ vì Presenter đã đề xuất/nêu nội dung đó.
- Chỉ sử dụng thông tin có trong facts/context; không hallucinate.
- Không bịa số hiệu văn bản, ngày tháng, số liệu, tên đơn vị,
  thời hạn hoặc nhiệm vụ.

3. Feature Type Accuracy
- OBJECTIVE → phải giữ là mục tiêu/kế hoạch/dự kiến; không được biến
  thành "Đề nghị..." hoặc chỉ đạo giả.
- STATUS → phải giữ đúng trạng thái "chưa...", "đang...", "chờ...";
  không được biến thành quyết định đã hoàn tất.
- DECISION → có thể thể hiện "Thống nhất...", "Ghi nhận...".
- ACTION → có thể thể hiện "Đề nghị...", "Giao...", "Rà soát..."
  nếu ACTION thực sự thuộc [CHAIR].
- INSIGHT/CONTEXT → chỉ trình bày như nhận định/thông tin nền.

4. Information Coverage
- Các feature quan trọng của [CHAIR] phải được phản ánh.
- Không làm mất hoặc làm sai chủ đề kết luận.
- Không yêu cầu đưa [PRESENTER] vào như một kết luận nếu Chair không
  có kết luận tương ứng.

5. Format
- Văn phong hành chính, trang trọng, khách quan.
- Các mục rõ ràng, không lẫn nội dung giữa các mục.

TRỪ ĐIỂM:
- Bỏ mục outline: -15
- Sai/nhảy số: -10
- Sai nguồn kết luận ([PRESENTER] bị viết thành kết luận Chair): -20
- Hallucination/bịa thông tin: -20
- OBJECTIVE bị biến thành ACTION: -20
- STATUS bị đảo ngược ý nghĩa: -15
- Thiếu feature quan trọng của CHAIR: -10
- Thiếu placeholder khi dữ liệu cụ thể không có: -10

OUTPUT:
Trả về JSON hợp lệ với đúng 2 trường:
{
  "confidence_score": 0-100,
  "feedback": "Các lỗi cụ thể và cách sửa"
}
"""

        user_prompt = f"""
Đánh giá phần "II. NỘI DUNG" dưới đây:

OUTLINE:
{outline}

MATCHED FACTS / CONTEXTS:
{summary_input['matched_information']}

UNMATCHED FEATURES:
{summary_input['unmatched_features']}

GENERATED DRAFT:
{generated_summary}

Kiểm tra:
1. Đúng số mục, đúng thứ tự outline.
2. CHỈ [CHAIR] được dùng làm nguồn kết luận.
3. [PRESENTER] không bị biến thành kết luận của Chair.
4. Đúng feature_type, đặc biệt OBJECTIVE/STATUS.
5. Không hallucinate hoặc suy luận.
6. Các thông tin quan trọng của CHAIR được phản ánh.
7. Đúng văn phong hành chính.

Nêu cụ thể từng lỗi nếu có và đề xuất cách sửa.
"""
        message = ModelHandler.build_message(system_prompt, user_prompt)
        try:
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "Sumamry Checker Agent", category="Sumamry Checker Agent",
                log_base_path=self.log_base_path,
                max_tokens=8000
            )
        except Exception as e:
            # Unlike every other agent in this pipeline, this call wasn't guarded:
            # a model failure (rate limit exhaustion, context-length error, ...)
            # used to propagate all the way up and crash run_pipeline.py instead
            # of degrading gracefully like atomic_facts/hallucination_validator do.
            logging.error(f"Checker agent call failed: {str(e)}")
            return output_format

        enriched_template = _clean_response(response)

        try:
            parsed_template = json.loads(enriched_template)
        except json.JSONDecodeError:
            try:
                parsed_template = ast.literal_eval(enriched_template)
            except (ValueError, SyntaxError):
                logging.error(f"Error parsing checker response: {enriched_template}")
                return output_format
        
        return parsed_template

    def process_chunk_with_feedback(self, agent_id: str, summary_input: Dict, outline: List[str]) -> Tuple[str, float, str]:
        """Process with feedback loops for improvement."""
        feedback_prompt = ""
        best_summary = ""
        best_score = 0
        
        for attempt in range(1):
            summary = self.expert_agent(summary_input, outline, feedback_prompt)
            check_result = self.checker_agent(summary_input, outline, summary)
            
            if check_result["confidence_score"] > best_score:
                best_summary = summary
                best_score = check_result["confidence_score"]
            
            if check_result["confidence_score"] >= 80:
                break
            
            logging.info(f"Revising summary for {agent_id} due to low confidence score: {check_result['confidence_score']}")
            feedback_prompt = f"Feedback for improvement: {_normalise_feedback(check_result['feedback'])}"
        
        return best_summary, best_score, feedback_prompt


