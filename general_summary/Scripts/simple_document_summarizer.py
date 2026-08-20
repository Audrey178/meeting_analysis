import logging
import os
import json
import hashlib
import pandas as pd
from typing import Dict, List, Tuple, Any
from docx_ingest import parse_transcript_docx, build_labeled_transcript_text
from model_handler import ModelHandler
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

MARKDOWN_FEW_SHOT = """
| | |
|---|---|
| **ĐOÀN ĐBQH VÀ HĐND**<br>**THÀNH PHỐ HỒ CHÍ MINH**<br>**VĂN PHÒNG ĐOÀN ĐẠI BIỂU QUỐC HỘI**<br>**VÀ HỘI ĐỒNG NHÂN DÂN THÀNH PHỐ**<br>Số:      /TB-VP | **CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM**<br>**Độc lập – Tự do – Hạnh phúc**<br>*TP. Hồ Chí Minh, ngày     tháng 7 năm 2026* |

# THÔNG BÁO

**Ý kiến kết luận của đồng chí Võ Văn Minh, Chủ tịch HĐND Thành phố tại cuộc họp giao ban Thường trực HĐND với lãnh đạo các Ban HĐND và Văn phòng tuần thứ 30**

Ngày 28 tháng 7 năm 2026, tại trụ sở HĐND Thành phố, đồng chí Võ Văn Minh, Ủy viên Trung ương Đảng, Phó Bí thư Thành ủy, Chủ tịch HĐND Thành phố đã chủ trì cuộc họp giao ban của Thường trực HĐND với lãnh đạo các Ban HĐND và Văn phòng Đoàn ĐBQH và HĐND Thành phố tuần thứ 30.

## I. THÀNH PHẦN THAM DỰ

**1. Chủ trì:** Đồng chí Võ Văn Minh, Ủy viên Trung ương Đảng, Phó Bí thư Thành ủy, Chủ tịch HĐND Thành phố.

**2. Tham dự:**

- Thường trực HĐND Thành phố: có mặt 09/09;
- Lãnh đạo các Ban của HĐND Thành phố;
- Lãnh đạo Văn phòng Đoàn ĐBQH và HĐND Thành phố;
- Lãnh đạo, chuyên viên các Phòng thuộc Văn phòng Đoàn ĐBQH và HĐND Thành phố.

## II. NỘI DUNG

Sau khi nghe lãnh đạo Văn phòng và các Ban của HĐND Thành phố báo cáo tình hình hoạt động tuần thứ 29, một số nhiệm vụ trọng tâm tuần thứ 30 và đề xuất, kiến nghị; ý kiến trao đổi, thảo luận của các đồng chí Thường trực HĐND Thành phố, lãnh đạo các Ban và Văn phòng, thay mặt Thường trực HĐND Thành phố, đồng chí Võ Văn Minh, Ủy viên Trung ương Đảng, Phó Bí thư Thành ủy, Chủ tịch HĐND Thành phố kết luận, chỉ đạo các nội dung trọng tâm cần tập trung thực hiện như sau:

### 1. Về công tác tổ chức bộ máy

Cơ bản thống nhất với báo cáo, đề xuất của Trưởng Ban Pháp chế về cơ cấu tổ chức của HĐND Thành phố sau khi Luật Phát triển đô thị có hiệu lực thi hành, theo hướng thành lập không quá 05 Ban của HĐND Thành phố, mỗi Ban có không quá 04 Phó trưởng Ban và 02 Ủy viên chuyên trách.

### 2. Về tổ chức các đoàn ra của Thường trực HĐND Thành phố

Văn phòng nghiên cứu, phối hợp Sở Ngoại vụ tham mưu theo hướng thực chất, hiệu quả với thành phần và nội dung làm việc phù hợp, đúng quy định.

### 3. Về công tác chuẩn bị triển khai Luật Phát triển đô thị

Đề nghị các Ban HĐND Thành phố theo lĩnh vực phụ trách tiếp tục chủ động tham mưu Thường trực thực hiện và theo dõi, đôn đốc các Sở, ngành có liên quan về tiến độ chuẩn bị các dự thảo Nghị quyết triển khai thực hiện Luật Phát triển đô thị đảm bảo tính kịp thời và yêu cầu chất lượng.

### 4. Giao Ban Pháp chế

- Chủ trì, phối hợp các Ban HĐND tham mưu chuẩn bị nội dung làm việc giữa Chủ tịch HĐND với Chủ tịch UBND Thành phố và các Sở, ngành về triển khai Luật Phát triển đô thị và xem xét, cho ý kiến xử lý các dự án đầu tư tồn đọng, vướng mắc kéo dài trên địa bàn Thành phố.
- Tiếp tục chủ trì, phối hợp các Ban HĐND hoàn thiện phương án cơ cấu tổ chức các Ban của HĐND Thành phố và HĐND cấp xã theo Luật Phát triển đô thị.
- Khẩn trương hoàn thành việc rà soát các Nghị quyết quy phạm pháp luật do HĐND Thành phố ban hành; phối hợp các Ban và Sở Tư pháp hoàn thiện danh mục nghị quyết cụ thể hóa Luật Phát triển đô thị.

### 5. Giao Ban Kinh tế - Ngân sách

- Tiếp tục tập trung giám sát chuyên đề "công tác sắp xếp, bố trí, xử lý tài sản công (cơ sở nhà, đất, trụ sở làm việc) khi thực hiện mô hình chính quyền địa phương hai cấp trên địa bàn Thành phố Hồ Chí Minh", báo cáo Thường trực HĐND theo kế hoạch.
- Phối hợp Ban Văn hóa - Xã hội tham mưu Thường trực HĐND đề nghị UBND Thành phố sớm thống nhất chủ trương về nguyên tắc xây dựng mức chi, đối tượng thụ hưởng đối với các chính sách an sinh xã hội trước khi xây dựng nghị quyết, bảo đảm khả năng cân đối ngân sách.
- Chủ động phối hợp Ban Nghiên cứu phát triển Thành phố đặt hàng, phản biện các đề tài lớn (kinh tế ngầm, đô thị đại học...); nghiên cứu chuyên đề về nguồn thu từ đất (khu vực TOD, đấu giá quỹ đất...) báo cáo Thường trực HĐND Thành phố.
- Khẩn trương hoàn thành công tác giám sát việc quản lý nhà nước đối với hoạt động khai thác khoáng sản làm vật liệu xây dựng trên địa bàn Thành phố; trên cơ sở kết quả giám sát, tham mưu Thường trực HĐND Thành phố tổ chức làm việc với UBND Thành phố về công tác quản lý hoạt động khai thác khoáng sản trên địa bàn Thành phố.

### 6. Giao Ban Đô thị

- Chủ động trao đổi, có ý kiến với Sở, ngành đề nghị sớm tham mưu UBND Thành phố phân cấp, phân quyền sử dụng vốn kiến thiết thị chính để UBND cấp xã chủ động trong thực hiện nhiệm vụ.
- Phối hợp Sở Quy hoạch - Kiến trúc và các đơn vị có liên quan đẩy nhanh tiến độ lập Quy hoạch tổng thể Thành phố Hồ Chí Minh thời kỳ 2025 – 2050, tầm nhìn 100 năm; nghiên cứu tổ chức hội thảo (lần 2) lấy ý kiến chuyên gia, nhà khoa học đối với Đồ án.
- Chủ trì, phối hợp Văn phòng tham mưu Chủ tịch HĐND Thành phố chuẩn bị nội dung làm việc với Chủ tịch UBND Thành phố theo lịch đã bố trí 16 giờ ngày 30/7/2026 và tổ chức khảo sát tình hình thực hiện Đề án di dời nhà trên và ven sông, kênh, rạch trên địa bàn sáng ngày 31/7/2026.

### 7. Giao Ban Văn hóa - Xã hội

- Tiếp tục theo dõi công tác chuẩn bị năm học mới, công tác tuyển sinh đầu cấp và cung ứng sách giáo khoa; chuẩn bị và tổ chức chu đáo chương trình "Dân hỏi - Chính quyền trả lời" định kỳ tháng 8/2026.
- Phối hợp Sở Y tế nghiên cứu, tham mưu Nghị quyết quy định chính sách hỗ trợ nhân viên y tế thực hiện chế độ luân phiên có thời hạn đến cơ sở khám bệnh, chữa bệnh cấp cơ bản và cấp ban đầu trên địa bàn Thành phố.
- Quán triệt tinh thần tiết kiệm chi thường xuyên để tập trung nguồn lực cho đầu tư phát triển, khi thẩm tra các chính sách an sinh xã hội có mức chi vượt trội, cần cân nhắc kỹ khả năng cân đối ngân sách, tính nhạy cảm của chính sách và thực hiện phản biện ngay từ khâu đề xuất, xây dựng dự thảo.
- Phối hợp Ban Kinh tế - Ngân sách khẩn trương làm việc với Sở Tài chính, Sở Xây dựng tháo gỡ dứt điểm vướng mắc về sử dụng vốn sự nghiệp trong sửa chữa trường lớp chuẩn bị cho năm học mới.

### 8. Giao Văn phòng Đoàn ĐBQH và HĐND Thành phố

- Khẩn trương hoàn thiện và triển khai áp dụng Khung kiến trúc dữ liệu, khung quản trị, quản lý và khai thác dữ liệu của Đoàn đại biểu Quốc hội và Hội đồng nhân dân Thành phố. Phối hợp các Ban xây dựng chi tiết các trường dữ liệu, phương án cấu hình và khai thác, lưu trữ tài liệu, dữ liệu; thực hiện số hóa quy trình xử lý công việc từ cấp chuyên viên, lấy kết quả làm cơ sở đánh giá chỉ số hoàn thành công việc (KPI).
- Nghiên cứu, đề xuất mua sắm phương tiện thay thế các xe đã hết hạn sử dụng.

---

Trên đây là ý kiến kết luận của đồng chí Võ Văn Minh, Chủ tịch HĐND Thành phố tại cuộc họp giao ban Thường trực HĐND với lãnh đạo các Ban HĐND và Văn phòng tuần thứ 30. Văn phòng Đoàn ĐBQH và HĐND Thành phố thông báo đến các tổ chức, cá nhân liên quan biết, thực hiện và báo cáo kết quả, tiến độ công việc tại cuộc họp giao ban thường kỳ tiếp theo./.

| | |
|---|---|
| ***Nơi nhận:***<br>- Thường trực HĐND TP;<br>- Lãnh đạo các Ban HĐND TP;<br>- Lãnh đạo Văn phòng;<br>- Các phòng thuộc VP;<br>- Lưu: VT, (P.CTHĐND – M.Hùng). | **CHÁNH VĂN PHÒNG**<br><br><br>**Võ Anh Tuấn** |
"""

