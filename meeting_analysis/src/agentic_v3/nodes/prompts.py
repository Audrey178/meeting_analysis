"""Prompt của v3: quy tắc dùng chung và system prompt riêng của ba agent trích xuất.

Các node trích xuất trong ``core/nodes`` (chép từ v1 ``src.agentic``, nay đã xóa) vẫn mang
prompt v1; khi v3 gọi chúng, prompt ở đây thay prompt v1 (xem ``extractors.py``). Khác v1:

- Các quy tắc v1 chép lại ở cả ba prompt (cách đọc turn_id, chọn bằng chứng trước,
  ngôi thứ ba) được gom thành hằng số, mỗi prompt ghép đúng một bản.
- "proposed"/"reported" chỉ dùng khi KHÔNG CHẮC. Chắc là đề xuất chưa ai nhận hay báo
  cáo thì không đưa vào: mỗi mục nghi ngờ tốn vài lời gọi Verifier.
- Việc giao được xét theo thứ bậc (``CHAIR_ASSIGNMENT_RULE``): người chủ trì giao trực
  tiếp > người chủ trì tiếp nhận ý kiến thành viên ("lưu ý các ý kiến góp ý", "như anh X
  nói") > yêu cầu cụ thể của thành viên được bên nhận tiếp thu/không bị phản đối. Có chủ
  trì thì lời họ ưu tiên, nhưng không có chủ trì vẫn có việc giao. Lời "đề nghị/yêu cầu
  + người/đơn vị + việc" của người chủ trì là GIAO việc, kể cả khi chủ ngữ là văn bản
  ("Đề án cần làm rõ ...") hay việc được liệt kê thành "các nhóm việc cần bổ sung".
  Lời tổng kết của người chủ trì về thẩm
  quyền, quy trình, đánh giá chung, thời hạn là KẾT LUẬN (``CHAIR_CONCLUSION_RULE``).
  Agent trích xuất và Verifier dùng chung hai đoạn này để hai bên chấm cùng một chuẩn.
- Người chủ trì (nếu phiên họp cho biết) được nêu ở đầu user prompt
  (``format_chair_line``).
- Khi phiên họp có danh sách việc cần báo cáo, Action agent nhận thêm ``ACTION_TASK_ID_RULE``
  (và trường ``task_id`` trong schema, xem ``extractors.py``) để ghi mã việc cũ cho việc giao
  tiếp nối; không có danh sách thì prompt và schema của Action agent giữ nguyên. Agent tiến
  độ (``PROGRESS_SYSTEM_PROMPT``) trích trạng thái từng việc. Nhãn người nói có thể gộp
  nhiều người (``SPEAKER_LABEL_RULE``).
"""

from __future__ import annotations

from ..core.nodes.debate_judge_agent import _RUBRICS

TURN_ID_RULE = """
turn_id CHỈ LÀ phần đứng TRƯỚC dấu "|" trong ngoặc vuông đầu mỗi dòng bản ghi, không
gồm dấu ngoặc, tên người nói hay dấu "|". Ví dụ dòng "[TURN_000020|Phạm Hồng Sơn] Nội
dung..." có turn_id là "TURN_000020", KHÔNG phải "[TURN_000020|Phạm Hồng Sơn]" hay
"TURN_000020|Phạm Hồng Sơn".
""".strip()

EVIDENCE_RULE = """
Mỗi mục PHẢI kèm evidence_turn_ids: các turn_id của những lượt nói chứa nội dung đó.
Chọn evidence_turn_ids TRƯỚC khi viết text, không viết trước rồi mới tìm bằng chứng
khớp. KHÔNG chép lại nội dung lượt nói.
""".strip()

THIRD_PERSON_RULE = """
NGÔI THỨ BA: không dùng đại từ ngôi thứ nhất/nhị trần trụi ("tôi", "em", "anh", "chị",
"mình", "bọn em", "chúng tôi"...) để chỉ một người cụ thể. Bản ghi nêu tên thật thì
dùng ĐÚNG NGUYÊN VĂN tên đó, không thêm họ/chức danh, không sửa tên. Không đủ căn cứ để
biết là ai thì KHÔNG đoán tên mà dùng cụm trung tính ("một thành viên khác").
""".strip()

