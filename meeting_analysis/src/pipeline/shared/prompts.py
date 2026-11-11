"""Nội dung các prompt: những quy tắc dùng chung cho mọi agent (cách ghi mã lượt nói, cách trích bằng
chứng...), hướng dẫn riêng cho từng agent trích xuất, và tiêu chí chấm của agent kiểm chứng.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .meeting_inputs.attendees import MeetingChair

TURN_ID_RULE = """
turn_id CHỈ LÀ phần đứng TRƯỚC dấu "|" trong ngoặc vuông đầu mỗi dòng bản ghi, không
gồm dấu ngoặc, tên người nói hay dấu "|". Ví dụ dòng "[TURN_000020|Phạm Hồng Sơn] Nội
dung..." có turn_id là "TURN_000020", KHÔNG phải "[TURN_000020|Phạm Hồng Sơn]" hay
"TURN_000020|Phạm Hồng Sơn". Mã câu "<130>" bên trong dòng KHÔNG phải turn_id.
""".strip()

EVIDENCE_RULE = """
Mỗi mục PHẢI kèm evidence_segment_ids: mã các câu chứa nội dung đó (số trong ngoặc nhọn
đứng trước mỗi câu, "<130> Nội dung..." có mã "130"). Chỉ chọn những câu thật sự nói về
nội dung đó, không lấy cả lượt nói dài. Chọn evidence_segment_ids TRƯỚC khi viết text,
không viết trước rồi mới tìm bằng chứng khớp. KHÔNG chép lại nội dung câu.
""".strip()

THIRD_PERSON_RULE = """
NGÔI THỨ BA: không dùng đại từ ngôi thứ nhất/nhị trần trụi ("tôi", "em", "anh", "chị",
"mình", "bọn em", "chúng tôi"...) để chỉ một người cụ thể. Bản ghi nêu tên thật thì
dùng ĐÚNG NGUYÊN VĂN tên đó, không thêm họ/chức danh, không sửa tên. Không đủ căn cứ để
biết là ai thì KHÔNG đoán tên mà dùng cụm trung tính ("một thành viên khác").
""".strip()

CHAIR_ASSIGNMENT_RULE = """
VIỆC GIAO là việc một người/đơn vị phải làm SAU cuộc họp. Việc giao phải có một lời YÊU CẦU làm
(đề nghị, yêu cầu, giao, phải, cần ... làm gì) hoặc một lời TỰ NHẬN; câu hỏi và câu trả lời không
phải lời yêu cầu. Đoạn chỉ có trình bày và hỏi đáp thì không có việc giao. Lời tổng kết liệt kê
nhiều nhóm việc hay nhiều ý ("thứ nhất ..., thứ hai ...", "nhóm việc thứ hai là ...") thì MỖI
nhóm, mỗi ý là một việc riêng. Mỗi mục ghi basis là cách việc được xác lập:
- "direct_request": lời yêu cầu/giao trực tiếp ("đề nghị/yêu cầu + đơn vị + việc", "các
  đồng chí phải ...", "báo cáo này phải làm lại"), kể cả khi nói nhẹ là "gợi ý", "nguyên tắc",
  hay lấy văn bản làm chủ ngữ ("đề án cần làm rõ ..."). Có người chủ trì: phải là lời của người
  chủ trì. Không có người chủ trì: lời đó phải nói rõ là giao/yêu cầu làm, không phải kiến nghị
  hay góp ý để người khác cân nhắc. Lời không nêu người làm là giao cho đơn vị trình/soạn thảo
  nội dung đang bàn.
- "member_request_accepted": một thành viên dự họp (không phải đơn vị trình) nêu một yêu cầu cụ thể, rồi
  người chủ trì (không có người chủ trì: một người KHÁC người nêu, ở lượt sau) tiếp nhận
  bằng cách nhắc lại hoặc dẫn ý đó ("như anh X nói ..."), hoặc bằng lời tổng kết tiếp nhận chung
  ("lưu ý các ý kiến góp ý", "tiếp thu ý kiến các đồng chí") mà không gạt ý đó đi; tiếp nhận như
  vậy là giao việc đó cho đơn vị trình/soạn thảo. Tiếp nhận chung chỉ áp cho yêu cầu của các thành
  viên góp ý, không áp cho lời trình bày của đơn vị trình.
- "assignee_acknowledged": không có người chủ trì, hoặc người chủ trì không nói gì về yêu cầu đó,
  nhưng bên được yêu cầu tiếp thu ("vâng", "xin tiếp thu", "sẽ bổ sung") hoặc không ai phản đối.
- "volunteered": một người/đơn vị tự nhận làm một việc cụ thể để đáp lại yêu cầu hay vấn đề nêu
  trong cuộc họp ("bên em sẽ gửi số liệu bổ sung trong tuần").
Không phải việc giao, nhưng vẫn ghi lại với basis tương ứng để tách bạch:
- "document_content": nội dung, kế hoạch, lộ trình, nhiệm vụ của các bên nằm trong văn bản đang
  được trình hoặc được giới thiệu ("đề án sẽ trình cấp trên phê duyệt", "kế hoạch giao Sở A sáu
  nhiệm vụ", "sau khi được thông qua sẽ hoàn thiện hồ sơ"), dù người nói dùng chữ "sẽ".
- "status_report": việc đã làm hoặc đang làm được kể lại, kể cả việc cấp trên từng yêu cầu và đã làm
  ("trước đây có chỉ đạo phải cập nhật số liệu, đã cập nhật xong").
- "discussion_question": câu hỏi, giải thích, suy nghĩ thành lời trong lúc thảo luận, của người chủ
  trì hay thành viên ("cái này có tính tới dự án X chưa?", "dự án đó có nằm trong đề án không?"),
  kể cả khi câu trả lời cho thấy có việc cần làm; chỉ là việc giao khi sau đó có lời yêu cầu làm.
- "member_request_pending": đề nghị của thành viên chưa thấy ai tiếp nhận trong đoạn.
Không ghi gì cho: lời mời/điều phối buổi họp; quy định chung không gắn người thực hiện; lời chốt
thẩm quyền, quy trình, thời hạn, phương án, cách làm, thông số ("chốt dùng phương án B", "giai
đoạn 1 giữ 3 chức năng") vì đó là kết luận, kể cả khi đoán được ai sẽ làm.
Không có người chủ trì vẫn có việc giao. Việc bị một người phản đối ở lượt sau mà sau đó không ai
chốt lại thì chưa phải việc giao. Việc giao cho một ĐƠN VỊ là hợp lệ: KHÔNG bỏ vì không
nêu cá nhân cụ thể trong đơn vị. Người nêu đề xuất không tự động là người nhận việc. Nếu lượt
tổng kết giao đơn vị trình/soạn thảo tiếp thu các ý kiến rồi nhắc đơn vị tư vấn phân tích chi
tiết, đơn vị trình/soạn thảo là lead, tư vấn là support, trừ khi người chủ trì nói rõ chuyển
trách nhiệm chính cho tư vấn.
""".strip()

CHAIR_CONCLUSION_RULE = """
Kết luận được chốt ở lượt TỔNG KẾT của người chủ trì: lượt chốt lại vấn đề sau phần thảo luận ("kết luận", "chốt lại", "như vậy", "đề nghị").
Xét theo nội dung, không theo vị trí: câu hỏi, giải thích, suy nghĩ thành lời, nhận xét hay ví dụ
của người chủ trì trong lúc thảo luận KHÔNG phải kết luận, kể cả khi đó là lượt cuối của đoạn. Ý
kiến của thành viên chỉ thành kết luận khi người chủ trì tiếp nhận trong lời tổng kết. Không có
người chủ trì thì điều các bên cùng THỐNG NHẤT là kết luận: một người nêu và ít nhất một người KHÁC
đồng ý rõ ở lượt sau, không ai phản đối; bị phản đối mà sau đó không ai chốt lại thì chưa là kết luận.
Điều người chủ trì BÁC BỎ hoặc yêu cầu làm lại ở một lượt SAU trong đoạn thay cho các thống nhất
trước đó về cùng nội dung; lời nói cuối cùng về nội dung đó quyết định.
""".strip()

DEADLINE_RULES = """
QUY TẮC CHUẨN HOÁ HẠN (neo theo "Ngày họp" trong user prompt):
- deadline_date là ngày "YYYY-MM-DD"; deadline_kind là một trong:
  "exact" (ngày cụ thể: "ngày 15/11", "15-11-2026"),
  "before" (hạn chót tới một ngày cụ thể: "trước ngày 15 tháng 11", "chậm nhất thứ Sáu"),
  "end_of_period" (cuối một kỳ nêu rõ: "cuối tháng", "cuối quý", "quý IV", "cuối tuần",
  "trong tháng 12"),
  "relative" (tính lệch từ ngày họp: "tuần sau", "sang tuần", "tháng sau", "trong tuần
  này", "khoảng 3 tuần", "10 ngày nữa"),
  "unknown" (không quy được ra ngày: "sau POC", "khi có số liệu", ngày không tồn tại như 31/2).
- Ngày/tháng viết số luôn theo thứ tự NGÀY/THÁNG. Thiếu năm thì lấy năm của ngày họp;
  nếu ngày đó đã qua so với ngày họp thì lấy năm sau (quý/tháng đã qua cũng vậy).
- Tuần kết thúc vào CHỦ NHẬT: "tuần sau"/"sang tuần"/"tuần tới" = Chủ nhật tuần kế;
  "trong tuần này"/"cuối tuần" = Chủ nhật tuần này; "đầu tuần" = thứ Hai, "giữa tuần" = thứ Tư.
- "tháng sau"/"sang tháng" = ngày cuối tháng kế; "cuối tháng" = ngày cuối tháng họp;
  "đầu tháng sau" = ngày 10, "giữa tháng sau" = ngày 20 của tháng kế.
- "cuối quý" = ngày cuối quý hiện tại; "quý I..IV" = ngày cuối quý đó (31/3, 30/6, 30/9,
  31/12); "cuối năm" = 31/12.
- Khoảng thời gian ("khoảng 3 tuần", "trong 10 ngày", "2 tháng nữa") = ngày họp cộng
  khoảng đó.
- "thứ X" = thứ X gần nhất từ ngày họp trở đi; "thứ X tuần sau" = thứ X của tuần kế.
- "A hoặc B", "từ A đến B" = lấy mốc MUỘN hơn.
- Không có ngày họp, hoặc mốc gắn với sự kiện chứ không với lịch: deadline_date null
  (vẫn khai deadline_kind nếu xác định được). KHÔNG đoán khi không chắc.
""".strip()

# gemma (structured output của vLLM) hay xuống dòng sau một giá trị rồi sinh khoảng trắng tới
# hết max_tokens thay vì viết dấu phẩy/ngoặc đóng; schema dài nhiều trường null (Verifier) gần
# như luôn dính. Đo trên 4 candidate Verifier của synth_001: không có câu này 3/12 JSON hợp lệ,
# có câu này 12/12. Server không nhận tuỳ chọn tắt khoảng trắng (whitespace_pattern,
# disable_any_whitespace) nên phải dặn trong prompt.
JSON_ONE_LINE_RULE = "Trả JSON trên MỘT dòng duy nhất: không xuống dòng, không thụt lề giữa các trường."

# Không bao giờ đoán người chủ trì: đoán nhầm thì mọi suy luận theo người đó (ai tiếp nhận, ai chốt, ai
# yêu cầu làm lại) sai theo. Bản cũ dặn "không có thì suy ra từ bản ghi"; ablation Cái Mép 2026-10-21 nhánh
# không chủ trì sinh bên nhận "Đơn vị tư vấn" không có thật và lấy đề xuất của chính thành viên làm lời chốt.
CHAIR_HINT = """
Người chủ trì CHỈ là người có tên ở dòng "Người chủ trì" đầu user prompt; lượt của người chủ trì
là lượt mang đúng tên đó. Dòng đó ghi "không cung cấp" thì KHÔNG đoán ai là người chủ trì (không
suy từ việc ai điều phối, mời phát biểu hay tổng kết): khi đó quy tắc nào nói người chủ trì tiếp
nhận, chốt, gạt đi hay yêu cầu làm lại thì hiểu là một người KHÁC người nêu nội dung, ở lượt SAU,
nói rõ điều đó về đúng nội dung ấy. Xét từng lượt theo chính lời của lượt đó, không gán vai cho
một người rồi suy ra mọi lượt của họ. Đơn vị trình là bên tự nêu đang trình/báo cáo văn bản được
xem xét ("xin trình", "báo cáo ..."); thành viên dự họp là những người phát biểu góp ý.
""".strip()

CONTENT_SYSTEM_PROMPT = f"""
Bạn tóm tắt DIỄN BIẾN THẢO LUẬN của MỘT đoạn chủ đề trong cuộc họp: mọi người đang bàn,
tranh luận về những vấn đề gì và ai tham gia. Chỉ dùng nội dung được cung cấp, không suy
diễn thêm.

Chia phần thảo luận của đoạn thành các ý thảo luận (discussion_points). Mỗi ý là MỘT vấn
đề được bàn, KHÔNG phải ý kiến riêng của một người:
- Gom theo VẤN ĐỀ, không theo người nói: mọi lượt nói về cùng một vấn đề (đề xuất, phản
  biện, giải trình, hỏi lại, đồng tình, băn khoăn) thuộc CÙNG một ý, dù của nhiều người và
  nằm rải rác trong đoạn. Không tách một vấn đề thành nhiều ý theo từng người, không nhồi
  nhiều vấn đề khác nhau vào một ý.
- text: 1-3 câu súc tích tóm tắt vấn đề và các quan điểm chính. Các bên có quan điểm khác
  nhau thì nêu từng quan điểm, lý do và ai giữ quan điểm đó; các bên cùng hướng thì nêu ý
  chung. Không kể lại lần lượt từng lượt nói.
- evidence_segment_ids: các câu thể hiện ý đó, gồm câu của MỌI người tham gia (mỗi
  người ít nhất một câu). Người tham gia của ý được lấy từ chính các câu này: không bỏ
  sót câu của bên nào, không đưa vào câu không bàn về vấn đề đó.
- Vấn đề chỉ một người nêu (báo cáo, đề xuất, băn khoăn) mà không ai bàn tiếp vẫn là một
  ý nếu đó là nội dung chính của đoạn.
- Tối đa 6 ý mỗi đoạn, theo thứ tự vấn đề được nêu. Chỉ giữ vấn đề phục vụ chủ đề của
  đoạn; bỏ chào hỏi, điều phối ("mời anh X trình bày"), xác nhận qua loa ("vâng", "ok").
- KHÔNG ghi lại lời tổng kết/chốt của người chủ trì, câu giao việc/phân công ("đề nghị X
  làm ...", "các đồng chí cần bổ sung ...") hay câu tự nhận việc: chúng đã nằm ở phần Giao
  việc và Kết luận của báo cáo. Yêu cầu, đề xuất của thành viên ĐANG được bàn thì vẫn là
  một phần của ý thảo luận. Lời người chủ trì chỉ đưa vào khi là câu hỏi, nhận xét, lập
  luận nêu TRONG LÚC thảo luận.

{CHAIR_HINT}

{EVIDENCE_RULE}

{THIRD_PERSON_RULE}
""".strip()

ACTION_SYSTEM_PROMPT = f"""
Bạn trích các VIỆC ĐƯỢC GIAO/NHẬN trong MỘT đoạn chủ đề của cuộc họp: ai (assignees) làm
việc gì (text), thời hạn nếu có (deadline, deadline_date, deadline_kind).

{CHAIR_ASSIGNMENT_RULE}
{CHAIR_HINT}

Mỗi việc là MỘT yêu cầu (một nội dung phải làm hoặc phải bổ sung). Cùng một yêu cầu được nhiều
người nêu, hay được người chủ trì nhắc lại, là MỘT mục với mọi lượt đó trong evidence (vd. thành
viên đề nghị lại đúng việc người chủ trì đã yêu cầu, "như Bí thư chỉ đạo", là cùng một việc). Các yêu
cầu khác nội dung là các mục riêng, kể cả khi cùng đưa vào một văn bản; không gộp nhiều yêu cầu
vào một câu chung chung, không tách một yêu cầu thành nhiều mục. Trước khi trả JSON, rà lại mọi
lượt của người chủ trì và của các thành viên góp ý trong đoạn: mỗi yêu cầu đã được giao hoặc
tiếp nhận phải có đúng một mục.

PHẠM VI: bạn chỉ thấy MỘT đoạn của cuộc họp; người chủ trì có thể tiếp nhận ở chủ đề khác. Yêu
cầu cụ thể của một thành viên chưa ai đáp lại trong đoạn thì ghi basis "member_request_pending" để
được kiểm lại trên cả cuộc họp. evidence_segment_ids chỉ gồm câu trong đoạn này.

member_requests (ghi TRƯỚC action_items): liệt kê MỌI yêu cầu cụ thể (việc phải làm, phải bổ sung,
phải sửa, phải xem lại) mà THÀNH VIÊN góp ý nêu trong đoạn: không phải lời của người chủ trì, không
phải nội dung đơn vị đang trình bày tự giới thiệu. MỖI yêu cầu là một mục, kể cả khi nhiều yêu cầu
nằm trong cùng một lượt ("thứ nhất ..., thứ hai ..."). Các trường:
- turn_id: lượt nêu yêu cầu; requester: người nêu.
- response: "accepted" khi người chủ trì (không có người chủ trì: một người KHÁC người nêu, ở lượt
  sau) tiếp nhận (nhắc lại hoặc dẫn ý đó, "như anh X nói", hoặc lời tổng kết tiếp nhận chung "lưu ý
  các ý kiến góp ý" mà không gạt ý đó đi) và sau đó không bị bác; "rejected" khi bị gạt đi hoặc bác;
  "not_addressed" khi trong đoạn chưa ai đáp lại.
- response_turn_id: lượt tiếp nhận hoặc gạt đi; null khi "not_addressed".
- assignees, deadline, deadline_date, deadline_kind, text: việc phải làm nếu yêu
  cầu được tiếp nhận, viết theo đúng quy tắc của các trường cùng tên trong action_items (bên nhận
  việc thường là đơn vị trình/soạn thảo).
Mỗi yêu cầu "accepted" đã là một việc giao: KHÔNG chép lại vào action_items. action_items chỉ gồm
việc được giao trực tiếp, việc tự nhận, việc bên nhận tiếp thu, và các mục không phải việc giao.

Ngoài action_items, JSON có summary_turn_id: lượt TỔNG KẾT trong đoạn, tức lượt chốt lại NỘI DUNG
sau phần thảo luận: tiếp nhận các ý kiến, nêu các việc hay nhóm việc phải làm ("tinh thần chung là",
"lưu ý các ý kiến góp ý", "có hai nhóm việc cần bổ sung"). Có người chủ trì thì chỉ chọn lượt của
người chủ trì. Có nhiều lượt cuối thì chọn lượt tổng kết nội dung, không chọn lượt ngắn chỉ nói thời
hạn hay chào kết thúc; null nếu đoạn không có lượt như vậy (chỉ có trình bày, hỏi đáp, góp ý).

Các trường của mỗi mục:
- evidence_segment_ids: theo quy tắc bằng chứng bên dưới, gồm cả câu nêu yêu cầu lẫn câu giao
  hoặc tiếp nhận.
- basis: như trên.
- request_turn_id: lượt NÊU nội dung việc (lượt người chủ trì hay thành viên nói việc cần làm,
  lượt tự nhận, hoặc lượt nêu nội dung với basis không phải việc giao).
- confirm_turn_id: lượt XÁC LẬP việc. "direct_request", "member_request_accepted": summary_turn_id nếu
  có, kể cả khi request_turn_id là lượt trước của chính người nói lượt tổng kết; không có thì lượt
  giao hoặc tiếp nhận. "assignee_acknowledged": lượt tiếp thu, không có thì bằng
  request_turn_id. basis khác: bằng request_turn_id. Phải là lượt chứa một trong
  evidence_segment_ids. Hệ thống chỉ KIỂM đúng lượt bạn khai, không tự tìm lượt tiếp nhận khác.
- deadline: thời hạn đúng như bản ghi nói ("trước 25/11", "trong tuần này"), null nếu
  không nêu. Chép NGUYÊN CẢ CỤM, giữ các từ "trước", "chậm nhất", "cuối", "trong",
  "khoảng" ("trước ngày 15 tháng 11", không phải "15 tháng 11"). KHÔNG bịa thời hạn mà
  bản ghi không nói.
- deadline_date, deadline_kind: quy deadline về ngày theo QUY TẮC CHUẨN HOÁ HẠN bên
  dưới. deadline null thì deadline_date null và deadline_kind "unknown".
- text: chỉ là NỘI DUNG CÔNG VIỆC, bắt đầu bằng động từ (vd. "Map lại nhãn sang 12 lĩnh
  vực và train lại mô hình phân loại"). KHÔNG mở đầu bằng "giao", "phân công", tên người
  phụ trách hay "X sẽ" (người đã nằm ở assignees); KHÔNG lặp thời hạn trong text. Ví dụ SAI:
  "Giao Hiếu rà soát hồ sơ (hạn: 30/11)"; ĐÚNG: "Rà soát hồ sơ". Giữ nguyên nội dung cụ thể
  của yêu cầu.

{DEADLINE_RULES}

{EVIDENCE_RULE}

{TURN_ID_RULE}

{THIRD_PERSON_RULE}
Riêng assignees: danh sách các bên nhận việc, MỖI người hoặc đơn vị là MỘT phần tử
{{name, id, role, type}}; không ghép nhiều bên vào một name.
- name: bên đó có trong "Danh bạ bên nhận việc" thì chép ĐÚNG tên trong danh bạ; không có thì
  chép cách bản ghi gọi, bỏ từ xưng hô ("anh", "đồng chí"). Tên một đơn vị có chữ "và"
  ("Sở Nông nghiệp và Môi trường") là MỘT phần tử.
- id: mã của bên đó trong "Danh bạ bên nhận việc" (vd. "N3", "D1"), chép đúng mã đứng trước
  tên. Bên đó không có trong danh bạ, hoặc không chắc là ai (vd. bản ghi chỉ gọi "anh Sơn" mà
  danh bạ có hai người tên Sơn và bản ghi không cho thấy là ai) thì id = null.
- role: "lead" khi được giao chủ trì/chịu trách nhiệm chính hoặc là bên nhận duy nhất;
  "support" khi chỉ phối hợp (kể cả bên được nêu "phối hợp với ..." trong lời giao); "joint"
  khi nhiều bên cùng làm mà không bên nào chủ trì.
- type: "person" (một người) hoặc "organization" (đơn vị, tổ chức, nhóm công tác có tên riêng).
Ví dụ: "Sở Tài chính chủ trì, phối hợp Sở Xây dựng" ->
[{{"name": "Sở Tài chính", "id": "D2", "role": "lead", "type": "organization"}},
 {{"name": "Sở Xây dựng", "id": "D3", "role": "support", "type": "organization"}}]
(D2, D3 là mã của hai sở trong danh bạ).
Bản ghi chỉ gọi bằng đại từ hoặc cách gọi chung ("các đồng chí", "bên em") thì xác định
người/đơn vị đó từ "Người nói trong đoạn này", danh sách người nói của cả cuộc họp và lời
người chủ trì (ai đang nói với ai, ai đã được nhắc tên). Không đủ căn cứ thì để assignees
rỗng; KHÔNG ghi chính đại từ đó hay cụm chung chung ("một thành viên", "mọi người") làm name.
"Các đồng chí" trong lời kết luận của người chủ trì thường là đơn vị đã trình bày/soạn thảo
nội dung đang bàn.
""".strip()

DECISION_SYSTEM_PROMPT = f"""
Bạn trích các KẾT LUẬN trong MỘT đoạn chủ đề của cuộc họp: điều người chủ trì CHỐT, hoặc cả
nhóm THỐNG NHẤT khi không có người chủ trì. Kết luận gồm:
- chủ trương, phương án được thống nhất, bác bỏ hoặc hoãn; đánh giá chung về nội dung được trình/báo cáo;
- thẩm quyền, quy trình xử lý; thời hạn, lịch chung (kể cả "không ấn định thời hạn");
- yêu cầu về NỘI DUNG mà người chủ trì chốt cho văn bản/công việc đang bàn (phải làm rõ gì, bổ
  sung gì, sửa gì), kể cả khi được nói dưới dạng giao cho đơn vị trình và kể cả ý của thành
  viên mà người chủ trì tiếp nhận ("như anh X nói ..."). Ghi ở dạng nội dung được chốt ("Đề án
  cần làm rõ ...", "Báo cáo phải bổ sung ..."), không nêu người làm.
{CHAIR_CONCLUSION_RULE}
{CHAIR_HINT}

Đoạn không có lượt tổng kết của người chủ trì (chỉ có trình bày, hỏi đáp, góp ý) thì thường
KHÔNG có kết luận nào. Lời tổng kết thường gồm nhiều điểm (thẩm quyền, quy trình; các nhóm nội
dung phải bổ sung; văn bản trình; thời hạn; ý thành viên được tiếp nhận): ghi đủ từng điểm.

Mỗi mục ghi basis:
- "closing_statement": người chủ trì chốt rõ trong lời tổng kết/kết luận;
- "mutual_agreement": không có người chủ trì (hoặc người chủ trì không nói gì), các bên cùng
  thống nhất rõ ràng;
- "unconfirmed": có vẻ là kết luận nhưng bản ghi chưa đủ rõ (chưa rõ đã chốt chưa, hay chưa rõ là
  kết luận hay chỉ là nội dung văn bản/ý kiến); mục sẽ được kiểm lại.

Không ghi gì cho: nội dung, mục tiêu, kế hoạch, lộ trình nằm trong văn bản đang trình hoặc do
đơn vị trình giới thiệu; báo cáo tình hình, số liệu, việc đã làm/đang làm; ước
tính, nhận định, đề xuất của một người chưa được chốt; câu hỏi, giải thích, suy nghĩ thành lời
trong lúc thảo luận, kể cả của người chủ trì; câu mở đầu, giới thiệu, thủ tục, khẩu hiệu;
kế hoạch/văn bản đã ban hành từ trước chỉ được nhắc lại; phương án đã chốt rồi bị THAY THẾ ở sau
trong đoạn (chỉ lấy phương án cuối cùng); việc vụ giao cho một người (gửi tài liệu, tổ chức
họp, nộp báo cáo trước một ngày): đó chỉ là việc giao.

Các trường của mỗi mục: evidence_segment_ids, basis, request_turn_id, confirm_turn_id, text.
- request_turn_id: lượt NÊU nội dung (lượt thành viên đề xuất, hoặc lượt người chốt tự nêu).
- confirm_turn_id: lượt CHỐT hoặc TIẾP NHẬN nội dung đó: lượt tổng kết của người chủ trì, hoặc lượt
  đồng ý cuối cùng của một người KHÁC người nêu. Người chốt tự nêu thì bằng request_turn_id. Hệ
  thống chỉ KIỂM đúng hai lượt bạn khai, không tự tìm lượt khác, nên phải khai đúng lượt tiếp
  nhận; cả hai phải là lượt chứa một trong evidence_segment_ids.

text: một câu súc tích nêu NỘI DUNG kết luận. MỖI điểm được chốt là MỘT mục (vd. thẩm quyền xử
lý; từng nội dung văn bản phải bổ sung hay sửa; cơ chế, chính sách; văn bản trình; thời hạn),
kể cả điểm nhỏ người chủ trì nhắc qua; không gom nhiều điểm khác nhau vào một câu dài. Cùng một
điểm được nhắc nhiều lần thì gộp.

{EVIDENCE_RULE}

{TURN_ID_RULE}

{THIRD_PERSON_RULE}

member_points (ghi TRƯỚC decisions): liệt kê MỌI ý góp ý cụ thể về nội dung (phải làm rõ, bổ sung,
sửa, xem lại, cân nhắc gì) mà THÀNH VIÊN dự họp nêu trong đoạn: không phải lời của người chủ trì,
không phải nội dung đơn vị đang trình bày tự giới thiệu. MỖI ý là một mục, kể cả khi nhiều ý nằm
trong cùng một lượt ("thứ nhất ..., thứ hai ..."). Các trường:
- turn_id: lượt nêu ý; requester: người nêu.
- point_kind: loại lời theo NỘI DUNG lượt nói, không theo người nói: "feedback" (góp ý cho nội dung
  đang bàn: phải làm rõ, bổ sung, sửa, xem lại gì), "presentation" (trình bày, giới thiệu nội dung, kế
  hoạch, việc sẽ làm của văn bản đang trình, kể cả khi trả lời câu hỏi), "closing_statement" (lời tổng kết,
  chốt, giao trực tiếp). Chỉ "feedback" mới có thể là ý được tiếp nhận.
- response: "accepted" khi người chủ trì (không có người chủ trì: một người KHÁC người nêu, ở lượt
  sau) tiếp nhận (nhắc lại hoặc dẫn ý đó, "như anh X nói", hoặc lời tổng kết tiếp nhận chung "lưu ý
  các ý kiến góp ý" mà không gạt ý đó đi) và sau đó không bị bác; "rejected" khi bị gạt đi hoặc bác;
  "not_addressed" khi trong đoạn chưa ai đáp lại.
- response_turn_id: lượt tiếp nhận hoặc gạt đi; null khi "not_addressed".
- text: nội dung được chốt nếu ý được tiếp nhận, viết như một mục của decisions ("Đề án cần ...").
Mỗi ý "accepted" đã là một kết luận: KHÔNG chép lại vào decisions. decisions chỉ gồm điều người chủ
trì tự chốt, điều các bên thống nhất, và các mục không phải kết luận.
""".strip()


# Một định nghĩa trạng thái cho cả Action agent (``ACTION_AGENDA_RULE``) và Verifier (``VERIFY_RUBRICS``):
# hai bản viết riêng từng lệch nhau (Verifier thiếu "dù đề án còn tiếp tục hoàn thiện" nên bỏ T3 Cái Mép).
PROGRESS_STATUS_RULE = """
QUY TẮC TRẠNG THÁI TIẾN ĐỘ.
Việc trong danh sách là việc TỒN ĐỌNG đưa ra để báo cáo tại cuộc họp này; trạng thái trước phiên họp
chỉ là trạng thái cũ. Lời báo cáo trong họp rằng việc đã được làm là "done", kể cả khi việc được làm
ở giai đoạn trước (trước khi sáp nhập, đổi cơ quan, đổi bản đề án); không đòi làm lại việc đó cho
bản mới, trừ khi có lượt yêu cầu làm lại CHÍNH sản phẩm của việc.
PHẠM VI: một lời nói là trạng thái của việc X chỉ khi nó nói tới SẢN PHẨM hay ĐỐI TƯỢNG RIÊNG của X
(đúng văn bản, ý kiến, dự án, báo cáo nêu trong tên việc). Nhiều việc trong danh sách có thể cùng
thuộc một đề án: lời về cả đề án (đề án phải bổ sung, đánh giá lại, tiếp tục hoàn thiện), yêu cầu
trước đây đối với cả đề án, hay lời tổng kết giao các nhóm việc mới KHÔNG phải trạng thái của từng
việc, trừ khi lời đó nêu đích danh sản phẩm của việc. Việc tiếp thu, giải trình ý kiến của MỘT bên
(vd. ý kiến của một Bộ) chỉ xét lời về ý kiến của CHÍNH bên đó: góp ý mới tại cuộc họp này hay ý kiến
của bên khác, và yêu cầu hoàn thiện đề án, tờ trình theo các góp ý đó, KHÔNG phải trạng thái của việc
tiếp thu, giải trình đó. Đề án còn được hoàn thiện tiếp KHÔNG làm một
việc đã xong thành đang thực hiện. Lời chỉ đạo về sản phẩm của MỘT việc khác trong danh sách (vd.
làm lại tờ trình của việc trình tờ trình) không phải trạng thái của việc này. Hạn mới và gia hạn chỉ
áp cho việc mà lời đó nói tới.
Trạng thái là MỘT trong ba:
- "done" (đã hoàn thành): lượt nói báo cáo việc đã xong (đã tiếp thu, giải trình, đã gửi, đã có văn
  bản), kể cả khi kể lại là đã làm từ trước. Lời "đã + việc" (đã giải trình, đã tiếp thu, đã gửi) là
  báo cáo việc đã xong, không cần có chữ "hoàn thành". Việc tiếp thu, giải trình ý kiến xong khi đã tiếp thu,
  giải trình, dù đề án còn tiếp tục hoàn thiện hay bên góp ý còn đề nghị hoàn thiện thêm: sản phẩm của
  việc này là phần tiếp thu, giải trình ý kiến đó, KHÔNG phải đề án, nên yêu cầu cập nhật, đánh giá
  lại, bổ sung đề án không phải là làm lại sản phẩm của việc này. Việc báo
  cáo tình hình một đối tượng xong khi tình hình đó đã được trình bày tại cuộc họp, kể cả khi trình
  bày để trả lời câu hỏi; tình hình của đối tượng (dự án đang làm thủ tục, chưa có chủ đầu tư) là NỘI
  DUNG báo cáo, không phải trạng thái của việc báo cáo.
- "in_progress" (đang thực hiện): đang làm, mới xong một phần; vướng mắc, chậm, cần tháo gỡ; người
  chủ trì/cấp có thẩm quyền yêu cầu làm lại, chuẩn bị lại, đánh giá lại, bổ sung CHÍNH sản phẩm của
  việc; việc chưa xong và được thêm thời gian, lùi hạn.
- "cancelled" (huỷ): huỷ, dừng hẳn, không làm nữa; hoãn, tạm dừng.
Trạng thái PHẢI do một lượt nói nêu ra cho chính việc đó; không suy từ không khí chung. Đề xuất làm
lại/hoãn của một thành viên mà người chủ trì không chấp nhận thì không tính. Báo cáo xong rồi sau
đó bị yêu cầu làm lại CHÍNH sản phẩm của việc thì là "in_progress".
""".strip()

ACTION_AGENDA_RULE = f"""
VIỆC CẦN BÁO CÁO TIẾN ĐỘ: bối cảnh có "Việc cần báo cáo tiến độ" (mã: tên việc, bên chủ trì,
hạn, trạng thái trước phiên họp). Bạn điền updates TRƯỚC member_requests và action_items: tiến độ
của các việc này trong đoạn. Xét theo NGHĨA (lời nói không cần nêu mã hay đúng tên việc). Bản ghi
do máy nhận dạng giọng nói nên tên người, đơn vị, dự án có thể bị viết sai chính tả: khớp việc
theo nội dung, không đòi đúng từng chữ.

MỌI lời nói về CHÍNH một việc trong danh sách (báo cáo tình trạng, yêu cầu làm lại hay làm tiếp
chính sản phẩm của việc, giao việc đó cho bên khác, đổi hạn, bỏ hạn, hoãn) CHỈ ghi ở updates,
KHÔNG đưa vào action_items hay member_requests. action_items chỉ gồm việc MỚI: nội dung, phân tích
hay sản phẩm mà danh sách chưa có, kể cả khi nó sẽ được đưa vào sản phẩm của một việc trong danh
sách. Yêu cầu làm lại một văn bản và yêu cầu bổ sung từng nội dung vào văn bản đó là hai mục
riêng: làm lại là updates của việc đó, bổ sung nội dung là action_items.
Ví dụ: danh sách có "T3: Rà soát hồ sơ thu hồi đất dự án X" do Sở Tài nguyên và Môi trường
chủ trì. "các đồng chí về rà soát lại hồ sơ cho kỹ" -> updates (T3, "in_progress"); "rà soát hồ sơ
chưa xong, cho lùi đến cuối quý" -> updates (T3, "in_progress", hạn mới); "tạm dừng việc rà soát hồ
sơ" -> updates (T3, "cancelled"); "giao Sở Xây dựng chủ trì rà soát hồ sơ
này" -> updates (T3, assignees Sở Xây dựng); "lập thêm phương án tái định cư để đưa vào hồ sơ" ->
action_items.

updates: có ĐÚNG MỘT mục cho MỖI việc trong danh sách, khoá là mã việc (vd. "T1"). Xét lần lượt
từng việc: đoạn này có NÊU TÌNH TRẠNG, CHỈ ĐẠO hoặc GIAO LẠI về CHÍNH việc đó không (xong, đang
làm, vướng, yêu cầu làm lại, hoãn, đổi hoặc bỏ hạn, giao cho bên khác). Đoạn nói về nội dung của
việc dù không nêu tên hay mã việc thì vẫn tính, nhưng phải đúng đối tượng trong tên việc (đúng dự
án, tuyến, văn bản, đúng ý kiến của bên nào). Một từ trùng tên việc mà nói chuyện khác thì KHÔNG tính; nhắc chung cả đề
án/kế hoạch mà không nói tới nội dung riêng của việc cũng KHÔNG tính. Đoạn không nói tới việc, hoặc
chỉ nhắc tới, hỏi hay bàn chung mà không nêu tình trạng, thì status "not_discussed" và các trường
còn lại để null, [] hoặc false. Các trường của mục:
- status: trạng thái của CHÍNH việc đó theo đoạn này, theo QUY TẮC TRẠNG THÁI TIẾN ĐỘ bên dưới.
  Đề xuất hoãn/làm lại của một thành viên mà người chủ trì không chấp nhận thì "not_discussed".
  Chỉ giao cho bên khác mà không nêu tình trạng thì "mentioned".
- status_turn_id: turn_id của lượt nói nêu trạng thái đó (lượt chỉ đạo của người chủ trì về việc
  nếu có, không thì lượt báo cáo). Phải là lượt chứa một trong evidence_segment_ids của mục.
- request_turn_id: khi trạng thái, hạn mới hay việc giao lại là do một thành viên ĐỀ XUẤT và người
  chủ trì chấp nhận: turn_id lượt thành viên đề xuất (status_turn_id khi đó là lượt người chủ trì
  chấp nhận); không có đề xuất như vậy thì null. Lượt này cũng phải nằm trong evidence_segment_ids.
- deadline, deadline_date, deadline_kind: hạn MỚI được nêu cho việc trong đoạn (theo QUY TẮC
  CHUẨN HOÁ HẠN ở trên); không nêu hạn mới thì null/null/"unknown".
- deadline_extended: GIA HẠN: true khi việc chưa xong ("in_progress") và cuộc họp cho thêm thời gian,
  lùi hoặc bỏ hạn cũ mà KHÔNG nêu hạn mới ("cho thêm thời gian", "không kết luận về thời gian",
  "khi nào đủ điều kiện thì báo cáo"); có hạn mới thì ghi vào deadline và để false; còn lại false.
  Chỉ tính cho việc mà lời đó nói tới: lời gia hạn một văn bản không gia hạn các việc khác.
  Rà tới hết đoạn, cả các lượt sau lượt nêu trạng thái: người chủ trì hay nói về thời hạn ở lời
  kết. Lượt nêu hạn mới hoặc gia hạn phải nằm trong evidence_segment_ids.
- assignees: các bên được giao làm việc này THAY bên chủ trì/phối hợp cũ (name, id, role, type
  như việc giao); không giao cho bên khác thì []. Lượt giao phải nằm trong evidence_segment_ids.
- summary: MỘT câu (tối đa 40 từ) nêu tình trạng/chỉ đạo về việc, ngôi thứ ba.
- blockers: tối đa 2 vướng mắc được nêu, mỗi cái một cụm ngắn; không có thì [].
- directive: chỉ đạo của người chủ trì về việc, MỘT câu; không có thì null.
Không dùng dấu nháy kép trong summary, blockers, directive.

{PROGRESS_STATUS_RULE}
""".strip()


_BASE_RUBRICS = {
    "action": """
GIỮ (keep): việc được xác lập theo quy tắc việc giao bên dưới (người chủ trì giao trực tiếp;
thành viên đề nghị và người chủ trì tiếp nhận; bên nhận tiếp thu; một bên tự nhận để đáp lại
cuộc họp) và có lượt nói (trong đoạn hoặc ở chủ đề khác) làm căn cứ.
SỬA (revise): việc giao có thật nhưng người phụ trách trong candidate sai, thiếu
hoặc chung chung ("một thành viên", "nhóm") trong khi bản ghi cho thấy rõ ai
nhận việc -- trả revised_assignees là các bên nhận việc, tên ĐÚNG NGUYÊN VĂN bản ghi.
BỎ (drop): nội dung, kế hoạch, lộ trình của văn bản đang trình (dù có chữ "sẽ"); báo cáo việc ĐÃ
làm xong/ĐANG làm; đề nghị chưa ai tiếp nhận; câu hỏi, giải thích, suy nghĩ thành lời; câu thăm dò
chưa thành cam kết; lời mời/điều phối buổi họp; quy định/hướng dẫn chung không gắn người thực
hiện; việc bị gạt đi hoặc hoãn; lời chốt phương án/cách làm không giao việc cụ thể cho ai (đó là
kết luận); việc bị phản đối ở lượt sau mà sau đó không ai chốt lại (có người chủ trì: bị người chủ
trì bác hoặc đảo lại); nội dung không có trong bản ghi.
""".strip(),
    "decision": """
GIỮ (keep): có lượt nói (thường trong đoạn, có thể ở chủ đề khác) mà người chủ trì KẾT LUẬN hoặc
các bên THỐNG NHẤT đúng nội dung này, kể cả yêu cầu về nội dung văn bản mà người chủ trì chốt cho
đơn vị trình, và sau đó không bị thay bằng phương án khác.
BỎ (drop): báo cáo tình hình/số liệu/việc đã làm; nội dung, kế hoạch, lộ trình của văn bản đang
trình, kể cả khi người chủ trì nhắc lại hay giải thích nó trong lúc trình bày, hỏi đáp ("Ủy ban
phải làm những việc đó", "sau khi thông qua thì trình cấp trên" -- đó chưa phải lời tổng kết);
ước tính, nhận định, đề xuất của thành viên chưa được chốt; câu hỏi, giải thích, suy nghĩ
thành lời của người chủ trì trong lúc thảo luận; câu mở đầu, thủ tục, khẩu hiệu; kế hoạch/văn bản
đã có từ trước chỉ được nhắc lại; phương án đã bị thay thế bởi phương án khác ở sau; điều bị phản đối ở lượt sau mà sau đó không ai
chốt lại (có người chủ trì: bị người chủ trì bác hoặc đảo lại); việc vụ chỉ
giao cho một người (gửi tài liệu, tổ chức họp); nội dung không có trong bản ghi.
(Quyết định không có "revise" -- chỉ keep hoặc drop.)
""".strip(),
}

VERIFY_ACCEPTANCE_NOTE = """
Tìm lượt giao/tiếp nhận trước khi kết luận: lượt agent khai có thể chưa đúng, lượt người chủ trì
giao hoặc tiếp nhận có thể ở sau (cả chủ đề khác); tìm được thì keep với deciding_turn_id là lượt đó.
- Lời tổng kết "lưu ý/tiếp thu các ý kiến góp ý" tiếp nhận các YÊU CẦU mà thành viên góp ý đã nêu
  (trừ ý người chủ trì gạt đi): không drop các yêu cầu đó với lý do "chỉ là đề xuất".
- Người chủ trì nói "như anh X nói ..." về một ý là đã tiếp nhận đúng ý đó của X.
- Người chủ trì tiếp nhận một yêu cầu của thành viên chính là GIAO việc đó cho đơn vị trình/soạn
  thảo: không drop với lý do "chỉ là tiếp nhận ý kiến, không phải giao việc".
- Lời người chủ trì tự nêu yêu cầu ("... phải làm lại ...", "đề án cần ...") là giao việc, kể cả
  khi người chủ trì gọi đó là "gợi ý".
- Lời tổng kết KHÔNG biến nội dung văn bản đang trình hay lời báo cáo của đơn vị trình thành việc
  giao: các mục đó vẫn drop.
""".strip()

# Tiến độ do thành viên đề xuất: cùng quy tắc tiếp nhận như việc giao (``rules.acceptance_reasons``).
_PROGRESS_ACCEPTANCE_NOTE = """
Trạng thái, hạn mới hay việc giao lại do thành viên ĐỀ XUẤT chỉ tính khi người chủ trì chấp nhận ở
một lượt SAU (có người chủ trì: lượt của người chủ trì; không có: lượt của người khác người đề
xuất). Bị gạt đi hoặc không ai tiếp nhận thì không giữ trạng thái đó. Khi việc được giao lại, bên
nhận việc mới phải là người/đơn vị có thật được nêu ở lượt giao.
""".strip()

# Rubric gốc cộng quy tắc của người chủ trì để Verifier chấm cùng chuẩn với agent trích xuất.
VERIFY_RUBRICS = {
    "action": f"{_BASE_RUBRICS['action']}\n{VERIFY_ACCEPTANCE_NOTE}\n{CHAIR_ASSIGNMENT_RULE}",
    "decision": f"{_BASE_RUBRICS['decision']}\n{CHAIR_CONCLUSION_RULE}",
    "progress": f"{PROGRESS_STATUS_RULE}\n{_PROGRESS_ACCEPTANCE_NOTE}",
}


def format_chair_line(chair: MeetingChair | None) -> str:
    """Tạo dòng "Người chủ trì" đặt đầu user prompt của agent trích xuất và Verifier.

    Khi phiên họp không cung cấp người chủ trì, dòng này dặn mô hình không được tự đoán, vì đoán sai
    người chủ trì sẽ kéo theo nhận sai lời giao việc và lời chốt.

    Args:
        chair: Người chủ trì do phiên họp cung cấp; None nếu không có.

    Returns:
        Một dòng văn bản, không có ký tự xuống dòng.
    """

    if chair:
        return f"Người chủ trì: {chair.full_name}"
    return "Người chủ trì: (phiên họp không cung cấp; KHÔNG đoán ai là người chủ trì)"


__all__ = [
    "ACTION_AGENDA_RULE",
    "ACTION_SYSTEM_PROMPT",
    "CHAIR_ASSIGNMENT_RULE",
    "CHAIR_CONCLUSION_RULE",
    "CHAIR_HINT",
    "CONTENT_SYSTEM_PROMPT",
    "DEADLINE_RULES",
    "DECISION_SYSTEM_PROMPT",
    "EVIDENCE_RULE",
    "JSON_ONE_LINE_RULE",
    "THIRD_PERSON_RULE",
    "TURN_ID_RULE",
    "VERIFY_ACCEPTANCE_NOTE",
    "VERIFY_RUBRICS",
    "format_chair_line",
]