class SimpleDocumentSummarizer:
    """
    A simple document summarizer that uses a single LLM call to generate
    general purpose summaries of text documents.
    """
    
    def __init__(self, client, model="gpt-4o", log_base_path="./logs"):
        self.client = client
        self.model = model
        self.log_base_path = log_base_path
        
    def generate_document_id(self, document: str) -> str:
        """Generate a unique document ID based on document content."""
        return hashlib.md5(document.encode()).hexdigest()
            
    def generate_summary(self, document: str, word_limit: int = 200) -> str:
        """
        Generate a general-purpose document summary in a single LLM call.
        
        Args:
            document: Document text to summarize
            word_limit: Maximum word count for the summary (default: 200)
            
        Returns:
            Document summary
        """
        # Create system prompt for general-purpose summarization
        
        system_prompt_v2 = """
        Bạn là chuyên viên tổng hợp của Văn phòng cơ quan hành chính/cơ quan Đảng tại Việt Nam, có nhiệm vụ soạn thảo văn bản Thông báo ý kiến kết luận của người chủ trì tại cuộc họp.

Đầu vào của bạn gồm nhiều nguồn:

Bản gỡ băng ghi âm cuộc họp (transcript, có thể có nhãn người nói, có lỗi nhận dạng tiếng nói).
Văn bản mẫu định dạng đầu ra.

Nhiệm vụ: chắt lọc ý kiến kết luận, chỉ đạo của người chủ trì và kết cấu lại thành văn bản hành chính hoàn chỉnh, đúng thể thức, đúng văn phong công vụ.

Nguyên tắc bắt buộc

A. Về nguồn thông tin

Chỉ viết những nội dung có căn cứ trong đầu vào. Không suy diễn, không bổ sung số liệu, tên riêng, mốc thời gian không có trong nguồn.
Ưu tiên ý kiến của người chủ trì khi kết luận. Ý kiến thảo luận của các thành viên khác chỉ đưa vào khi người chủ trì tiếp thu, chốt lại hoặc giao nhiệm vụ.
Khi transcript và tài liệu mâu thuẫn về số liệu, tên văn bản, số hiệu, lấy theo tài liệu (bản gỡ băng thường sai chính tả số liệu và tên riêng).
Được phép bổ sung nội dung từ tài liệu trình (nếu có) (ví dụ: ý kiến thẩm định chưa được nêu miệng nhưng thuộc phạm vi kết luận), nhưng phải bảo đảm đúng tinh thần chỉ đạo tại cuộc họp.

B. Về thông tin thiếu

Nếu thiếu thông tin thể thức (số văn bản, ngày ban hành, ngày họp, danh sách thành phần tham dự), để trống bằng khoảng trắng đúng như văn bản mẫu, không bịa.
Cuối phần trả lời, liệt kê riêng mục "Nội dung cần kiểm tra, bổ sung" nêu rõ các chỗ để trống và các chi tiết chưa xác minh được (tên riêng, tên dự án, chức danh nghe không rõ trong ghi âm).

C. Về văn phong

Văn phong hành chính công vụ: khách quan, ngắn gọn, dùng cấu trúc mệnh lệnh — chỉ đạo ("Đề nghị...", "Giao...", "Rà soát...", "Bổ sung, làm rõ...", "Cân nhắc...").
Loại bỏ hoàn toàn khẩu ngữ, từ đệm, câu hỏi qua lại, ví von trong ghi âm; chuyển thành mệnh đề chỉ đạo.
Dùng đúng tên đầy đủ của cơ quan, chức danh, số hiệu văn bản ở lần nhắc đầu tiên; các lần sau có thể viết tắt sau khi đã chú thích (gọi tắt là ...).
Không dùng ngôi thứ nhất, không dùng "chúng tôi/chúng ta".

D. Về cấu trúc nội dung

Nhóm các ý chỉ đạo rời rạc trong ghi âm thành các đầu mục theo chủ đề, đánh số 1, 2, 3...
Mỗi đầu mục có tiêu đề dạng "Về ..." hoặc "Giao [đơn vị]".
Sắp xếp theo trình tự: (i) đánh giá chung/thẩm quyền → (ii) các yêu cầu về nội dung chuyên môn → (iii) cơ chế, nguồn lực → (iv) tiến độ → (v) phân công theo dõi, đôn đốc.
Mỗi ý chỉ đạo phải trả lời được: ai làm — làm gì — làm đến đâu/khi nào.

E. Về thể thức

Cơ quan Đảng: dòng tiêu đề bên phải là ĐẢNG CỘNG SẢN VIỆT NAM, số hiệu dạng -TB/VPTU.
Cơ quan nhà nước: CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM / Độc lập – Tự do – Hạnh phúc, số hiệu dạng /TB-VP.
Kết thúc phần nội dung bằng đoạn "Trên đây là ý kiến kết luận của đồng chí ... Văn phòng ... thông báo đến ... biết, thực hiện ... /."
        """
        
        system_prompt = """
        NGÔN NGỮ: Phải trả lời bằng tiếng Việt.

        You are an expert summarization agent tasked with creating clear, concise document summaries.
        Your goal is to extract the most important information from the document and present it in a coherent summary.

        CRITICAL CONSTRAINTS:
        - Summary MUST be between 150-200 words
        - Use ONLY provided facts from the document
        - NO hallucination or inference beyond what's explicitly stated
        - Focus on the most important information and key points
        - Present as cohesive paragraphs
        - DO NOT use bullet points, numbered lists, or section headers in your summary

        OUTPUT FORMAT:
        - The summary must be in paragraph format only
        - Use well-structured paragraphs that flow naturally
        - No headers, bullet points, or other structural elements
        - Present as a cohesive narrative that covers key points

        SUMMARY CONSIDERATIONS:
        - Identify and prioritize main ideas and key supporting points
        - Maintain the original meaning and intent of the document
        - Preserve critical details while omitting unnecessary ones
        - Ensure logical flow between ideas
        - Use clear, concise language
        - Stay within word limit
        """
        
        # Create user prompt with document
        
        user_prompt_v2 = f"""
        Soạn Thông báo ý kiến kết luận cuộc họp từ các nguồn sau.

<ghi_am_cuoc_hop>
{document}
</ghi_am_cuoc_hop>

<tai_lieu_lien_quan>
</tai_lieu_lien_quan>

<yeu_cau_dinh_dang>
Xuất ra Markdown theo đúng cấu trúc của ví dụ mẫu bên dưới:
- Khối thể thức đầu văn bản dạng bảng 2 cột.
- Tiêu đề "# THÔNG BÁO" + dòng in đậm mô tả nội dung kết luận.
- "## I. THÀNH PHẦN THAM DỰ" gồm mục Chủ trì và Tham dự (gạch đầu dòng).
- "## II. NỘI DUNG" mở đầu bằng đoạn dẫn "Sau khi nghe ... kết luận, chỉ đạo ... như sau:", tiếp theo là các mục "### 1. Về ...".
- Đoạn kết "Trên đây là ý kiến kết luận..."
- Khối Nơi nhận – Chức danh người ký dạng bảng 2 cột.
Sau văn bản, thêm mục "## Nội dung cần kiểm tra, bổ sung".
</yeu_cau_dinh_dang>

Ví dụ về đầu ra: " {MARKDOWN_FEW_SHOT}
        """
        
        user_prompt = f"""
        Generate a {word_limit}-word summary of this document:

        Document Text:
        {document}
        
        Remember:
        - Focus on the most important information and key points
        - Stay within {word_limit} words
        - Only use provided information
        - Format as cohesive paragraphs that flow naturally
        - DO NOT use bullet points, headers, or numbered lists
        - Present as a smooth narrative
        """
        
        try:
            message = ModelHandler.build_message(system_prompt_v2, user_prompt_v2)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "general",
                category="Document Summary",
                log_base_path=self.log_base_path,
                max_tokens=4000
            )

            # Return the summarized response
            return response

        except Exception as e:
            logging.error(f"Error generating summary: {str(e)}")
            return f"Failed to generate summary: {str(e)}"
    
    def process_document(self, document: str, word_limit: int = 200) -> str:
        """
        Process a document to generate a summary.
        
        Args:
            document: Document text
            word_limit: Maximum word count for the summary
            
        Returns:
            Document summary
        """
        # Generate summary
        summary = self.generate_summary(document, word_limit)
        logging.info("Generated document summary")
        
        return summary

    def process_all_meetings(self, input_file_path: str, output_file_path: str) -> pd.DataFrame:
        """
        Process multiple meetings from either a CSV or PKL file and save
        results incrementally. The input file is assumed to have columns:
          - 'Meeting'
          - 'Gold_Summary'
        
        Args:
            input_file_path: Path to CSV or PKL file
            output_file_path: Where to save the CSV of results
        
        Returns:
            DataFrame of processed results
        """
        # Create result directory if it doesn't exist
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        
        # Check if output file already exists to append to it
        all_results = []
        if os.path.exists(output_file_path):
            try:
                existing_results = pd.read_csv(output_file_path)
                all_results = existing_results.to_dict('records')
                logging.info(f"Loaded {len(all_results)} existing results from {output_file_path}")
            except Exception as e:
                logging.warning(f"Could not load existing results, starting fresh: {e}")
        
                # Load the meetings data
        df = pd.read_csv(input_file_path)
        logging.info(f"total meetings =  {len(df)}")
        # Process each document/meeting
        for i, row in df.iterrows():
            # Generate meeting ID
            meeting_id = self.generate_document_id(row['transcript'])
            
            # Check if this meeting has already been processed
            if any(r['meeting_id'] == meeting_id for r in all_results):
                logging.info(f"Meeting {i+1} already processed. Skipping.")
                continue
            
            logging.info(f"Processing meeting {i+1} of {len(df)}")
            
            try:
                # Generate the summary
                raw_summary = self.process_document(row['transcript'])
                
                # Store results
                result = {
                    'meeting_id': meeting_id,
                    'meeting_index': i,
                    'transcript': row['transcript'],
                    'Gold_summary' : row['summary'],
                    'generated_summary': raw_summary,
                }
                
                all_results.append(result)
                logging.info(f"Successfully processed meeting {i+1}")
                
                # Save results after each meeting is processed
                current_results_df = pd.DataFrame(all_results)
                current_results_df.to_csv(output_file_path, index=False)
                logging.info(f"Incremental results saved to {output_file_path} after processing meeting {i+1}")
                
            except Exception as e:
                logging.error(f"Error processing meeting {i+1}: {str(e)}")
                continue
        
        # Final save of all results
        if all_results:
            final_results_df = pd.DataFrame(all_results)
            logging.info("All results processed successfully.")
            return final_results_df
        else:
            logging.warning("No results were generated.")
            return pd.DataFrame()


def _load_turns(input_path: str):
    """Load {meeting, turns, docs, entities} from either a .docx transcript or a pre-processed JSON."""
    if input_path.lower().endswith(".docx"):
        return parse_transcript_docx(input_path)

    with open(input_path, 'r', encoding='utf-8') as f:
        return json.load(f)


if __name__ == "__main__":
    API_KEY = os.getenv('OPENAI_API_KEY')
    BASE_URL = os.getenv('OPENAI_BASE_URL')  # e.g. vLLM endpoint; unset = default OpenAI API
    MODEL_NAME = os.getenv('MODEL_NAME', 'gpt-4o')
    # Example usage
    CLIENT = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    transcript_json = _load_turns('Vietnamese_datasets/processed/GHI_AM_CAI_MEP_THI_VAI.meetingrecord.json')
    transcript_text = build_labeled_transcript_text(transcript_json)
    summarizer = SimpleDocumentSummarizer(CLIENT, MODEL_NAME)
    summary = summarizer.generate_summary(transcript_text)
    print(summary)