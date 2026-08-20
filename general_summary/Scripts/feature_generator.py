from typing import List, Dict
from model_handler import ModelHandler
from utils import _clean_response
import ast
import json
import logging
import re

class FeatureGenerator:
    def __init__(self, client, model,log_base_path):
        self.client = client
        self.model = model
        self.log_base_path = log_base_path

    def verify_feature_completeness(self, features_output: str) -> bool:
        """
        Verify if the model output is complete and properly formatted.
        Returns True if output is complete, False if truncated or malformed.
        """
        logging.info(f"Features = {features_output}")
        try:
            # Try parsing the output as JSON first
            try:
                features = json.loads(features_output)
            except json.JSONDecodeError:
                try:
                    features = ast.literal_eval(features_output)
                except (ValueError, SyntaxError):
                    logging.error("Failed to parse features output")
                    return False
            
            if not isinstance(features, list):
                logging.error("Features output is not a list")
                return False
                
            # Required fields for each feature
            required_fields = {
                'feature',
                'reasoning',
                'importance_score',
                'feature_type',
                'certainty_score'
            }
            
            # Check each feature has all required fields with valid values
            for feature in features:
                # Check all required fields exist
                if not all(field in feature for field in required_fields):
                    logging.error(f"Missing required fields in feature: {feature}")
                    return False
                
                # Check field types and values
                if not isinstance(feature['feature'], str) or not feature['feature'].strip():
                    return False
                    
                if not isinstance(feature['reasoning'], str) or not feature['reasoning'].strip():
                    return False
                    
                if not isinstance(feature['importance_score'], (int, float)) or \
                   not (1 <= feature['importance_score'] <= 10):
                    return False
                    
                if not isinstance(feature['feature_type'], str) or \
                   feature['feature_type'] not in {'DECISION', 'ACTION', 'OBJECTIVE', 'STATUS', 'INSIGHT', 'CONTEXT'}:
                    return False
                    
                if not isinstance(feature['certainty_score'], (int, float)) or \
                   not (0 <= feature['certainty_score'] <= 100):
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error verifying features: {str(e)}")
            return False

    def identify_salient_features(self, atomic_facts: List[Dict[str, str]]):
        """
        Extract and rank salient features from atomic facts.
        Returns tuple of (features, is_complete)
        """
        default_template = [{
            "feature": "Default feature",
            "reasoning": "Fallback reasoning due to parsing error",
            "importance_score": 5,
            "feature_type": "CONTEXT",
            "certainty_score": 50
        }]
        # [TODO]: Ktra ranking
        system_prompt = """
        Bạn là một AI có nhiệm vụ xác định và xếp hạng các đặc điểm (features) nổi bật nhất từ các fact nguyên tử được trích xuất từ biên bản/cuộc họp. Mục tiêu của bạn là trích xuất và ưu tiên những thông tin quan trọng dựa trên mức độ đóng góp của chúng đối với bản tóm tắt cuối cùng.

        Hướng dẫn:
        1. Phân tích kỹ các fact nguyên tử được cung cấp
        2. Đối với mỗi feature được xác định, trước tiên hãy suy luận về mức độ quan trọng của nó bằng cách xem xét:
           - Đây có phải là một điểm quyết định quan trọng hoặc kết quả lớn đã ĐƯỢC QUYẾT ĐỊNH hay không?
           - Nó có đại diện cho một hành động/yêu cầu/chỉ đạo mà ai đó VẪN PHẢI thực hiện hay không?
           - Nó có phải là một mục tiêu/đích đến/kế hoạch trong tương lai (một con số, một năm, một nguyện vọng) được đề xuất nhưng BẢN THÂN NÓ KHÔNG PHẢI là một chỉ đạo dành cho bất kỳ ai hay không?
           - Nó có mô tả TRẠNG THÁI HIỆN TẠI của một quá trình phê duyệt/quyết định hay không (ví dụ: vẫn đang chờ xử lý, chưa có kết luận, chưa xác định thời hạn)?
           - Nó có phải là một insight quan trọng hoặc một điểm thảo luận đáng chú ý hay không?
           - Nó đóng góp như thế nào vào bối cảnh tổng thể?

        3. Dựa trên quá trình đánh giá ở trên, sau đó:
           a. Gán một điểm quan trọng (importance score) từ 1-10, trong đó:
              - 10: Các quyết định mang tính then chốt, kết quả lớn, các đầu việc/hành động quan trọng
              - 7-9: Các thảo luận quan trọng, insight đáng kể, mục tiêu/chỉ tiêu quan trọng, các phát biểu về trạng thái quan trọng
              - 4-6: Thông tin hỗ trợ, thông tin cung cấp bối cảnh
              - 1-3: Các chi tiết mang tính nền tảng/bối cảnh

           b. Xác định loại feature — hãy lựa chọn cẩn thận vì sự phân biệt này rất quan trọng đối với các bước xử lý phía sau:
              - DECISION: Một vấn đề đã ĐƯỢC KẾT LUẬN/THỐNG NHẤT/PHÊ DUYỆT rõ ràng
              - ACTION: Một nhiệm vụ, yêu cầu hoặc chỉ đạo cụ thể mà ai đó phải thực hiện
                (chỉ sử dụng loại này khi nguồn thực sự nêu rõ yêu cầu/chỉ đạo/bắt buộc thực hiện điều gì đó — KHÔNG sử dụng loại này chỉ vì một chủ đề nghe có vẻ quan trọng)
              - OBJECTIVE: Một mục tiêu, đích đến, kế hoạch, dự báo hoặc nguyện vọng trong tương lai
                (ví dụ: "sản lượng dự kiến 18-20 triệu TEU vào năm 2030", "mục tiêu xây cảng xanh vào năm 2050") — đây là thông tin mô tả về MỘT KẾ HOẠCH, KHÔNG PHẢI là một chỉ đạo dành cho bất kỳ ai.
                KHÔNG gán OBJECTIVE thành ACTION/DECISION chỉ vì nó có vẻ quan trọng.
              - STATUS: Trạng thái hiện tại của một quá trình quyết định/phê duyệt
                (ví dụ: "chưa được phê duyệt", "chưa xác định thời hạn trình", "đang chờ ý kiến của X")
              - INSIGHT: Những nhận định, phát hiện hoặc kết luận đáng chú ý
              - CONTEXT: Thông tin nền hoặc thông tin hỗ trợ

        4. Cung cấp điểm độ chắc chắn (certainty score) từ 0-100%, thể hiện mức độ tự tin của bạn đối với đánh giá trên

        *Không được hallucinate/bịa đặt bất kỳ thông tin nào; chỉ được sử dụng thông tin có trong các fact nguyên tử được cung cấp*
        *Nếu có thể, hãy sắp xếp các feature có mức độ quan trọng cao nhất trước, tiếp theo là các feature ít quan trọng hơn, và cuối cùng là các feature có mức độ quan trọng thấp nhất để duy trì thứ tự ưu tiên*

        QUAN TRỌNG: Câu trả lời của bạn phải là một JSON object hợp lệ cho mỗi feature. Mỗi object phải chứa chính xác các trường sau:
        - "feature": (string) Nội dung của feature được xác định
        - "reasoning": (string) Giải thích chi tiết về mức độ quan trọng, có xem xét đến bối cảnh của feature đó; không được hallucinate/bịa đặt thông tin
        - "importance_score": (number) Điểm từ 1-10
        - "feature_type": (string) Một trong các giá trị: DECISION, ACTION, OBJECTIVE, STATUS, INSIGHT, CONTEXT
        - "certainty_score": (number) Điểm từ 0-100
        """

        user_prompt = f"""
        Hãy phân tích các fact nguyên tử này và cung cấp các feature được xếp hạng theo mức độ quan trọng, dưới định dạng JSON hợp lệ nghiêm ngặt:

        {atomic_facts}

        Hãy nhớ: Câu trả lời phải là một danh sách các JSON object hợp lệ, trong đó mỗi object chứa chính xác các trường sau:
        - "feature" (string)
        - "reasoning" (string)
        - "importance_score" (number từ 1-10)
        - "feature_type" (string: DECISION/ACTION/OBJECTIVE/STATUS/INSIGHT/CONTEXT)
        - "certainty_score" (number từ 0-100)
        """

        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "Salient Feature generation",    
                category="Salient Feature generation", 
                log_base_path=self.log_base_path
            )             
            # Clean up the response
            enriched_template = _clean_response(response)
            
            # Verify completeness
            is_complete = self.verify_feature_completeness(enriched_template)
            
            if is_complete:
                # Parse the complete output
                try:
                    features = json.loads(enriched_template)
                except json.JSONDecodeError:
                    features = ast.literal_eval(enriched_template)
                return features, True
            else:
                logging.warning("Incomplete or invalid features output")
                return default_template, False
                
        except Exception as e:
            logging.error(f"Unexpected error in identify_salient_features: {str(e)}")
            return default_template, False

    def generate_outline(self, important_features: List[Dict]) -> List[str]:
        """
        Generate the sub-heading titles for the "II. NỘI DUNG" section of a
        formal "Thông báo kết luận" document.

        The overall document skeleton (THÔNG BÁO title, đoạn mở, I. THÀNH
        PHẦN THAM DỰ, II. NỘI DUNG, đoạn kết) is FIXED and handled by
        docx_writer.py — this method only produces the ordered list of
        sub-topic titles that belong under II. NỘI DUNG, grouped from the
        chair's ([CHAIR]-tagged) decisions/high-priority points.

        Returns a list of clean section titles (no leading numbers/bullets —
        numbering is applied when the document is rendered).
        """
        system_prompt = """
    NGÔN NGỮ: Phải trả lời bằng tiếng Việt.

    Bạn đang chuẩn bị đề mục cho phần "II. NỘI DUNG" của một văn bản
    "Thông báo kết luận" (thể loại văn bản hành chính Đảng/Nhà nước),
    KHÔNG PHẢI cho một bản tóm tắt cuộc họp thông thường.

    MỤC TIÊU CỐT LÕI:
    Outline phải phản ánh CÁC Ý KIẾN KẾT LUẬN/CHỈ ĐẠO CỦA CHỦ TRÌ,
    không phải toàn bộ nội dung được trình bày trong cuộc họp.

    ============================================================
    1. NGUYÊN TẮC NGUỒN — QUAN TRỌNG NHẤT
    ============================================================

    Mỗi feature có thể có nguồn [CHAIR] hoặc [PRESENTER].

    - CHỈ feature có nguồn [CHAIR] mới được phép tạo ra một đề mục
      kết luận trong outline.
    - Feature [PRESENTER] KHÔNG được tự tạo thành đề mục kết luận,
      kể cả khi feature đó có feature_type = ACTION hoặc DECISION.
    - Nội dung [PRESENTER] chỉ có thể được sử dụng làm thông tin nền
      hoặc chất liệu hỗ trợ cho một kết luận [CHAIR] đã tồn tại.
    - Tuyệt đối không suy luận rằng Chair đã đồng ý, thống nhất,
      phê duyệt, yêu cầu hoặc giao nhiệm vụ chỉ vì Presenter đã
      trình bày hoặc đề xuất nội dung đó.
    - Nếu một nội dung chỉ xuất hiện ở [PRESENTER] mà không có kết luận,
      chỉ đạo, yêu cầu hoặc xác nhận tương ứng từ [CHAIR], nội dung đó
      KHÔNG được tạo thành một mục riêng trong outline.

    Nói cách khác:

        [CHAIR] + DECISION  → có thể tạo mục
        [CHAIR] + ACTION    → có thể tạo mục
        [CHAIR] + STATUS    → có thể tạo mục nếu quan trọng
        [CHAIR] + OBJECTIVE → có thể tạo mục nếu Chair thực sự đề cập
                              như một nội dung kết luận/mục tiêu
        [CHAIR] + INSIGHT   → chỉ tạo mục nếu đây là nhận định quan trọng
                              được Chair nêu trong kết luận
        [CHAIR] + CONTEXT   → chủ yếu làm chất liệu hỗ trợ

        [PRESENTER] + bất kỳ feature_type nào
            → KHÔNG được tự tạo mục kết luận.

    ============================================================
    2. PHÂN BIỆT FEATURE_TYPE
    ============================================================

    Mỗi feature có "feature_type" là một trong:
    DECISION, ACTION, OBJECTIVE, STATUS, INSIGHT, CONTEXT.

    Feature_type quyết định BẢN CHẤT của nội dung, nhưng KHÔNG thay thế
    điều kiện về nguồn [CHAIR]/[PRESENTER].

    - DECISION:
      Nội dung đã được Chair quyết định, thống nhất, phê duyệt hoặc
      kết luận rõ ràng.
      → Có thể tạo một đề mục nếu đây là một chủ đề kết luận độc lập.

    - ACTION:
      Nhiệm vụ, yêu cầu, chỉ đạo hoặc việc cần thực hiện mà Chair
      yêu cầu/chỉ đạo rõ ràng.
      → Đây là loại ưu tiên cao nhất để tạo đề mục.

    - STATUS:
      Trạng thái hiện tại của một vấn đề/quá trình quyết định/phê duyệt,
      ví dụ "chưa được phê duyệt", "đang chờ ý kiến", "chưa xác định
      thời hạn".
      → Có thể tạo mục nếu trạng thái này là nội dung quan trọng mà
      Chair cần ghi nhận trong kết luận.
      → Không được biến STATUS thành DECISION hoặc ACTION.

    - OBJECTIVE:
      Mục tiêu, chỉ tiêu, kế hoạch, dự kiến hoặc định hướng tương lai.
      → Không tự biến OBJECTIVE thành ACTION.
      → Nếu chỉ là mục tiêu được Presenter trình bày mà Chair không
        kết luận về nó, không tạo mục.

    - INSIGHT:
      Nhận định hoặc phát hiện quan trọng.
      → Chỉ tạo mục nếu Chair thực sự đưa nhận định đó vào ý kiến
        kết luận và nó đủ quan trọng để trở thành một chủ đề riêng.

    - CONTEXT:
      Thông tin nền, dữ liệu hỗ trợ hoặc bối cảnh.
      → Không tạo mục riêng chỉ vì feature có importance_score cao.
      → Chỉ dùng để hỗ trợ một chủ đề kết luận [CHAIR] phù hợp.

    ============================================================
    3. THỨ TỰ ƯU TIÊN
    ============================================================

    Sau khi đã lọc CHỈ các feature có nguồn [CHAIR], ưu tiên:

    1) ACTION của Chair
       → Các chỉ đạo/yêu cầu/nhiệm vụ cụ thể.

    2) DECISION của Chair
       → Các nội dung đã được thống nhất/quyết định/phê duyệt.

    3) STATUS quan trọng của Chair
       → Đặc biệt các trạng thái liên quan trực tiếp đến việc
         quyết định, phê duyệt hoặc triển khai đề án.

    4) OBJECTIVE của Chair
       → Mục tiêu/kế hoạch/định hướng được Chair thực sự nêu ra.

    5) INSIGHT quan trọng của Chair.

    6) CONTEXT của Chair.

    Importance_score được sử dụng để xếp hạng trong cùng một nhóm
    ưu tiên, nhưng KHÔNG được phép khiến CONTEXT/INSIGHT/OBJECTIVE
    của Presenter vượt lên trên ACTION/DECISION của Chair.

    ============================================================
    4. NHÓM CÁC FEATURE CÙNG CHỦ ĐỀ
    ============================================================

    - Các feature cùng một chủ đề kết luận phải được nhóm vào MỘT mục.
    - Một ACTION hoặc DECISION của Chair có thể kéo theo các STATUS,
      OBJECTIVE, INSIGHT hoặc CONTEXT liên quan làm nội dung hỗ trợ.
    - Tuy nhiên, tiêu đề mục phải phản ánh chủ đề của ACTION/DECISION
      của Chair, không được lấy OBJECTIVE/CONTEXT làm tiêu đề thay thế.
    - Không tạo nhiều mục riêng chỉ vì có nhiều feature mô tả cùng
      một vấn đề.

    Ví dụ:

        [CHAIR] ACTION: Rà soát, hoàn thiện Tờ trình...
        [CHAIR] OBJECTIVE: Tờ trình cần bảo đảm...
        [PRESENTER] CONTEXT: Tờ trình hiện có...

    → Chỉ tạo một mục:

        "Về rà soát, hoàn thiện Tờ trình"

    Không tạo thành ba mục riêng.

    ============================================================
    5. QUY TẮC ĐẶT TIÊU ĐỀ
    ============================================================

    Mỗi tiêu đề phải:

    - Là một chủ đề kết luận/chỉ đạo độc lập.
    - Ngắn gọn nhưng đủ cụ thể.
    - Phản ánh đúng nội dung thực chất của feature [CHAIR].
    - Không thêm thông tin không có trong feature.
    - Không tự thêm tên cơ quan, đơn vị, thời hạn, số liệu hoặc nhiệm vụ
      nếu feature không nêu.
    - Không dùng các tiêu đề chung chung như:
        "Tổng quan cuộc họp"
        "Nội dung cuộc họp"
        "Bước tiếp theo"
        "Các vấn đề khác"

    Có thể sử dụng các dạng:

        "Về hoàn thiện Tờ trình"
        "Về rà soát tiến độ thực hiện"
        "Về phương án triển khai..."
        "Về việc phối hợp giữa các đơn vị"
        "Về tiến độ..."
        "Về các nội dung chưa được phê duyệt"

    Tiêu đề không cần bắt đầu bằng "Đề nghị", "Yêu cầu", "Giao".
    Tiêu đề nên là tên chủ đề hành chính, không phải câu mệnh lệnh đầy đủ.

    ============================================================
    6. KHÔNG HALLUCINATION
    ============================================================

    - Không tạo đề mục từ thông tin không có trong features.
    - Không suy luận kết luận của Chair từ nội dung Presenter.
    - Không biến một mục tiêu thành nhiệm vụ.
    - Không biến một trạng thái "chưa..." thành quyết định đã hoàn tất.
    - Không thêm số liệu, thời hạn, tên cơ quan, tên người hoặc hành động
      không được nêu rõ.
    - Nếu không có đủ thông tin để tạo một tiêu đề cụ thể, không được
      tự bổ sung nội dung.

    ============================================================
    7. TRÌNH TỰ CÁC MỤC
    ============================================================

    Sau khi xác định các chủ đề cần đưa vào outline:

    - Sắp xếp theo trình tự logic của các ý kiến kết luận của Chair.
    - Nếu không xác định được trình tự phát biểu, ưu tiên:
        ACTION/DECISION quan trọng
        → STATUS liên quan
        → OBJECTIVE/INSIGHT hỗ trợ.
    - Không đảo lộn các chủ đề một cách tùy tiện.
    - Không để các feature phụ làm thay đổi thứ tự logic của các
      kết luận chính.

    ============================================================
    8. ĐỊNH DẠNG ĐẦU RA — BẮT BUỘC
    ============================================================

    - Chỉ trả về danh sách các tiêu đề.
    - Mỗi dòng là ĐÚNG MỘT tiêu đề.
    - Không đánh số.
    - Không gạch đầu dòng.
    - Không thêm giải thích.
    - Không thêm reasoning.
    - Không thêm JSON.
    - Không thêm Markdown.
    - Không thêm dòng trống.
    - Không thêm tiêu đề chung ở đầu hoặc cuối.
    """

        user_prompt = f"""
        Dựa trên các feature được cung cấp dưới đây, hãy tạo danh sách tiêu đề
        các mục cho phần "II. NỘI DUNG" của "Thông báo kết luận".
    
        IMPORTANT:
        - Trước tiên phải xác định nguồn của từng feature ([CHAIR] hay
          [PRESENTER]).
        - CHỈ feature có nguồn [CHAIR] mới được phép tạo đề mục kết luận.
        - Feature [PRESENTER] chỉ được dùng để hiểu/bổ sung bối cảnh cho
          feature [CHAIR] liên quan; không được tự tạo đề mục.
        - Ưu tiên ACTION và DECISION của [CHAIR].
        - STATUS của [CHAIR] được đưa vào nếu thực sự quan trọng.
        - OBJECTIVE/INSIGHT/CONTEXT của [CHAIR] chỉ tạo mục riêng khi có
          đủ vai trò và mức độ quan trọng; nếu không thì dùng làm chất liệu
          hỗ trợ cho mục ACTION/DECISION liên quan.
        - Không được biến OBJECTIVE thành ACTION.
        - Không được biến STATUS thành DECISION.
        - Không được suy luận ý kiến của Chair từ nội dung Presenter.
        - Không được thêm bất kỳ thông tin nào ngoài các feature được cung cấp.
    
        FEATURES:
        {important_features}
    
        Chỉ trả về danh sách tiêu đề, mỗi tiêu đề một dòng, không đánh số,
        không gạch đầu dòng và không giải thích.
        """

        message = ModelHandler.build_message(system_prompt, user_prompt)
        response = ModelHandler.call_model_with_retry(
            self.client, message, self.model, "Outline Generation",
            category="Outline Generation",
            log_base_path=self.log_base_path
            )
        return self._clean_outline(response)

    @staticmethod
    def _clean_outline(response: str) -> List[str]:
        """
        Turn the raw model response into a clean list of section titles:
        drop empty lines and strip any numbering/bullet markers the model
        might still have added on its own (defensive — numbering is applied
        later when the document is rendered, to avoid double-numbering).
        """
        titles: List[str] = []
        leading_marker = re.compile(r'^\s*(?:[-*•]|\d+[.)])\s*')
        for line in response.split('\n'):
            line = leading_marker.sub('', line).strip()
            if line:
                titles.append(line)
        return titles