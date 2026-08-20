from model_handler import ModelHandler
import json
import ast
import logging
from hallucination_validator import HallucinationValidator
from utils import _clean_response

def track_regeneration_step(
    regeneration_logs,
    chunk_text,
    original_facts,
    original_validation,
    regenerated_facts=None,
    regenerated_validation=None
):
    """
    Store/log the before/after results for external analysis. 
    
    Args:
        regeneration_logs (list): Reference to a list storing all regeneration events.
        chunk_text (str): The exact transcript chunk being processed.
        original_facts (list): The atomic facts generated initially.
        original_validation (dict): The hallucination validation result for original_facts.
        regenerated_facts (list): The atomic facts after regeneration (if any).
        regenerated_validation (dict): The validation result for regenerated_facts (if any).
    """
    data_to_log = {
        "chunk_text": chunk_text,
        "original_facts": original_facts,
        "original_overall_score": original_validation.get('overall_score', None),
        "original_feedback": original_validation.get('feedback', None),
        "regenerated_facts": regenerated_facts,
        "regenerated_overall_score": (
            regenerated_validation.get('overall_score', None) if regenerated_validation else None
        ),
        "regenerated_feedback": (
            regenerated_validation.get('feedback', None) if regenerated_validation else None
        )
    }
    # Append to the in-memory log; you can later dump it to a file or DB as needed.
    regeneration_logs.append(data_to_log)