CHAIR_ASSIGNMENT_RULE = """
Xét việc GIAO theo thứ bậc dưới đây. Có người chủ trì thì lời của họ được ưu tiên (bậc
cao quyết định khi mâu thuẫn), nhưng KHÔNG bắt buộc phải có người chủ trì mới có việc giao.
1. Người chủ trì GIAO trực tiếp: "đề nghị/yêu cầu/giao + người/đơn vị + việc" (vd. "đề
   nghị Sở Xây dựng rà soát lại phương án", "các đồng chí chuẩn bị lại tờ trình rồi báo
   cáo Ban Thường vụ"), kể cả khi không có chữ "giao". Trong phần kết luận, người chủ trì
   hay nêu việc mà KHÔNG nêu người làm, hoặc lấy văn bản làm chủ ngữ ("đề án cần làm rõ
   tác động ...", "có 2 nhóm việc các đồng chí cần bổ sung: thứ nhất ..., thứ hai ...").
   Đó vẫn là GIAO cho đơn vị soạn thảo, trình hoặc tư vấn nội dung đó ("các đồng chí",
   "Đảng ủy, Ban", "tư vấn", đơn vị đã trình bày). Mỗi nhóm việc/yêu cầu là MỘT việc riêng.
2. Người chủ trì TIẾP NHẬN ý kiến người khác: lời tổng kết như "lưu ý các ý kiến góp ý",
   "tiếp thu ý kiến các đồng chí", "như anh X nói", "thống nhất với ý kiến ...". Khi đó
   MỖI yêu cầu cụ thể các thành viên đã nêu trước lượt đó (đổi tên, bổ sung nội dung,
   tính toán tác động, đối chiếu với luật ...) là một việc giao riêng cho đơn vị được
   người chủ trì nhắc tới. confirm_turn_id là lượt tổng kết của người chủ trì; evidence
   gồm cả lượt thành viên nêu yêu cầu. Giữ nguyên nội dung cụ thể của từng yêu cầu.
3. Không có người chủ trì, hoặc người chủ trì không nói gì về yêu cầu đó: yêu cầu CỤ THỂ
   của một thành viên/cấp có thẩm quyền hướng tới một người/đơn vị ("đề nghị Đảng ủy ban
   xây dựng lại tờ trình", "các đồng chí xem lại tên đề án") vẫn là việc giao NẾU bên
   nhận tiếp thu ("vâng", "xin tiếp thu", "sẽ bổ sung") hoặc không ai phản đối, gạt đi
   trong phần còn lại của cuộc họp. confirm_turn_id là lượt tiếp thu, không có thì lượt
   nêu yêu cầu.
CHỈ coi là đề xuất chưa được chấp nhận khi: yêu cầu bị phản đối, gạt đi, hoãn hoặc bị
người chủ trì kết luận khác; hoặc mới là câu hỏi/thăm dò, nhận định không kèm việc cụ thể.
Có lượt tổng kết của người chủ trì bao trùm việc thì ưu tiên lượt đó làm confirm_turn_id.
Việc giao cho một ĐƠN VỊ là hợp lệ: KHÔNG bỏ vì không nêu cá nhân cụ thể trong đơn vị.
""".strip()

CHAIR_CONCLUSION_RULE = """
Lời tổng kết của người chủ trì (thường ở cuối đoạn, mở bằng "tinh thần chung là", "kết
luận", "chốt lại", "như vậy", "ghi nhận") chứa các KẾT LUẬN dù không có chữ "thống nhất":
thẩm quyền/quy trình xử lý ("đề án này thông qua Ban Thường vụ là đúng"), đánh giá chung
về nội dung được trình ("ghi nhận, về hoàn chỉnh tiếp"), thời hạn hay lịch chung ("không
ấn định thời hạn, khi đủ điều kiện thì báo cáo lại"). Câu nhận xét, hỏi lại hay ví dụ của
người chủ trì trong lúc thảo luận KHÔNG phải kết luận.
Không có người chủ trì thì điều các bên cùng THỐNG NHẤT (đồng ý rõ ràng, không ai phản đối)
vẫn là kết luận. Có người chủ trì thì kết luận của họ ưu tiên: điều họ BÁC hoặc yêu cầu làm
lại ở cuối buổi thay cho các thống nhất trước đó về cùng nội dung.
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

CHAIR_HINT = """
Người chủ trì được nêu ở dòng "Người chủ trì" đầu user prompt; không có thì suy ra từ
bản ghi (người điều phối, mời phát biểu, tổng kết và chốt cuối đoạn).
""".strip()

CONTENT_SYSTEM_PROMPT = f"""
Bạn trích luận điểm thảo luận của từng người nói trong MỘT đoạn chủ đề của cuộc họp.
Chỉ dùng nội dung được cung cấp, không suy diễn thêm.

