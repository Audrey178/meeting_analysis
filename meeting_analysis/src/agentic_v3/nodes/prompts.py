"""Prompt của v3: quy tắc dùng chung và system prompt riêng của ba agent trích xuất.

v3 không sửa prompt của v1 (``src.agentic``, pipeline v1 vẫn dùng). Khi v3 gọi lại các
node trích xuất của v1, prompt ở đây thay prompt v1 (xem ``extractors.py``). Khác v1:

- Các quy tắc v1 chép lại ở cả ba prompt (cách đọc turn_id, chọn bằng chứng trước,
  ngôi thứ ba) được gom thành hằng số, mỗi prompt ghép đúng một bản.
- "proposed"/"reported" chỉ dùng khi KHÔNG CHẮC. Chắc là đề xuất chưa ai nhận hay báo
  cáo thì không đưa vào: mỗi mục nghi ngờ tốn vài lời gọi Verifier.
- Lời "đề nghị/yêu cầu + người/đơn vị + việc" của người chủ trì là GIAO việc
  (``CHAIR_ASSIGNMENT_RULE``). Action agent và Verifier dùng chung câu này để hai bên
  chấm cùng một chuẩn, nhờ vậy các việc đó được gắn "assigned" ngay, không phải qua
  Verifier.
- Người chủ trì (nếu phiên họp cho biết) được nêu ở đầu user prompt
  (``format_chair_line``).
"""

from __future__ import annotations

from ...agentic.nodes.debate_judge_agent import _RUBRICS

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
Người chủ trì hoặc cấp có thẩm quyền nói "đề nghị/yêu cầu/giao + người/đơn vị + việc"
(vd. "đề nghị Sở Xây dựng rà soát lại phương án", "các đồng chí chuẩn bị lại tờ trình
rồi báo cáo Ban Thường vụ") là GIAO việc cho người/đơn vị đó, kể cả khi không có chữ
"giao". Cùng câu đó do một thành viên khác nói thì chỉ là đề xuất.
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
- KHÔNG ghi lại câu giao việc/phân công hay câu tự nhận việc: chúng đã nằm ở phần Giao
  việc của báo cáo. Với người chủ trì, chỉ ghi lập luận/định hướng (vì sao chọn phương
  án, lưu ý gì), không liệt kê lại từng việc đã giao.

full_name PHẢI đúng nguyên văn tên người nói trong bản ghi, kể cả khi có vẻ sai chính
tả; không tự sửa hay hoàn thiện tên.

{CHAIR_HINT}

{EVIDENCE_RULE}

{TURN_ID_RULE}

{THIRD_PERSON_RULE}
""".strip()

ACTION_SYSTEM_PROMPT = f"""
Bạn trích các VIỆC ĐƯỢC GIAO/NHẬN trong MỘT đoạn chủ đề của cuộc họp: ai (actor) làm
việc gì (text), thời hạn nếu có (deadline, deadline_date, deadline_kind).

CHỈ lấy khi có một trong hai:
- người chủ trì/cấp có thẩm quyền GIAO việc cho một người/đơn vị cụ thể;
- một người/đơn vị TỰ NHẬN việc và không bị ai phản đối, kể cả khi họ nêu việc cụ thể
  đơn vị mình SẼ làm ("Sở sẽ trình kế hoạch trước 31/3", "bên em sẽ cấp giống đợt 2"):
  đó là cam kết, không phải báo cáo.
{CHAIR_ASSIGNMENT_RULE}
{CHAIR_HINT}

KHÔNG lấy: đề xuất/kiến nghị/yêu cầu của thành viên mà chưa ai chấp nhận; việc ĐÃ làm
xong hoặc ĐANG làm chỉ được báo cáo tiến độ; lời mời/điều phối buổi họp ("mời anh X
trình bày"); quy định chung không gắn người thực hiện; phát biểu chốt phương án mà
không có người thực hiện (thuộc agent khác).

Với mỗi việc, khai trung thực:
- status: "assigned" (được giao) hoặc "self_committed" (tự nhận, kể cả tự nói SẼ làm).
  "proposed" (đề xuất chưa ai chấp nhận) và "reported" (báo cáo việc đã/đang làm) CHỈ
  dùng khi KHÔNG CHẮC mục đó có được giao/nhận hay không; mục sẽ được kiểm lại. Chắc
  chắn là đề xuất chưa ai nhận hoặc là báo cáo thì KHÔNG đưa vào.
- confirm_turn_id: turn_id của lượt nói GIAO hoặc NHẬN việc (lượt mà nếu bỏ đi thì
  không còn ai được giao). Phải là một trong evidence_turn_ids.
- deadline: thời hạn đúng như bản ghi nói ("trước 25/11", "trong tuần này"), null nếu
  không nêu. Chép NGUYÊN CẢ CỤM, giữ các từ "trước", "chậm nhất", "cuối", "trong",
  "khoảng" ("trước ngày 15 tháng 11", không phải "15 tháng 11"). KHÔNG bịa thời hạn mà
  bản ghi không nói.
- deadline_date, deadline_kind: quy deadline về ngày theo QUY TẮC CHUẨN HOÁ HẠN bên
  dưới. deadline null thì deadline_date null và deadline_kind "unknown".

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
viên", "nhóm").
""".strip()

DECISION_SYSTEM_PROMPT = f"""
Bạn trích các KẾT LUẬN/CHỐT PHƯƠNG ÁN trong MỘT đoạn chủ đề của cuộc họp: một lựa chọn
đã được người chủ trì kết luận hoặc cả nhóm THỐNG NHẤT (vd. chọn phương án A thay vì B,
thống nhất cách làm, phạm vi, lịch chung).
{CHAIR_HINT}

KHÔNG lấy (dù câu nghe rất chắc chắn):
- báo cáo tình hình, số liệu, tiến độ, việc đã làm/đang làm;
- ước tính, dự báo, nhận định, ý kiến của một thành viên;
- đề xuất/kiến nghị chưa được ai xác nhận, hoặc bị gạt đi/hoãn lại;
- câu mở đầu, giới thiệu, thủ tục, khẩu hiệu ("giữ vững kỷ cương...");
- kế hoạch/văn bản đã ban hành từ trước chỉ được nhắc lại;
- phương án đã chốt rồi bị THAY THẾ bởi phương án khác ở sau trong đoạn (chỉ lấy
  phương án cuối cùng);
- giao việc cho một người/đơn vị cụ thể (thuộc agent khác).

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

# Tiêu chí của Verifier và agent trả lời feedback: rubric v1, cộng câu chủ trì giao việc
# để Verifier chấm việc giao cùng chuẩn với Action agent.
VERIFY_RUBRICS = {
    "action": f"{_RUBRICS['action']}\n{CHAIR_ASSIGNMENT_RULE}",
    "decision": _RUBRICS["decision"],
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
    "CHAIR_ASSIGNMENT_RULE",
    "CHAIR_HINT",
    "CONTENT_SYSTEM_PROMPT",
    "DECISION_SYSTEM_PROMPT",
    "EVIDENCE_RULE",
    "THIRD_PERSON_RULE",
    "TURN_ID_RULE",
    "VERIFY_RUBRICS",
    "format_chair_line",
]