class AtomicFacts:
    def __init__(self, client, model,log_base_path):
        self.client = client
        self.model = model
        self.log_base_path=log_base_path
        self.previous_chunk = None
        self.validator = HallucinationValidator(client, model,log_base_path)
        self.MAX_REGENERATION_ATTEMPTS = 3
        self.HALLUCINATION_THRESHOLD = 30

         # A list to store before/after details for regenerations.
        self.regeneration_logs = []

    def verify_atomic_facts_format(self, output: str) -> bool:
        """
        Verify if the atomic facts output is complete and properly formatted.
        Returns True if output is valid, False otherwise.
        """
        try:
            # Try parsing the output as JSON first
            try:
                facts = json.loads(output)
            except json.JSONDecodeError:
                try:
                    facts = ast.literal_eval(output)
                except (ValueError, SyntaxError):
                    logging.error("Failed to parse atomic facts output")
                    return False
            
            # Ensure it's a list
            if not isinstance(facts, list):
                logging.error("Atomic facts output is not a list")
                return False
            
            # Required fields for each fact
            required_fields = {'fact', 'context', 'verbose_context'}
            
            # Check each fact
            for fact in facts:
                # Check if it's a dictionary with all required fields
                if not isinstance(fact, dict):
                    logging.error(f"Fact is not a dictionary: {fact}")
                    return False
                
                if not all(field in fact for field in required_fields):
                    logging.error(f"Missing required fields in fact: {fact}")
                    return False
                
                # Check if fields are non-empty strings
                if not all(isinstance(fact[field], str) and fact[field].strip() 
                          for field in required_fields):
                    logging.error(f"Invalid field values in fact: {fact}")
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error verifying atomic facts: {str(e)}")
            return False


    def regenerate_atomic_facts(self, chunk, previous_chunk_context,feedback):
        """
        Regenerate atomic facts while addressing validation feedback.
        Uses same rigorous validation as initial extraction plus feedback handling.
        Returns new atomic facts.
        """
        system_prompt = """
                Bạn là chuyên gia bóc tách nội dung cuộc họp hành chính thành các đơn vị thông tin nguyên tử. Đầu ra của bạn sẽ được dùng để soạn Thông báo kết luận cuộc họp, nên tiêu chí cao nhất là KHÔNG BỎ SÓT chỉ đạo, không phải cô đọng nội dung.
                
                QUY TẮC QUAN TRỌNG:
                1. Đầu ra phải là một danh sách JSON hợp lệ gồm nhiều object.
                2. TUYỆT ĐỐI KHÔNG thêm thông tin không có trong biên bản.
                3. Bỏ qua các nội dung không rõ ràng hoặc mơ hồ.
                4. Mỗi “fact” phải là thông tin nguyên tử (chỉ chứa MỘT sự kiện hoặc ý đơn lẻ).
                5. TUYỆT ĐỐI KHÔNG tự suy luận hoặc đoán thêm.
        
                HƯỚNG DẪN NỘI DUNG – TUÂN THỦ NGHIÊM NGẶT:
                1. CHỈ BAO GỒM:
                    - Phát biểu rõ ràng, cụ thể.
                    - Các thông tin đầy đủ và có ý nghĩa.
                    - Các đầu việc cần làm hoặc quyết định đã được đưa ra.
                    - Các điểm thảo luận quan trọng.
                    - Sự kiện hoặc kết quả cụ thể.
        
                2. HOÀN TOÀN BỎ QUA:
                   - Các câu đệm, câu xã giao (“OK”, “Đúng rồi”, “Vâng”...)
                   - Các câu xác nhận chung chung.
                   - Câu nói chưa trọn ý hoặc mơ hồ.
                   - Các ký hiệu, lỗi biên bản như {"disfmarker"} hoặc {"vocalsound"}
                   - Các cuộc hội thoại bên lề.
                   - Các thông tin lặp lại.
                   - Phát biểu không đủ rõ ràng.
        
        
                3. Mỗi sự kiện (“fact”) được chọn cần:
                   - "fact": Một phát biểu đơn nhất, nguyên tử.
                   - "context": Phần ngữ cảnh hiện tại liên quan, BẮT BUỘC phải đưa tiền tố tag vai trò [CHAIR] hoặc [PRESENTER] chính xác như trong biên bản gốc vào đầu chuỗi này; không thêm tag khi nguồn gốc không rõ ràng/đan xen.
                   - "verbose_context": Bối cảnh rộng hơn, có lịch sử trước đó nếu cần thiết.
        
                4. YÊU CẦU TAG VAI TRÒ (RẤT QUAN TRỌNG – TUYỆT ĐỐI KHÔNG ĐƯỢC LÀM MẤT):
                   - Các dòng biên bản đầu vào luôn có sẵn tag [CHAIR] hoặc [PRESENTER] ở đầu mỗi lượt nói.
                   - Mỗi “fact” trích xuất, ở trường “context” PHẢI giữ đúng tag vai trò đó đầu chuỗi (thí dụ: “[CHAIR] ...”, “[PRESENTER] ...”).
                   - KHÔNG đưa tag này vào trường “fact” hay “verbose_context”.
                   - KHÔNG dịch, viết lại, hoặc tự chế ra tag nếu không xác định được nguồn (bỏ trống tag ở những trường hợp này).
        
                Định dạng đầu ra:
                Trả lại một danh sách JSON với mỗi object gồm chính xác 3 trường:
                [
                    {
                        "fact": "Phát biểu sự thật nguyên tử, rõ ràng",
                        "context": "[CHAIR] Ngữ cảnh trực tiếp và tác động",
                        "verbose_context": "Bối cảnh tổng thể, bao gồm lịch sử trước đó nếu cần"
                    },
                    ...
                ]
        
                Ví dụ đầu ra hợp lệ:
                [
                    {
                        "fact": "Nhóm đã đồng ý ra mắt sản phẩm vào quý 3",
                        "context": "[CHAIR] Thảo luận về các ràng buộc thời gian và điều kiện thị trường",
                        "verbose_context": "Sau nhiều lần trì hoãn và phân tích thị trường, quý 3 được chọn để đạt hiệu quả cao nhất"
                    }
                ]
        
                Ví dụ đầu ra KHÔNG hợp lệ, CẤM sử dụng:
                    - Dùng từ đệm: {"fact": "OK, chúng ta sẽ làm vậy"}
                    - Phát biểu không rõ ý: {"fact": "Có lẽ chúng ta nên..."}
                    - Lỗi/ký hiệu biên bản: {"fact": "Speaker1 {disfmarker}"}
                    - Phát biểu đa ý, không nguyên tử: {"fact": "Nhóm đã thảo luận về thời gian, ngân sách và nguồn lực"}
        
                YÊU CẦU ĐẦU RA:
                    - JSON LIST, KHÔNG bọc trong code block.
                    - Nội dung câu trả lời viết hoàn toàn bằng tiếng Việt.
                    - Mỗi object chỉ chứa đúng ba trường: fact, context, verbose_context.
                    - Luôn giữ chính xác tag vai trò (nếu có) ở đầu trường "context".
        
                NHẮC LẠI: Dịch hoàn toàn yêu cầu sang tiếng Việt và TUÂN THỦ chặt chẽ cấu trúc, quy tắc trên khi xử lý bất kỳ đầu vào nào.
                """

        user_prompt = f"""
        TẠO LẠI CÁC FACT NGUYÊN TỬ CHO ĐOẠN VĂN NÀY:

        {previous_chunk_context}


        VĂN BẢN NGUỒN:
        {chunk}


        PHẢN HỒI TRƯỚC ĐÓ CẦN ĐƯỢC KHẮC PHỤC:
        {feedback}

        YÊU CẦU:
        1. Khắc phục TẤT CẢ các vấn đề được đề cập trong phản hồi
        2. Tuân thủ TẤT CẢ các quy tắc của quá trình trích xuất ban đầu:
           - Chỉ sử dụng thông tin được nêu rõ trong nguồn
           - Chia nhỏ thành các fact nguyên tử
           - Cung cấp ngữ cảnh chính xác
           - Không suy luận hoặc giả định
           - Bỏ qua nội dung không rõ ràng
           - Đảm bảo định dạng JSON hợp lệ
           - Bao gồm tất cả các trường bắt buộc

        3. Yêu cầu bổ sung khi tạo lại:
           - Xử lý cụ thể từng điểm được nêu trong phản hồi
           - Loại bỏ tất cả các hallucination đã được xác định trước đó
           - Kiểm tra lại kỹ tính chính xác của ngữ cảnh
           - Đảm bảo không phát sinh thêm vấn đề mới
           - Duy trì tính đầy đủ trong khi khắc phục các vấn đề

        4. Các bước xác minh đối với từng fact:
           - Fact này có được nêu rõ trong nguồn hay không?
           - Ngữ cảnh có chính xác và được nguồn hỗ trợ hay không?
           - Tất cả các thành phần của fact có thể được kiểm chứng hay không?
           - Các vấn đề trước đó đã được khắc phục hay chưa?
           - Fact này đã đủ tính nguyên tử hay chưa?

        Tạo ra tập hợp đầy đủ và đã được hiệu chỉnh của các fact nguyên tử."""

        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "regeneration",    
                category="Fact Regenration", 
                 log_base_path=self.log_base_path,
                verbose=True, max_tokens=8000
            )

            enriched_template = _clean_response(response)
            if self.verify_atomic_facts_format(enriched_template):
                try:
                    return json.loads(enriched_template)
                except json.JSONDecodeError:
                    return ast.literal_eval(enriched_template)
            return None

        except Exception as e:
            logging.error(f"Error regenerating atomic facts: {str(e)}")
            return None

    def Break_into_atomic_facts(self, chunk,log_base_path):
        """
        Break a chunk into atomic facts with context.
        Returns a list of dictionaries, each containing fact, context, and verbose_context.
        """
        default_template = [{
            "fact": "Default fact due to parsing error",
            "context": "Error occurred during processing",
            "verbose_context": "Unable to process chunk properly"
        }]

        system_prompt = """
        Bạn là chuyên gia bóc tách nội dung cuộc họp hành chính thành các đơn vị thông tin nguyên tử. Đầu ra của bạn sẽ được dùng để soạn Thông báo kết luận cuộc họp, nên tiêu chí cao nhất là KHÔNG BỎ SÓT chỉ đạo, không phải cô đọng nội dung.
        
        QUY TẮC QUAN TRỌNG:
        1. Đầu ra phải là một danh sách JSON hợp lệ gồm nhiều object.
        2. TUYỆT ĐỐI KHÔNG thêm thông tin không có trong biên bản.
        3. Bỏ qua các nội dung không rõ ràng hoặc mơ hồ.
        4. Mỗi “fact” phải là thông tin nguyên tử (chỉ chứa MỘT sự kiện hoặc ý đơn lẻ).
        5. TUYỆT ĐỐI KHÔNG tự suy luận hoặc đoán thêm.

        HƯỚNG DẪN NỘI DUNG – TUÂN THỦ NGHIÊM NGẶT:
        1. CHỈ BAO GỒM:
            - Phát biểu rõ ràng, cụ thể.
            - Các thông tin đầy đủ và có ý nghĩa.
            - Các đầu việc cần làm hoặc quyết định đã được đưa ra.
            - Các điểm thảo luận quan trọng.
            - Sự kiện hoặc kết quả cụ thể.

        2. HOÀN TOÀN BỎ QUA:
           - Các câu đệm, câu xã giao (“OK”, “Đúng rồi”, “Vâng”...)
           - Các câu xác nhận chung chung.
           - Câu nói chưa trọn ý hoặc mơ hồ.
           - Các ký hiệu, lỗi biên bản như {"disfmarker"} hoặc {"vocalsound"}
           - Các cuộc hội thoại bên lề.
           - Các thông tin lặp lại.
           - Phát biểu không đủ rõ ràng.


        3. Mỗi sự kiện (“fact”) được chọn cần:
           - "fact": Một phát biểu đơn nhất, nguyên tử.
           - "context": Phần ngữ cảnh hiện tại liên quan, BẮT BUỘC phải đưa tiền tố tag vai trò [CHAIR] hoặc [PRESENTER] chính xác như trong biên bản gốc vào đầu chuỗi này; không thêm tag khi nguồn gốc không rõ ràng/đan xen.
           - "verbose_context": Bối cảnh rộng hơn, có lịch sử trước đó nếu cần thiết.

        4. YÊU CẦU TAG VAI TRÒ (RẤT QUAN TRỌNG – TUYỆT ĐỐI KHÔNG ĐƯỢC LÀM MẤT):
           - Các dòng biên bản đầu vào luôn có sẵn tag [CHAIR] hoặc [PRESENTER] ở đầu mỗi lượt nói.
           - Mỗi “fact” trích xuất, ở trường “context” PHẢI giữ đúng tag vai trò đó đầu chuỗi (thí dụ: “[CHAIR] ...”, “[PRESENTER] ...”).
           - KHÔNG đưa tag này vào trường “fact” hay “verbose_context”.
           - KHÔNG dịch, viết lại, hoặc tự chế ra tag nếu không xác định được nguồn (bỏ trống tag ở những trường hợp này).

        Định dạng đầu ra:
        Trả lại một danh sách JSON với mỗi object gồm chính xác 3 trường:
        [
            {
                "fact": "Phát biểu sự thật nguyên tử, rõ ràng",
                "context": "[CHAIR] Ngữ cảnh trực tiếp và tác động",
                "verbose_context": "Bối cảnh tổng thể, bao gồm lịch sử trước đó nếu cần"
            },
            ...
        ]

        Ví dụ đầu ra hợp lệ:
        [
            {
                "fact": "Nhóm đã đồng ý ra mắt sản phẩm vào quý 3",
                "context": "[CHAIR] Thảo luận về các ràng buộc thời gian và điều kiện thị trường",
                "verbose_context": "Sau nhiều lần trì hoãn và phân tích thị trường, quý 3 được chọn để đạt hiệu quả cao nhất"
            }
        ]

        Ví dụ đầu ra KHÔNG hợp lệ, CẤM sử dụng:
            - Dùng từ đệm: {"fact": "OK, chúng ta sẽ làm vậy"}
            - Phát biểu không rõ ý: {"fact": "Có lẽ chúng ta nên..."}
            - Lỗi/ký hiệu biên bản: {"fact": "Speaker1 {disfmarker}"}
            - Phát biểu đa ý, không nguyên tử: {"fact": "Nhóm đã thảo luận về thời gian, ngân sách và nguồn lực"}

        YÊU CẦU ĐẦU RA:
            - JSON LIST, KHÔNG bọc trong code block.
            - Nội dung câu trả lời viết hoàn toàn bằng tiếng Việt.
            - Mỗi object chỉ chứa đúng ba trường: fact, context, verbose_context.
            - Luôn giữ chính xác tag vai trò (nếu có) ở đầu trường "context".

        NHẮC LẠI: Dịch hoàn toàn yêu cầu sang tiếng Việt và TUÂN THỦ chặt chẽ cấu trúc, quy tắc trên khi xử lý bất kỳ đầu vào nào.
        """
        
        previous_chunk_context = ""
        if self.previous_chunk:
            previous_chunk_context = f"\nPrevious chunk for context:\n{self.previous_chunk}\n"

        user_prompt = f"""
        Hãy phân tích đoạn transcript sau thành các sự kiện (fact) nhỏ gọn với đầy đủ ngữ cảnh.
        - PHẢI trả về danh sách JSON hợp lệ.
        - Mỗi sự kiện ("fact") bắt buộc phải có đủ ba trường: "fact", "context", "verbose_context".
        - Chỉ bao gồm thông tin rõ ràng, cụ thể, đã được phát biểu trực tiếp trong đoạn transcript.
        - Loại bỏ tất cả từ đệm, lời xác nhận, nội dung không liên quan, hoặc những câu thoại không mang thông tin (filler words, acknowledgments, artifacts).
        - Nếu một câu phát biểu có nhiều sự kiện, hãy tách thành nhiều fact riêng biệt (atomic facts).
        - Bỏ qua mọi nội dung không rõ ràng hoặc mơ hồ.
        - GIỮ NGUYÊN TAG VAI TRÒ NGƯỜI NÓI ("[CHAIR]", "[PRESENTER]", v.v.) Ở ĐẦU trường "context" của mỗi fact, theo quy tắc SPEAKER ROLE TAG.
        - (Nếu có ngữ cảnh từ đoạn trước, chèn vào đúng vị trí {previous_chunk_context})

        Ngữ cảnh từ các đoạn trước (nếu có):  
        {previous_chunk_context}

        Đoạn transcript hiện tại:  
        {chunk}

        YÊU CẦU:  
        Trả về một danh sách JSON, mỗi phần tử là một object có 3 trường:  
        - "fact" (thông tin sự kiện gốc, đúng nguyên văn, loại bỏ những phần không cần thiết)  
        - "context" (câu gốc hoặc đoạn gốc chứa fact, bắt đầu bằng SPEAKER ROLE TAG)  
        - "verbose_context" (ngữ cảnh mở rộng hoặc giải thích nếu cần, có thể giữ nguyên cả đoạn lời nói của speaker, cũng bắt đầu bằng SPEAKER ROLE TAG)
        """
        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "regeneration",    
                category="Fact Extraction", 
                log_base_path=self.log_base_path,
                verbose=True, max_tokens=8000
            )

            logging.info(f'Output = {response}')

            enriched_template = _clean_response(response)
            
            logging.info(f'Output = {enriched_template}')
            
            # Verify format
            is_valid = self.verify_atomic_facts_format(enriched_template)
            
            if is_valid:
                try:
                    atomic_facts = json.loads(enriched_template)
                except json.JSONDecodeError:
                    atomic_facts = ast.literal_eval(enriched_template)
                
                # Check for hallucinations
                validation_result = self.validator.validate_atomic_facts(atomic_facts,previous_chunk_context, chunk)
                logging.info(f"Validation_results = {json.dumps(validation_result)}")

                # If hallucination score is too high, attempt regeneration
                attempt_count = 1
                current_facts = atomic_facts
                
                while (validation_result['overall_score'] > self.HALLUCINATION_THRESHOLD 
                       and attempt_count < self.MAX_REGENERATION_ATTEMPTS):
                    
                    logging.info(f"Hallucination score too high ({validation_result['overall_score']}), attempting regeneration")
                    
                    # Log the original facts + validation before first regeneration
                    if attempt_count == 1:
                        track_regeneration_step(
                            self.regeneration_logs,
                            chunk,
                            current_facts,
                            validation_result
                        )
                    
                    regenerated_facts = self.regenerate_atomic_facts(chunk, previous_chunk_context,validation_result['feedback'])
                    


                    if regenerated_facts and self.verify_atomic_facts_format(json.dumps(regenerated_facts)):
                        new_validation = self.validator.validate_atomic_facts(regenerated_facts,previous_chunk_context, chunk)

                        
                        # Now log the original + regenerated with new validation
                        track_regeneration_step(
                            self.regeneration_logs,
                            chunk,
                            current_facts,
                            validation_result,
                            regenerated_facts,
                            new_validation
                        )    
                        # Keep better version
                        if new_validation['overall_score'] < validation_result['overall_score']:
                            current_facts = regenerated_facts
                            validation_result = new_validation
                    
                    attempt_count += 1
                
                # Return facts if final hallucination score is acceptable
                if validation_result['overall_score'] <= self.HALLUCINATION_THRESHOLD:
                    return current_facts, True
                else:
                    logging.warning("High hallucination score even after regeneration attempts")
                    return default_template, False
                    
            else:
                logging.warning("Invalid atomic facts format, using default template")
                return default_template, False
                
        except Exception as e:
            logging.error(f"Error in Break_into_atomic_facts: {str(e)}")
            return default_template, False