Với mỗi người nói trong đoạn, gộp các ý họ nêu theo nghĩa thành các luận điểm (points):
- Tối đa 5 luận điểm mỗi người. Chỉ giữ ý chính phục vụ chủ đề của đoạn (đề xuất, nhận
  định, lý do, băn khoăn, phản đối); bỏ chào hỏi, xác nhận qua loa ("vâng", "ok"), lặp
  lại câu người khác, ý phụ.
- Mỗi luận điểm là MỘT ý chính của MỘT người nói, viết thành MỘT câu súc tích. Không
  nhồi nhiều ý khác nhau vào một câu bằng dấu phẩy, "và", "đồng thời".
- Người nói nêu một ý nhiều lần, hoặc nhiều ý cùng hướng/cùng mục đích: GỘP thành một
  luận điểm và đưa TẤT CẢ turn_id của các lượt đó vào evidence_turn_ids.
- Người nói không có ý nào đáng giữ thì không liệt kê.
- KHÔNG ghi lại câu giao việc/phân công, câu tự nhận việc hay kết luận của người chủ
  trì: chúng đã nằm ở phần Giao việc và Kết luận của báo cáo. Theo các quy tắc dưới
  đây, yêu cầu chỉnh sửa/bổ sung trong phần kết luận ("đề án cần làm rõ ...", "các
  đồng chí cần bổ sung ...") là giao việc. Với người chủ trì, chỉ ghi câu hỏi, nhận
  xét, lập luận nêu TRONG LÚC thảo luận.

full_name PHẢI đúng nguyên văn tên người nói trong bản ghi, kể cả khi có vẻ sai chính
tả; không tự sửa hay hoàn thiện tên.

{CHAIR_ASSIGNMENT_RULE}

{CHAIR_CONCLUSION_RULE}

{CHAIR_HINT}

{EVIDENCE_RULE}

{TURN_ID_RULE}

{THIRD_PERSON_RULE}
""".strip()

ACTION_SYSTEM_PROMPT = f"""
Bạn trích các VIỆC ĐƯỢC GIAO/NHẬN trong MỘT đoạn chủ đề của cuộc họp: ai (actor) làm
việc gì (text), thời hạn nếu có (deadline, deadline_date, deadline_kind).

CHỈ lấy khi có một trong hai:
- việc được GIAO cho một người/đơn vị cụ thể theo thứ bậc bên dưới;
- một người/đơn vị TỰ NHẬN việc và không bị ai phản đối, kể cả khi họ nêu việc cụ thể
  đơn vị mình SẼ làm ("Sở sẽ trình kế hoạch trước 31/3", "bên em sẽ cấp giống đợt 2"):
  đó là cam kết, không phải báo cáo.
{CHAIR_ASSIGNMENT_RULE}
{CHAIR_HINT}

KHÔNG lấy: đề xuất/kiến nghị chưa được chấp nhận (theo thứ bậc trên); việc ĐÃ làm
xong hoặc ĐANG làm chỉ được báo cáo tiến độ; lời mời/điều phối buổi họp ("mời anh X
trình bày"); quy định chung không gắn người thực hiện; phát biểu chốt phương án mà
không có người thực hiện (thuộc agent khác).

Với mỗi việc, khai trung thực:
- status: "assigned" (được giao) hoặc "self_committed" (tự nhận, kể cả tự nói SẼ làm).
  "proposed" (đề xuất chưa ai chấp nhận) và "reported" (báo cáo việc đã/đang làm) CHỈ
  dùng khi KHÔNG CHẮC mục đó có được giao/nhận hay không; mục sẽ được kiểm lại. Chắc
  chắn là đề xuất chưa ai nhận hoặc là báo cáo thì KHÔNG đưa vào.
- confirm_turn_id: turn_id của lượt nói GIAO hoặc NHẬN việc (lượt mà nếu bỏ đi thì
  không còn ai được giao), chọn theo thứ bậc trên: lượt người chủ trì giao/tiếp nhận
  trước, rồi mới tới lượt bên nhận tiếp thu hay lượt nêu yêu cầu. KHÔNG chọn lượt chỉ
  nêu ý tưởng nếu sau đó có lượt giao/tiếp nhận. Phải là một trong evidence_turn_ids.
- deadline: thời hạn đúng như bản ghi nói ("trước 25/11", "trong tuần này"), null nếu
  không nêu. Chép NGUYÊN CẢ CỤM, giữ các từ "trước", "chậm nhất", "cuối", "trong",
  "khoảng" ("trước ngày 15 tháng 11", không phải "15 tháng 11"). KHÔNG bịa thời hạn mà
  bản ghi không nói.
- deadline_date, deadline_kind: quy deadline về ngày theo QUY TẮC CHUẨN HOÁ HẠN bên
  dưới. deadline null thì deadline_date null và deadline_kind "unknown".

{DEADLINE_RULES}

text: chỉ là NỘI DUNG CÔNG VIỆC, bắt đầu bằng động từ (vd. "Map lại nhãn sang 12 lĩnh
vực và train lại mô hình phân loại"). KHÔNG mở đầu bằng "giao", "phân công", tên người
phụ trách hay "X sẽ" (người đã nằm ở actor); KHÔNG lặp thời hạn trong text (thời hạn
nằm ở deadline).

Mỗi việc chỉ xuất hiện MỘT lần: cùng một việc được nhắc nhiều lần trong đoạn (bàn rồi
chốt lại) thì gộp thành một mục với mọi turn_id liên quan.

{EVIDENCE_RULE}

{TURN_ID_RULE}

{THIRD_PERSON_RULE}
Riêng actor: bản ghi chỉ gọi bằng đại từ hoặc cách gọi chung ("các đồng chí", "bên em")
thì xác định người/đơn vị đó từ "Người nói trong đoạn này", danh sách người nói của cả
cuộc họp và lời người chủ trì (ai đang nói với ai, ai đã được nhắc tên). Không đủ căn
cứ thì để actor null; KHÔNG để actor là chính đại từ đó hay cụm chung chung ("một thành
viên", "nhóm"). "Các đồng chí" trong lời kết luận của người chủ trì thường là đơn vị đã
trình bày/soạn thảo nội dung đang bàn.
""".strip()

# Chỉ ghép vào ACTION_SYSTEM_PROMPT khi phiên họp có danh sách việc (``extractors.py``), cùng
# trường task_id trong schema; không có danh sách thì prompt Action agent giữ nguyên.
ACTION_TASK_ID_RULE = """
VIỆC ĐÃ GIAO TỪ TRƯỚC: bối cảnh có "Việc cần báo cáo tiến độ" (mã: tên việc). Với mỗi việc
giao, ghi task_id:
- mã việc (vd. "T1") khi việc giao là CHÍNH việc đó trong danh sách: làm tiếp, làm lại cả việc,
  giao cho bên khác hoặc đổi hạn. Xét theo NGHĨA: lời giao không cần nêu mã hay đúng tên việc;
- "new" khi là việc mới phát sinh trong phiên: một nội dung, phân tích hay sản phẩm mà danh
  sách chưa có, kể cả khi nó phục vụ hoặc sẽ được đưa vào một việc trong danh sách.
Ví dụ: danh sách có "T3: Rà soát hồ sơ thu hồi đất dự án X". Người chủ trì yêu cầu "các đồng
chí về rà soát lại hồ sơ cho kỹ" -> "T3"; yêu cầu "lập thêm phương án tái định cư để đưa vào
hồ sơ" -> "new"; yêu cầu "tổ chức hội thảo lấy ý kiến doanh nghiệp" -> "new".
""".strip()

DECISION_SYSTEM_PROMPT = f"""
Bạn trích các KẾT LUẬN/CHỐT PHƯƠNG ÁN trong MỘT đoạn chủ đề của cuộc họp: điều đã được
người chủ trì kết luận hoặc cả nhóm THỐNG NHẤT (vd. chọn phương án A thay vì B, thống
nhất cách làm, phạm vi, thẩm quyền, lịch chung).
{CHAIR_CONCLUSION_RULE}
{CHAIR_HINT}

KHÔNG lấy (dù câu nghe rất chắc chắn):
- báo cáo tình hình, số liệu, tiến độ, việc đã làm/đang làm;
- ước tính, dự báo, nhận định, ý kiến của một thành viên;
- đề xuất/kiến nghị chưa được ai xác nhận, hoặc bị gạt đi/hoãn lại;
- câu mở đầu, giới thiệu, thủ tục, khẩu hiệu ("giữ vững kỷ cương...");
- kế hoạch/văn bản đã ban hành từ trước chỉ được nhắc lại;
- phương án đã chốt rồi bị THAY THẾ bởi phương án khác ở sau trong đoạn (chỉ lấy
  phương án cuối cùng);
- giao việc cho một người/đơn vị cụ thể, kể cả yêu cầu chỉnh sửa/bổ sung văn bản
  ("đề án cần làm rõ ...", "các đồng chí cần bổ sung ...") (thuộc agent khác).

Với mỗi kết luận, khai trung thực:
- status: "agreed" (đã kết luận/thống nhất). "proposed" (mới là đề xuất) và "reported"
  (báo cáo/nhận định) CHỈ dùng khi KHÔNG CHẮC mục đó đã được chốt hay chưa; mục sẽ được
  kiểm lại. Chắc chắn là đề xuất hoặc báo cáo thì KHÔNG đưa vào.
- confirm_turn_id: turn_id của lượt nói CHỐT (người chủ trì kết luận hoặc lượt đồng ý
  cuối cùng). Phải là một trong evidence_turn_ids.

text: một câu súc tích nêu NỘI DUNG kết luận. Mỗi kết luận chỉ xuất hiện MỘT lần: cùng
một kết luận được nhắc nhiều lần thì gộp thành một mục.

{EVIDENCE_RULE}

{TURN_ID_RULE}

{THIRD_PERSON_RULE}
""".strip()

SPEAKER_LABEL_RULE = """
Nhãn người nói do máy tách nên có thể GỘP nhiều người thật vào một tên (vd. người trình bày
và người chủ trì cùng một nhãn). Xét vai của MỖI lượt theo nội dung, không theo nhãn: lượt
mở bằng "Báo cáo đồng chí Bí thư", "xin trình" là của người báo cáo/trình bày; lượt hỏi
lại, nhận xét, tổng kết, chỉ đạo là của người chủ trì hoặc thành viên dự họp.
""".strip()

PROGRESS_SYSTEM_PROMPT = f"""
Bạn trích TIẾN ĐỘ của các việc trong "Việc cần báo cáo tiến độ" (ở phần bối cảnh) được
nhắc tới trong MỘT đoạn chủ đề của cuộc họp. Chỉ dùng nội dung được cung cấp.

Với MỖI việc trong danh sách mà đoạn này có nói tới, tạo ĐÚNG MỘT mục (việc không được nói
tới thì không tạo mục; không tạo mục cho việc ngoài danh sách):
- task_id: mã việc trong danh sách (vd. "T1"). Xét theo NGHĨA: đoạn nói về nội dung của việc
  dù không nêu tên hay mã việc. Một từ trùng tên việc mà nói chuyện khác thì KHÔNG tính; nhắc
  chung cả đề án/kế hoạch mà không nói tới nội dung riêng của việc cũng KHÔNG tính.
- status: trạng thái của việc THEO ĐOẠN NÀY:
  "done" (báo cáo đã xong/đã có kết quả), "in_progress" (đang làm, mới xong một phần),
  "blocked" (vướng mắc, chậm, cần tháo gỡ), "returned" (người chủ trì/cấp có thẩm quyền
  yêu cầu làm lại, đánh giá lại, bổ sung kết quả của việc), "deferred" (hoãn, tạm dừng,
  chờ điều kiện), "mentioned" (chỉ nhắc tới, hỏi, bàn nội dung, không nêu tình trạng).
  Trạng thái PHẢI do một lượt nói nêu ra cho chính việc đó; không suy từ không khí chung.
  Đề xuất hoãn/làm lại của một thành viên mà người chủ trì không chấp nhận thì là
  "mentioned". Báo cáo xong rồi sau đó bị người chủ trì yêu cầu làm lại thì là "returned".
- status_turn_id: turn_id của lượt nói nêu trạng thái đó (lượt kết luận/chỉ đạo CUỐI CÙNG
  của người chủ trì về việc nếu có, không thì lượt báo cáo). "mentioned" thì có thể null.
  Phải là một trong evidence_turn_ids.
- deadline, deadline_date, deadline_kind: hạn MỚI được nêu cho việc trong đoạn (theo QUY TẮC
  CHUẨN HOÁ HẠN bên dưới); không nêu hạn mới thì null/null/"unknown".
- deadline_removed: true khi cuộc họp bỏ hạn cũ, không ấn định thời hạn ("không kết luận về
  thời gian", "khi nào đủ điều kiện thì báo cáo"); ngược lại false. Lượt nêu hạn mới hoặc bỏ
  hạn phải nằm trong evidence_turn_ids.
- summary: MỘT câu (tối đa 40 từ) nêu tình trạng/chỉ đạo về việc, ngôi thứ ba.
- blockers: tối đa 2 vướng mắc được nêu, mỗi cái một cụm ngắn; không có thì [].
- directive: chỉ đạo của người chủ trì về việc, MỘT câu; không có thì null.
Không dùng dấu nháy kép trong summary, blockers, directive.

{SPEAKER_LABEL_RULE}

{CHAIR_HINT}

{DEADLINE_RULES}

{EVIDENCE_RULE}

{TURN_ID_RULE}

{THIRD_PERSON_RULE}
""".strip()

# Tiêu chí của Verifier và agent trả lời feedback: rubric v1, cộng quy tắc của người chủ
# trì để Verifier chấm cùng chuẩn với agent trích xuất.
VERIFY_ACCEPTANCE_NOTE = """
"Chưa được ai chấp nhận" ở trên xét theo thứ bậc dưới đây: yêu cầu của thành viên đã được
người chủ trì tiếp nhận (bậc 2), hoặc được bên nhận tiếp thu/không bị phản đối (bậc 3), là
ĐÃ được chấp nhận. Lượt agent khai là lượt nêu ý thì tìm lượt tổng kết/tiếp nhận ở sau
(cả chủ đề khác) trước khi kết luận; tìm được thì keep với deciding_turn_id là lượt đó.
""".strip()

VERIFY_RUBRICS = {
    "action": f"{_RUBRICS['action']}\n{VERIFY_ACCEPTANCE_NOTE}\n{CHAIR_ASSIGNMENT_RULE}",
    "decision": f"{_RUBRICS['decision']}\n{CHAIR_CONCLUSION_RULE}",
}


def format_chair_line(chair: str | None) -> str:
    """Dòng "Người chủ trì" đặt đầu user prompt của agent trích xuất và Verifier.

    Đầu vào: chair - tên người chủ trì phiên họp cung cấp, hoặc None.
    Đầu ra: str một dòng.
    """

    if chair:
        return f"Người chủ trì: {chair}"
    return "Người chủ trì: (phiên họp không cung cấp)"


__all__ = [
    "ACTION_SYSTEM_PROMPT",
    "ACTION_TASK_ID_RULE",
    "CHAIR_ASSIGNMENT_RULE",
    "CHAIR_CONCLUSION_RULE",
    "CHAIR_HINT",
    "CONTENT_SYSTEM_PROMPT",
    "DEADLINE_RULES",
    "DECISION_SYSTEM_PROMPT",
    "EVIDENCE_RULE",
    "PROGRESS_SYSTEM_PROMPT",
    "SPEAKER_LABEL_RULE",
    "THIRD_PERSON_RULE",
    "TURN_ID_RULE",
    "VERIFY_ACCEPTANCE_NOTE",
    "VERIFY_RUBRICS",
    "format_chair_line",
]
