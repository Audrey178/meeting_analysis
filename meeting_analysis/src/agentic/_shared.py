"""Các hàm dùng chung cho nhiều node trong graph agent phía sau (downstream).

Ba node LLM theo từng đoạn chủ đề (Content/Action/Decision) đều dựng prompt
từ các lượt nói của đoạn theo cùng một cách, và đều phải lọc các turn_id
được trích dẫn theo cùng một luật. Vì vậy logic đó nằm ở đây một chỗ, tránh
việc các node tự lệch nhau theo thời gian.

Nhóm hàm trong file:
    - Kiểm tra bằng chứng (trích dẫn): ``validate_evidence_with_quotes``,
      ``validate_evidence_by_turn_ids``.
    - Evidence-check CLEAR/UNCERTAIN (kiến trúc M5): ``check_action_evidence``,
      ``check_decision_evidence``.
    - Làm sạch output: ``strip_assignment_prefix``, ``is_assignment_point``,
      ``merge_duplicate_assignments``, ``merge_duplicate_decisions``.
    - Xác định người nói: ``list_distinct_speaker_names``,
      ``match_claimed_name_to_real_speaker``, ``make_speaker_initials``.
    - Xử lý người phụ trách (actor): ``make_actor_grouping_key``,
      ``is_bare_personal_pronoun``.
    - Ngữ cảnh giữa các chủ đề: ``collect_names_and_assignments_of_topic``,
      ``format_previous_context``.
    - Dựng prompt / chia lô: ``format_turns_as_transcript``,
      ``split_into_ranges_within_budget``, ``get_turns_of_segment``.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import replace

from ..utils.contracts import SpeakerTurn, TopicSegment
from .schemas import ActionItemCandidate, DecisionCandidate, EvidenceFlag, SpeakerSection
from .turn_act import COMMIT_CLEAR_MIN, COMMIT_REJECT_MAX, TurnActJudge

logger = logging.getLogger(__name__)

# Các từ xưng hô đứng đầu tên, bị bỏ khi so khớp người phụ trách ("anh Sơn" -> "sơn").
_HONORIFIC_PREFIXES = ("anh", "chị", "em", "bạn", "cô", "chú", "bác", "ông", "bà")

# Đại từ ngôi thứ nhất/nhị đứng một mình: không phải tên thật nên không được
# coi là người phụ trách trong văn bản báo cáo.
_FIRST_OR_SECOND_PERSON_PRONOUNS = frozenset(
    {
        "em", "anh", "chị", "tôi", "mình", "ta",
        "bọn em", "bọn anh", "bọn chị", "bọn mình", "bọn tôi",
        "chúng em", "chúng anh", "chúng tôi", "chúng mình", "chúng ta",
        "các em", "các anh", "các chị",
    }
)

# Cụm trung tính mà ACTION_SYSTEM_PROMPT dặn model dùng TRONG TEXT khi không đủ căn cứ
# xác định actor thật ("một thành viên", "nhóm phụ trách") -- nhưng model có thể nhét
# nhầm đúng cụm này vào field actor thay vì để actor=null. Không định danh được MỘT
# người/nhóm cụ thể nào, nên không được coi là actor hợp lệ (đã xác nhận qua đo trên dữ
# liệu thật: 5/15 verified_assignments của một file có actor thuộc nhóm này mà vẫn lọt
# CLEAR vì check_action_evidence trước đây chỉ bắt actor is None).
_NON_IDENTIFYING_ACTOR_PHRASES = frozenset(
    {
        "nhóm", "cả nhóm", "nhóm phụ trách",
        "một thành viên", "một thành viên khác",
        "team", "mọi người", "các bên liên quan",
    }
)


def _collapse_whitespace(text: str) -> str:
    """Gộp mọi chuỗi khoảng trắng/xuống dòng liên tiếp thành đúng một dấu cách.

    Đầu vào: text (str) - chuỗi bất kỳ.
    Đầu ra: str - chuỗi đã gộp khoảng trắng và bỏ khoảng trắng hai đầu.
    """

    return " ".join(text.split())


def _extract_bare_turn_id(raw: str) -> str:
    """Lấy turn_id "trần" ra khỏi giá trị mà model trả về, kể cả khi model chép cả cụm ngoặc.

    Vì sao cần: prompt hiển thị mỗi dòng bản ghi dạng ``[TURN_000020|Phạm Hồng Sơn] ...``.
    Model nhỏ tự host đôi khi chép nguyên cả ``"[TURN_000020|Phạm Hồng Sơn]"``
    thay vì ``"TURN_000020"``. Nếu không sửa, chuỗi này không khớp turn_id thật
    nên luận điểm bị mất trích dẫn một cách âm thầm.

    Đầu vào: raw (str) - giá trị turn_id do model trả về.
    Đầu ra: str - turn_id trần. Id đã đúng dạng (``"TURN_000020"``) được giữ nguyên.
    """

    text = raw.strip().lstrip("[").rstrip("]")
    return text.split("|", 1)[0].strip()


def split_dict_entries(value: object) -> tuple[list[dict], int]:
    """Lấy các phần tử là dict từ một giá trị mà model được yêu cầu trả về dạng danh sách.

    Schema chỉ yêu cầu chứ không ép được kiểu, nên model có thể trả ``null``, một chuỗi,
    hoặc danh sách lẫn phần tử không phải dict. Hàm này chuẩn hóa để người gọi lặp
    an toàn, không bị ``TypeError``/``AttributeError``.

    Đầu vào: value - giá trị model trả về cho một trường danh sách.

    Đầu ra: tuple ``(entries, invalid_count)``:
        - ``entries``: các phần tử là dict, giữ thứ tự.
        - ``invalid_count``: số phần tử bị bỏ vì sai kiểu. ``None`` (không có gì) tính 0;
          giá trị khác không phải danh sách tính 1.
    """

    if value is None:
        return [], 0
    if not isinstance(value, list):
        return [], 1
    entries = [entry for entry in value if isinstance(entry, dict)]
    return entries, len(value) - len(entries)


def read_stripped_text(value: object) -> str:
    """Đọc một trường văn bản do model trả về, đã bỏ khoảng trắng hai đầu.

    Đầu vào: value - giá trị model trả về.
    Đầu ra: chuỗi đã strip nếu ``value`` là ``str``; ngược lại chuỗi rỗng (None, số,
        danh sách... đều coi như không có nội dung, thay vì bị ép thành chuỗi vô nghĩa
        như ``"123"`` hay ``"['a']"``).
    """

    return value.strip() if isinstance(value, str) else ""


def read_list_or_empty(value: object) -> list:
    """Đọc một trường danh sách do model trả về; sai kiểu hoặc thiếu thì coi là danh sách rỗng.

    Dùng cho ``evidence_turn_ids``: một giá trị không phải danh sách (``null``, chuỗi...)
    nghĩa là luận điểm không có bằng chứng kiểm chứng được, nên sẽ bị loại ở bước sau.

    Đầu vào: value - giá trị model trả về.
    Đầu ra: chính ``value`` nếu là ``list``; ngược lại ``[]``.
    """

    return value if isinstance(value, list) else []


def validate_evidence_with_quotes(
    turns: tuple[SpeakerTurn, ...], claimed_evidence: list[dict]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Lọc bằng chứng do model nêu (gồm turn_id + câu trích) về những gì kiểm chứng được.

    Chức năng:
        - Chỉ giữ mục có ``turn_id`` là lượt nói thật của ĐOẠN này. turn_id bịa
          hoặc thuộc đoạn khác bị loại, để không làm tăng sai số "N trích dẫn".
        - Với câu trích: chỉ tin nếu nó là chuỗi con thật (sau khi gộp khoảng
          trắng) của ``text_exact`` của lượt nói. Ngược lại dùng nguyên văn cả
          lượt nói. Cách này an toàn và vẫn truy vết được, tránh nhận nhầm câu
          model đã diễn đạt lại.

    Đầu vào:
        turns: các lượt nói của đoạn chủ đề hiện tại.
        claimed_evidence: danh sách dict ``{"turn_id": ..., "quote": ...}`` do model trả về.

    Đầu ra:
        Tuple ``(evidence_ids, quotes)``, hai tuple cùng độ dài và cùng thứ tự.
    """

    known = {turn.turn_id: turn.text_exact for turn in turns}
    evidence_ids: list[str] = []
    quotes: list[str] = []
    for entry in claimed_evidence:
        turn_id = _extract_bare_turn_id(str(entry.get("turn_id") or ""))
        if turn_id not in known:
            continue
        turn_text = known[turn_id]
        claimed_quote = (entry.get("quote") or "").strip()
        quote = (
            claimed_quote
            if claimed_quote and _collapse_whitespace(claimed_quote) in _collapse_whitespace(turn_text)
            else turn_text
        )
        evidence_ids.append(turn_id)
        quotes.append(quote)
    return tuple(evidence_ids), tuple(quotes)


def read_confirm_turn_id(turns: tuple[SpeakerTurn, ...], value: object) -> str | None:
    """Đọc ``confirm_turn_id`` do model trả về: chỉ nhận nếu là lượt nói thật của đoạn.

    Đầu vào: turns - các lượt nói của đoạn; value - giá trị model trả về.
    Đầu ra: turn_id trần hợp lệ, hoặc None (bịa, thuộc đoạn khác, sai kiểu).
    """

    if not isinstance(value, str):
        return None
    turn_id = _extract_bare_turn_id(value)
    return turn_id if any(turn.turn_id == turn_id for turn in turns) else None


def validate_evidence_by_turn_ids(
    turns: tuple[SpeakerTurn, ...], claimed_turn_ids: list
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Lọc bằng chứng cho agent chỉ trích dẫn bằng turn_id (model không tự viết câu trích).

    Chức năng: giữ các turn_id là lượt nói thật của đoạn này (bỏ trùng, giữ thứ
    tự xuất hiện) và tự điền câu trích bằng nguyên văn lượt nói đó theo luật.
    Cách này rẻ và an toàn hơn việc bắt model chép lại câu, vì chép lại tốn
    token đầu ra mà kết quả vẫn không đáng tin nếu không phải chuỗi con chính xác.

    Đầu vào:
        turns: các lượt nói của đoạn chủ đề hiện tại.
        claimed_turn_ids: danh sách turn_id do model trả về (có thể sai dạng).

    Đầu ra:
        Tuple ``(evidence_ids, quotes)``, hai tuple cùng độ dài và cùng thứ tự.
    """

    known = {turn.turn_id: turn.text_exact for turn in turns}
    evidence_ids: list[str] = []
    quotes: list[str] = []
    for raw in claimed_turn_ids:
        turn_id = _extract_bare_turn_id(str(raw or ""))
        if turn_id not in known or turn_id in evidence_ids:
            continue
        evidence_ids.append(turn_id)
        quotes.append(known[turn_id])
    return tuple(evidence_ids), tuple(quotes)


# Từ ngữ cho thấy một phát biểu mới là Ý KIẾN/ĐỀ XUẤT, CHƯA phải quyết định
# đã chốt. Dùng cho CẢ ``text`` do agent viết lẫn lượt nói chốt nguyên văn.
_HEDGE_CUES = (
    "đề xuất",
    "có thể",
    "cân nhắc",
    "nên chăng",
    "dự kiến",
    "gợi ý",
    "chưa chốt",
    "xem xét thêm",
    "để xem xét",
    "nghiên cứu thêm",
    "tính sau",
    "hay là",
    "liệu có",
    "ghi nhận",
)

# Từ ngữ cho thấy lượt nói thực sự CHỐT/GIAO/NHẬN việc. Lượt chốt PHẢI có ít
# nhất một cụm ở đây mới được CLEAR: "không có từ do dự" KHÔNG có nghĩa là đã
# chốt (eval: "Tôi đề nghị báo cáo rõ..." + "Sở xin ghi nhận ý kiến" không có
# từ do dự nào nhưng cũng không ai nhận việc). "đề nghị" cố ý không nằm ở đâu
# cả: trong văn nói hành chính nó vừa là chỉ đạo (chủ trì) vừa là kiến nghị
# (đại biểu) -- để debate phân xử theo người nói.
_COMMIT_CUES = (
    "giao cho", "giao nhiệm vụ", "giao việc", "giao em", "giao anh", "giao chị",
    "chốt", "thống nhất", "đồng ý", "phân công", "yêu cầu", "chỉ đạo", "chủ trì",
    "kết luận", "quyết định", "phụ trách", "trước ngày", "thời hạn", "hạn chót",
    "nhất trí", "triển khai ngay", "đảm nhận", "nhé",
    "em nhận", "tôi nhận", "em làm", "để em", "em sẽ", "tôi sẽ", "bên em sẽ", "chúng tôi sẽ",
)
# Trạng thái agent tự khai được coi là đủ để đi thẳng (không cần debate).
_ACTION_STATUSES_CLEAR = frozenset({"assigned", "self_committed"})
_DECISION_STATUSES_CLEAR = frozenset({"agreed"})

# Từ chức năng bỏ khi so trùng nội dung (chỉ để so khớp, không đổi text hiển thị).
_SIMILARITY_STOPWORDS = frozenset(
    "và của cho các những một được để là thì sẽ đã với trong theo về từ khi này "
    "đó lại ra vào cũng như nhằm việc thực hiện giao thống nhất".split()
)
# Ngưỡng gộp trùng, tune trên 30 output eval/results/dialtreeseg_v1 đối chiếu cờ
# "trùng" của judge: Jaccard >= 0.45 VÀ overlap >= 0.7 cho 12 cặp, 11 đúng là
# trùng (1 nhầm: hai việc khác nhau cùng mô tả dài một công trình). Chỉ dùng
# overlap thì gộp nhầm nhiều (một câu ngắn nằm gọn trong một câu kết luận dài).
_DUPLICATE_MIN_JACCARD = 0.45
_DUPLICATE_MIN_OVERLAP = 0.7


def _normalize_for_match(text: str) -> str:
    """Chuẩn hoá để so khớp cụm từ: NFC, hạ chữ thường, gộp khoảng trắng.

    Đầu vào: text - chuỗi bất kỳ.
    Đầu ra: str đã chuẩn hoá.
    """

    return _collapse_whitespace(unicodedata.normalize("NFC", text).casefold())


def _find_cues(text: str, cues: Sequence[str]) -> tuple[str, ...]:
    """Liệt kê các cụm trong ``cues`` xuất hiện trọn từ trong ``text``.

    So theo ranh giới âm tiết, không theo chuỗi con. Tiếng Việt không đánh dấu
    ranh giới từ ghép nên cue một âm tiết vẫn khớp trong từ ghép (vd. "hạn"
    trong "hạn chế") -- vì vậy cue một âm tiết chỉ được dùng ở ``_COMMIT_CUES``
    (sai theo hướng ít gửi debate), còn ``_HEDGE_CUES`` toàn cụm hai âm tiết trở lên.

    Đầu vào: text - chuỗi đã chuẩn hoá; cues - các cụm cần tìm.
    Đầu ra: tuple cụm đã khớp, theo thứ tự trong ``cues``.
    """

    return tuple(cue for cue in cues if re.search(rf"(?<!\w){re.escape(cue)}(?!\w)", text))


def _confirm_turn_reasons(
    confirm_turn: SpeakerTurn | None,
    turns: tuple[SpeakerTurn, ...] = (),
    judge: TurnActJudge | None = None,
) -> list[str]:
    """Lý do nghi ngờ rút ra từ NGUYÊN VĂN lượt nói chốt (không từ câu agent viết lại).

    Có ``judge``: phân loại lượt chốt theo nghĩa (xem ``turn_act``), ba vùng theo
    p_commit: >= ``COMMIT_CLEAR_MIN`` thì không có lý do; giữa hai ngưỡng thì gắn cờ
    "chưa rõ" kèm phân bố xác suất; < ``COMMIT_REJECT_MAX`` thì gắn cờ "không phải lời
    chốt". Judge lỗi thì quay về luật từ khoá.

    Không có ``judge`` (luật từ khoá): lượt chốt chỉ được coi là đã chốt khi có từ
    chốt/giao/nhận việc (``_COMMIT_CUES``); từ đề xuất tìm thấy (nếu có) được nêu kèm
    để debate có đầu mối.

    Đầu vào:
        confirm_turn: lượt nói agent chỉ ra là lượt chốt, None nếu không có.
        turns: các lượt nói của đoạn (lấy các lượt đứng trước làm ngữ cảnh cho judge).
        judge: bộ phân loại lượt nói; None thì dùng luật từ khoá.
    Đầu ra: list lý do (rỗng nếu lượt nói được coi là đã chốt/giao/nhận việc).
    """

    if confirm_turn is None:
        return ["Agent không chỉ ra được lượt nói chốt/giao việc thuộc đoạn này."]
    if judge is not None:
        try:
            return _judged_confirm_turn_reasons(confirm_turn, turns, judge)
        except Exception as exc:  # noqa: BLE001 -- lỗi mạng/API bất kỳ: quay về luật từ khoá
            logger.warning("turn_act judge lỗi ở %s, dùng luật từ khoá: %s", confirm_turn.turn_id, exc)
    text = _normalize_for_match(confirm_turn.text_exact)
    if _find_cues(text, _COMMIT_CUES):
        return []
    reason = f"Lượt chốt {confirm_turn.turn_id} không có từ chốt/giao/nhận việc nào"
    hedges = _find_cues(text, _HEDGE_CUES)
    if hedges:
        reason += f", lại có từ đề xuất/ghi nhận ({', '.join(hedges)})"
    elif text.rstrip(" .…").endswith("?"):
        reason += ", và là câu hỏi"
    return [reason + "."]


def _judged_confirm_turn_reasons(
    confirm_turn: SpeakerTurn, turns: tuple[SpeakerTurn, ...], judge: TurnActJudge
) -> list[str]:
    """Nhánh có judge của ``_confirm_turn_reasons`` (ném lỗi của judge ra ngoài)."""

    index = next((i for i, turn in enumerate(turns) if turn.turn_id == confirm_turn.turn_id), len(turns))
    judgement = judge.judge(confirm_turn, turns[:index])
    p_commit = judgement.p_commit
    if p_commit >= COMMIT_CLEAR_MIN:
        return []
    if p_commit < COMMIT_REJECT_MAX:
        return [
            f"Lượt chốt {confirm_turn.turn_id} không phải lời chốt/giao/nhận việc: "
            f"phân loại là '{judgement.label}' (p_chốt={p_commit:.2f}; {judgement.describe()})."
        ]
    return [
        f"Lượt chốt {confirm_turn.turn_id} chưa rõ là chốt/giao/nhận việc "
        f"(p_chốt={p_commit:.2f}; {judgement.describe()}); cần đọc lại lượt này và ngữ cảnh."
    ]


def _turn_by_id(turns: tuple[SpeakerTurn, ...], turn_id: str | None) -> SpeakerTurn | None:
    """Tra lượt nói theo id trong đoạn; None nếu không có."""

    return next((turn for turn in turns if turn.turn_id == turn_id), None) if turn_id else None


def _split_actor_parts(actor: str) -> list[str]:
    """Tách actor ghép ("Hiếu và Nam", "Sở A, Sở B") thành từng người/đơn vị.

    Đầu vào: actor - chuỗi actor.
    Đầu ra: list khoá đã chuẩn hoá (``make_actor_grouping_key``) của từng phần.
    """

    parts = re.split(r",|;|\bvà\b|\bcùng\b|/", actor)
    return [key for key in (make_actor_grouping_key(part) for part in parts) if key]


def _actor_is_grounded(actor: str, turns: tuple[SpeakerTurn, ...], known_names: Sequence[str]) -> bool:
    """Actor có căn cứ trong đoạn không: mỗi phần của actor phải xuất hiện trọn
    từ trong nội dung/người nói của đoạn, hoặc là tên đã biết từ chủ đề trước.

    Bắt lỗi agent tự gán người không có trong bản ghi ("hộ dân", "các xã"...)
    hoặc lấy nhầm người từ đoạn khác. Khoá bỏ từ xưng hô đứng đầu, nên
    "Anh Phong" khớp "Phong" trong bản ghi.

    Đầu vào:
        actor: người phụ trách do agent nêu.
        turns: các lượt nói của đoạn.
        known_names: tên đã biết từ các chủ đề trước (ngữ cảnh chạy dồn).
    Đầu ra: bool.
    """

    haystack = _normalize_for_match(
        " ".join(f"{turn.speaker or ''} {turn.text_exact}" for turn in turns)
        + " " + " ".join(known_names)
    )
    return all(
        re.search(rf"(?<!\w){re.escape(part)}(?!\w)", haystack)
        for part in _split_actor_parts(actor)
    )


def check_action_evidence(
    item: ActionItemCandidate,
    turns: tuple[SpeakerTurn, ...],
    known_names: Sequence[str] = (),
    judge: TurnActJudge | None = None,
) -> EvidenceFlag:
    """Evidence-check (luật, 0 token) cho một ``ActionItemCandidate``.

    Bản trước chỉ kiểm WHO trên ``actor`` -- mù trước lỗi thường gặp nhất (đo
    trên 30 cuộc họp eval: đề xuất/yêu cầu chưa được nhận, lời mời điều phối,
    câu thủ tục bị biến thành việc giao, actor đều có tên nên lọt CLEAR). Giờ
    kết hợp các tín hiệu KHÔNG phụ thuộc câu agent đã viết lại:

    1. WHO: actor None / không định danh được (như trước).
    2. WHO có căn cứ: actor phải xuất hiện trong đoạn (``_actor_is_grounded``).
    3. Agent tự khai ``status`` không phải "assigned"/"self_committed".
    4. Lượt chốt (``confirm_turn_id``) thiếu, hoặc không phải lời chốt/giao/nhận
       việc (``_confirm_turn_reasons``: theo ``judge`` nếu có, không thì theo từ khoá).
    5. Tự nhận việc (``self_committed``) nhưng người nói lượt chốt khác actor.

    Đầu vào:
        item: candidate cần kiểm.
        turns: các lượt nói của đoạn chứa candidate.
        known_names: tên đã biết từ các chủ đề trước.
        judge: bộ phân loại lượt chốt theo nghĩa; None thì dùng luật từ khoá.
    Đầu ra: EvidenceFlag; ``reasons`` gom MỌI lý do khớp (để debate có đủ đầu mối).
    """

    reasons: list[str] = []
    if item.actor is None:
        reasons.append("Chưa xác định được người phụ trách (WHO).")
    elif is_non_identifying_actor(item.actor):
        reasons.append(f"Actor '{item.actor}' không định danh được một người/nhóm cụ thể (WHO).")
    elif not _actor_is_grounded(item.actor, turns, known_names):
        reasons.append(f"Actor '{item.actor}' không xuất hiện trong bản ghi của đoạn (WHO).")
    if item.status not in _ACTION_STATUSES_CLEAR:
        reasons.append(f"Agent tự đánh giá trạng thái là '{item.status}', chưa phải việc được giao/nhận.")
    confirm_turn = _turn_by_id(turns, item.confirm_turn_id)
    reasons.extend(_confirm_turn_reasons(confirm_turn, turns, judge))
    if (
        item.status == "self_committed"
        and item.actor
        and confirm_turn is not None
        and confirm_turn.speaker
        and match_claimed_name_to_real_speaker(item.actor, turns) not in (None, confirm_turn.speaker.strip())
    ):
        reasons.append(
            f"Ghi là tự nhận việc nhưng lượt chốt {confirm_turn.turn_id} do "
            f"'{confirm_turn.speaker}' nói, không phải '{item.actor}'."
        )
    return EvidenceFlag("uncertain", tuple(reasons)) if reasons else EvidenceFlag("clear")


def check_decision_evidence(
    item: DecisionCandidate,
    turns: tuple[SpeakerTurn, ...],
    judge: TurnActJudge | None = None,
) -> EvidenceFlag:
    """Evidence-check (luật, 0 token) cho một ``DecisionCandidate``: đã thực sự chốt chưa.

    Bản trước chỉ tìm từ đề xuất trong ``text`` -- nhưng decision agent luôn
    viết lại thành "Thống nhất...", nên báo cáo tình hình, số ước tính, câu mở
    đầu, khẩu hiệu đều lọt CLEAR (đo trên eval: 9 kết luận bịa + 6 trap, 0 bị
    gắn cờ). Giờ gắn cờ ``"uncertain"`` khi:

    1. Agent tự khai ``status`` khác "agreed".
    2. ``text`` có từ đề xuất -- CHỈ khi không có ``judge``: khớp cụm không xét nghĩa
       nên gắn cờ nhầm ("có thể sau này nâng cấp" trong một câu đã chốt); có judge thì
       lượt chốt nguyên văn đã được xét theo nghĩa ở bước 3.
    3. Lượt chốt thiếu, hoặc không phải lời chốt (theo ``judge`` nếu có, không thì từ khoá).

    Đầu vào: item - candidate cần kiểm; turns - các lượt nói của đoạn;
        judge - bộ phân loại lượt chốt theo nghĩa (tuỳ chọn).
    Đầu ra: EvidenceFlag; ``reasons`` gom mọi lý do khớp.
    """

    reasons: list[str] = []
    if item.status not in _DECISION_STATUSES_CLEAR:
        reasons.append(f"Agent tự đánh giá trạng thái là '{item.status}', chưa phải kết luận đã chốt.")
    if judge is None:
        matched = _find_cues(_normalize_for_match(item.text), _HEDGE_CUES)
        if matched:
            reasons.append(f"Câu chữ có dấu hiệu chưa chốt: {', '.join(matched)}.")
    reasons.extend(_confirm_turn_reasons(_turn_by_id(turns, item.confirm_turn_id), turns, judge))
    return EvidenceFlag("uncertain", tuple(reasons)) if reasons else EvidenceFlag("clear")


# ---------------------------------------------------------------------------
# Làm sạch output (luật, 0 token)
# ---------------------------------------------------------------------------

# "giao"/"phân công" ĐẦU CÂU chỉ là động từ giao việc khi theo sau là "nhiệm
# vụ"/"việc"/"cho", một từ xưng hô, hoặc một tên riêng viết hoa -- để không
# bắt nhầm từ ghép "giao diện", "giao dịch", "giao thông", "giao ban"...
_ASSIGNMENT_VERB = re.compile(
    r"^\s*(?:giao|phân\s+công)(?:\s+nhiệm\s+vụ|\s+việc)?(?:\s+cho)?\s+", re.IGNORECASE
)
_ASSIGNEE_START = re.compile(
    rf"(?:nhiệm\s+vụ|việc|cho|(?:{'|'.join(_HONORIFIC_PREFIXES)}|đồng\s+chí|đ/c)\b)", re.IGNORECASE
)
_ACTOR_LINKING_WORDS = re.compile(r"^\s*(?:sẽ|phải|cần|chịu trách nhiệm|có trách nhiệm|thực hiện)\s+", re.IGNORECASE)


def _assignment_verb_end(text: str) -> int | None:
    """Vị trí kết thúc cụm động từ giao việc ở đầu câu, hoặc None nếu không phải.

    Đầu vào: text - câu cần xét.
    Đầu ra: chỉ số ký tự ngay sau cụm "giao (nhiệm vụ) (cho) ", hoặc None.
    """

    match = _ASSIGNMENT_VERB.match(text)
    if not match:
        return None
    verb = match.group(0).casefold()
    rest = text[match.end():]
    # "phân công" không có từ ghép nào khác; "giao nhiệm vụ/việc/cho" đã rõ là giao việc.
    is_unambiguous = verb.lstrip().startswith("phân") or any(
        marker in verb for marker in ("nhiệm vụ", "việc", "cho")
    )
    if is_unambiguous or _ASSIGNEE_START.match(rest) or rest[:1].isupper():
        return match.end()
    return None


def _strip_leading_actor(text: str, actor: str | None) -> str | None:
    """Bỏ actor (kèm từ xưng hô và "sẽ/phải/thực hiện") đứng đầu ``text``.

    Đầu vào: text - chuỗi cần xét; actor - người phụ trách (có thể None).
    Đầu ra: phần còn lại nếu ``text`` bắt đầu bằng actor, ngược lại None.
    """

    if not actor:
        return None
    for name in (actor, make_actor_grouping_key(actor)):
        pattern = re.compile(
            rf"^\s*(?:(?:{'|'.join(_HONORIFIC_PREFIXES)})\s+)?{re.escape(name)}(?!\w)[\s,:]*", re.IGNORECASE
        )
        match = pattern.match(text)
        if match:
            return _ACTOR_LINKING_WORDS.sub("", text[match.end():], count=1)
    return None


def strip_assignment_prefix(text: str, actor: str | None) -> str:
    """Bỏ phần lặp "giao <actor>"/"<actor> sẽ" ở đầu nội dung việc giao.

    Prompt đã dặn ``text`` bắt đầu bằng động từ công việc, nhưng model vẫn hay
    viết "giao Hiếu map lại nhãn..." (132/388 việc trên eval) -- lặp đúng
    thông tin đã có ở ``actor``. Chỉ bỏ khi phần đứng đầu KHỚP actor (hoặc là
    động từ "giao"/"phân công" đứng đầu), không đụng vào phần còn lại.

    Đầu vào: text - nội dung việc do model viết; actor - người phụ trách (có thể None).
    Đầu ra: str đã bỏ tiền tố, viết hoa chữ đầu; trả nguyên ``text`` nếu bỏ xong thì rỗng.
    """

    verb = _ASSIGNMENT_VERB.match(text)
    without_actor = _strip_leading_actor(text[verb.end():] if verb else text, actor)
    if without_actor is not None:
        # "giao <actor> ..." (kể cả actor viết thường như "giao phòng Tài chính")
        # hoặc "<actor> sẽ ...".
        result = without_actor
    else:
        verb_end = _assignment_verb_end(text)
        result = text[verb_end:] if verb_end is not None else text
    result = result.strip()
    if not result or result == text.strip():
        return text.strip()
    return result[0].upper() + result[1:]


def is_assignment_point(text: str) -> bool:
    """Luận điểm Content chỉ là câu giao việc ("Giao nhiệm vụ cho Hiếu...").

    Những câu này đã có ở tab Giao việc (Action Agent), nên lặp ở Diễn biến
    (149/1752 luận điểm trên eval). Chỉ bắt câu BẮT ĐẦU bằng động từ giao/phân
    công (``_assignment_verb_end``) -- luận điểm bàn về việc giao ("Đề nghị
    không giao cho xã...") hay nói về "giao diện"/"giao dịch" giữ nguyên.

    Đầu vào: text - nội dung luận điểm.
    Đầu ra: bool.
    """

    return _assignment_verb_end(text) is not None


def _content_tokens(text: str, drop: frozenset[str] = frozenset()) -> frozenset[str]:
    """Tập âm tiết nội dung để so trùng (bỏ từ chức năng và token của ``drop``)."""

    words = re.findall(r"\w+", _normalize_for_match(text))
    return frozenset(w for w in words if len(w) > 1 and w not in _SIMILARITY_STOPWORDS and w not in drop)


def _is_near_duplicate(left: str, right: str, drop: frozenset[str] = frozenset()) -> bool:
    """Hai câu có trùng nội dung không (Jaccard VÀ overlap theo âm tiết, xem ngưỡng ở trên)."""

    a, b = _content_tokens(left, drop), _content_tokens(right, drop)
    if not a or not b:
        return False
    shared = len(a & b)
    return shared / len(a | b) >= _DUPLICATE_MIN_JACCARD and shared / min(len(a), len(b)) >= _DUPLICATE_MIN_OVERLAP


def _merge_evidence(
    keep_ids: tuple[str, ...], keep_quotes: tuple[str, ...], extra_ids: tuple[str, ...], extra_quotes: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Hợp bằng chứng của hai mục trùng, bỏ turn_id lặp, giữ thứ tự."""

    ids, quotes = list(keep_ids), list(keep_quotes)
    for turn_id, quote in zip(extra_ids, extra_quotes):
        if turn_id not in ids:
            ids.append(turn_id)
            quotes.append(quote)
    return tuple(ids), tuple(quotes)


def merge_duplicate_assignments(items: Sequence[ActionItemCandidate]) -> list[ActionItemCandidate]:
    """Gộp các việc giao trùng nội dung của CÙNG một người (trong và giữa các chủ đề).

    Hay gặp khi một việc được bàn ở chủ đề trước rồi chốt lại kèm thời hạn ở
    phần tổng kết. Mục giữ lại là mục có thời hạn (nếu chỉ một bên có), không
    thì mục dài hơn; bằng chứng được hợp lại, vị trí là vị trí mục xuất hiện trước.

    Đầu vào: items - việc giao đã kiểm chứng, theo thứ tự.
    Đầu ra: list đã gộp, giữ thứ tự xuất hiện đầu tiên.
    """

    merged: list[ActionItemCandidate] = []
    for item in items:
        actor_key = make_actor_grouping_key(item.actor or "")
        drop = _content_tokens(item.actor or "")
        for index, kept in enumerate(merged):
            if make_actor_grouping_key(kept.actor or "") != actor_key:
                continue
            if not _is_near_duplicate(kept.text, item.text, drop):
                continue
            prefer_new = (item.deadline_raw and not kept.deadline_raw) or (
                bool(item.deadline_raw) == bool(kept.deadline_raw) and len(item.text) > len(kept.text)
            )
            base, other = (item, kept) if prefer_new else (kept, item)
            ids, quotes = _merge_evidence(base.evidence_ids, base.quotes, other.evidence_ids, other.quotes)
            merged[index] = replace(base, segment_id=kept.segment_id, evidence_ids=ids, quotes=quotes)
            break
        else:
            merged.append(item)
    return merged


def merge_duplicate_decisions(items: Sequence[DecisionCandidate]) -> list[DecisionCandidate]:
    """Gộp các kết luận trùng nội dung (giữ câu dài hơn, hợp bằng chứng).

    Đầu vào: items - kết luận đã kiểm chứng, theo thứ tự.
    Đầu ra: list đã gộp, giữ thứ tự xuất hiện đầu tiên.
    """

    merged: list[DecisionCandidate] = []
    for item in items:
        for index, kept in enumerate(merged):
            if not _is_near_duplicate(kept.text, item.text):
                continue
            base, other = (item, kept) if len(item.text) > len(kept.text) else (kept, item)
            ids, quotes = _merge_evidence(base.evidence_ids, base.quotes, other.evidence_ids, other.quotes)
            merged[index] = replace(base, segment_id=kept.segment_id, evidence_ids=ids, quotes=quotes)
            break
        else:
            merged.append(item)
    return merged


def get_turns_of_segment(
    segment: TopicSegment, turns_by_id: dict[str, SpeakerTurn]
) -> tuple[SpeakerTurn, ...]:
    """Lấy các lượt nói thuộc một đoạn chủ đề, theo đúng thứ tự trong đoạn.

    Chuyển từ ``graph.py`` sang đây vì ``nodes/evidence_check.py`` cũng cần
    dùng lại (để dựng bản ghi cho debate), không chỉ ``graph.py``.

    Đầu vào:
        segment: đoạn chủ đề (``atom_ids`` của nó chính là các turn_id).
        turns_by_id: bảng tra turn_id -> SpeakerTurn của cả cuộc họp.

    Đầu ra: tuple SpeakerTurn của đoạn; turn_id không có trong bảng thì bị bỏ qua.
    """

    return tuple(
        turns_by_id[turn_id] for turn_id in (segment.atom_ids or ()) if turn_id in turns_by_id
    )


def list_distinct_speaker_names(turns: tuple[SpeakerTurn, ...]) -> tuple[str, ...]:
    """Liệt kê tên các người nói khác nhau trong một đoạn chủ đề (luật, không tốn token).

    Đây là tập tên thật mà các cách xưng hô như "em"/"anh" trong đoạn có thể
    quy về.

    Đầu vào: turns - các lượt nói của đoạn.
    Đầu ra: tuple tên người nói, không trùng, giữ thứ tự xuất hiện đầu tiên.
    """

    names: list[str] = []
    for turn in turns:
        speaker = (turn.speaker or "").strip()
        if speaker and speaker not in names:
            names.append(speaker)
    return tuple(names)


def _make_speaker_name_key(name: str) -> str:
    """Tạo khóa so sánh tên người nói: chuẩn hóa Unicode NFC, hạ chữ thường, gộp khoảng trắng.

    NFC quan trọng vì tiếng Việt có thể ở dạng dấu tổ hợp hoặc dấu rời, nhìn
    giống hệt nhau nhưng so sánh chuỗi thô lại khác nhau.

    Đầu vào: name (str) - tên người nói.
    Đầu ra: str - khóa để so khớp.
    """

    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", name).strip().casefold())


def match_claimed_name_to_real_speaker(
    claimed_name: str,
    turns: tuple[SpeakerTurn, ...],
    cited_turn_ids: tuple[str, ...] = (),
) -> str | None:
    """Đưa tên do model viết (``full_name``) về đúng người nói thật của đoạn này (luật, 0 token).

    Prompt yêu cầu model chép đúng tên nhưng không có gì ép buộc, nên tên bịa từng
    lọt vào chữ viết tắt và danh sách tên đã biết giữa các chủ đề. Hàm này chặn lại.

    Thứ tự thử (khớp cái nào trước dùng cái đó):
        1. Khớp chính xác sau khi chuẩn hóa NFC/hạ chữ thường/gộp khoảng trắng.
        2. Tên model nêu là một phần nguyên từ của ĐÚNG MỘT người nói trong đoạn
           (ví dụ "Sơn" -> "Phạm Hồng Sơn"). Nếu mơ hồ (khớp nhiều người) thì không đoán.
        3. Mọi lượt nói được trích dẫn đều do cùng một người nói, chọn người đó
           (bằng chứng có trọng lượng hơn tên sai).

    Đầu vào:
        claimed_name: tên do model viết.
        turns: các lượt nói của đoạn chủ đề.
        cited_turn_ids: các turn_id mà luận điểm trích dẫn (dùng ở bước 3).

    Đầu ra:
        Tên người nói chuẩn, hoặc None nếu không khớp cách nào. Riêng đoạn hoàn
        toàn không có tên người nói thì không có gì để kiểm tra, trả nguyên tên
        model viết (thay vì loại hết luận điểm của bản ghi không gắn nhãn người nói).
    """

    speakers = list_distinct_speaker_names(turns)
    claimed = claimed_name.strip()
    if not speakers:
        return claimed or None

    by_key = {_make_speaker_name_key(name): name for name in speakers}
    if claimed and _make_speaker_name_key(claimed) in by_key:
        return by_key[_make_speaker_name_key(claimed)]

    if claimed:
        pattern = re.compile(rf"(?<!\w){re.escape(_make_speaker_name_key(claimed))}(?!\w)")
        partial = [name for key, name in by_key.items() if pattern.search(key)]
        if len(partial) == 1:
            return partial[0]

    cited = set(cited_turn_ids)
    cited_speakers = {
        (turn.speaker or "").strip() for turn in turns if turn.turn_id in cited
    }
    if len(cited_speakers) == 1 and next(iter(cited_speakers)) in speakers:
        return next(iter(cited_speakers))
    return None


def make_actor_grouping_key(actor: str) -> str:
    """Tạo khóa để gộp các việc được giao theo người phụ trách (chỉ khớp chính xác).

    Chức năng: chuẩn hóa NFC, hạ chữ thường, gộp khoảng trắng và bỏ từ xưng hô đứng
    đầu ("anh", "chị"...). TUYỆT ĐỐI không khớp mờ/chuỗi con.

    Vì sao không khớp mờ: theo dữ liệu thật, người nói chính là "Phạm Hồng Sơn"
    và anh ấy giao việc cho một người KHÁC chỉ được gọi là "Sơn". Gộp theo chuỗi
    con sẽ nhập nhầm hai người này thành một. Chấp nhận việc đôi khi gộp thiếu
    (một cách gọi khác chưa được gộp) vì an toàn hơn.

    Đầu vào: actor (str) - tên người phụ trách như model/bản ghi nêu.
    Đầu ra: str - khóa đã chuẩn hóa để so sánh.
    """

    text = unicodedata.normalize("NFC", actor).strip().casefold()
    text = re.sub(r"\s+", " ", text)
    for prefix in _HONORIFIC_PREFIXES:
        if text.startswith(prefix + " "):
            text = text[len(prefix) + 1 :]
            break
    return text.strip()


def is_bare_personal_pronoun(actor: str) -> bool:
    """Kiểm tra ``actor`` có chỉ là đại từ ngôi thứ nhất/nhị đứng một mình hay không.

    Ví dụ "em", "anh", "bọn em": nghĩa của chúng phụ thuộc ai đang nói với ai,
    nên không thể là người phụ trách trong văn bản báo cáo. Đây là lớp chốt an
    toàn khi model chưa tự quy được về tên thật qua ``previous_context``.

    So khớp CHÍNH XÁC sau chuẩn hóa (cùng cách với ``make_actor_grouping_key``),
    không so khớp chuỗi con, để tên thật có chứa "anh" (như "Hải Anh") không bị chặn nhầm.

    Đầu vào: actor (str) - người phụ trách do model nêu.
    Đầu ra: bool - True nếu là đại từ trần cần loại.
    """

    return make_actor_grouping_key(actor) in _FIRST_OR_SECOND_PERSON_PRONOUNS


def is_non_identifying_actor(actor: str) -> bool:
    """Kiểm tra ``actor`` có phải cụm KHÔNG định danh được một người/nhóm cụ thể nào hay không.

    Gồm ba trường hợp: (1) đại từ ngôi thứ nhất/nhị trần (``is_bare_personal_pronoun``),
    (2) khớp CHÍNH XÁC một cụm trung tính trong ``_NON_IDENTIFYING_ACTOR_PHRASES``
    (vd. "nhóm", "một thành viên"), (3) actor GHÉP có chứa một cụm như vậy dưới dạng
    từ/cụm từ trọn vẹn (vd. "Phạm Hồng Sơn và một thành viên") -- vế (3) dùng so khớp
    theo ranh giới từ (không phải chuỗi con) để không bắt nhầm tên thật tình cờ chứa
    một từ trùng (áp dụng cùng kỹ thuật với ``match_claimed_name_to_real_speaker``).

    Đầu vào: actor (str) - người/nhóm phụ trách do model nêu.
    Đầu ra: bool - True nếu KHÔNG định danh được ai cụ thể, cần loại khỏi actor hợp lệ.
    """

    if is_bare_personal_pronoun(actor):
        return True
    key = make_actor_grouping_key(actor)
    if key in _NON_IDENTIFYING_ACTOR_PHRASES:
        return True
    return any(
        re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", key)
        for phrase in _NON_IDENTIFYING_ACTOR_PHRASES
    )


def collect_names_and_assignments_of_topic(
    speaker_sections: tuple[SpeakerSection, ...], action_items: tuple[ActionItemCandidate, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Thu phần đóng góp của MỘT chủ đề vừa xong vào ngữ cảnh chạy dồn giữa các chủ đề.

    Luật, 0 token. Ngữ cảnh này giúp chủ đề sau quy được "em"/"anh" về tên thật đã
    biết ở chủ đề trước (xem vòng lặp tuần tự trong ``graph.py``). Actor không định
    danh được ai cụ thể (đại từ trần, hoặc cụm như "nhóm"/"một thành viên" --
    ``is_non_identifying_actor``) không bao giờ được đưa vào danh sách tên đã biết,
    vì mang nó sang chủ đề sau chỉ lan sự mơ hồ thay vì giải quyết nó (nếu lọt vào,
    ``format_previous_context`` sẽ hiển thị nó dưới nhãn "Người đã biết tên" và dạy
    model rằng đó là một tên hợp lệ).

    Đầu vào:
        speaker_sections: các phần luận điểm theo người nói của chủ đề.
        action_items: các việc được giao của chủ đề.

    Đầu ra:
        Tuple ``(names, assignments)``: ``names`` là tên thật không trùng (giữ
        thứ tự gặp đầu tiên); ``assignments`` là mỗi việc một dòng "người: nội dung".
    """

    names = [s.full_name for s in speaker_sections if s.full_name]
    for item in action_items:
        actor = (item.actor or "").strip()
        if actor and not is_non_identifying_actor(actor):
            names.append(actor)
    assignments = [
        f"{item.actor}: {item.text}"
        for item in action_items
        if item.actor and not is_non_identifying_actor(item.actor)
    ]
    # Bỏ trùng nhưng giữ thứ tự gặp đầu tiên để chạy lại luôn ra cùng kết quả.
    seen: set[str] = set()
    unique_names = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique_names.append(name)
    return tuple(unique_names), tuple(assignments)


def format_previous_context(known_names: tuple[str, ...], known_assignments: tuple[str, ...]) -> str:
    """Biến ngữ cảnh đã dồn từ các chủ đề trước thành khối văn bản ngắn đưa vào prompt.

    Kết quả nằm ở ``SegmentTask.previous_context``. Đây chỉ là bản tóm tắt tên và
    việc đã giao, không bao giờ là bản ghi thô của các chủ đề trước, để agent
    không phải xử lý lại toàn bộ cuộc họp (SPEC.md AC-5.1).

    Đầu vào:
        known_names: tên người đã biết từ các chủ đề trước.
        known_assignments: các dòng "người: việc" đã giao ở các chủ đề trước.

    Đầu ra: str - khối văn bản cho prompt, hoặc câu báo chưa có chủ đề trước.
    """

    if not known_names and not known_assignments:
        return "(Chưa có chủ đề nào trước đó.)"
    parts = []
    if known_names:
        parts.append("Người đã biết tên từ các chủ đề trước: " + ", ".join(known_names) + ".")
    if known_assignments:
        parts.append("Việc đã được giao ở các chủ đề trước: " + "; ".join(known_assignments) + ".")
    return " ".join(parts)


def format_turns_as_transcript(turns: tuple[SpeakerTurn, ...]) -> str:
    """Dựng bản ghi văn bản đưa vào prompt, mỗi lượt nói một dòng.

    Mỗi dòng có dạng ``[turn_id|người nói] nội dung``. Model được yêu cầu chỉ
    trích phần turn_id đứng trước dấu "|" (xem ``_extract_bare_turn_id``).

    Đầu vào: turns - các lượt nói của đoạn chủ đề.
    Đầu ra: str - các dòng bản ghi nối bằng xuống dòng.
    """

    return "\n".join(
        f"[{turn.turn_id}|{turn.speaker or 'unknown'}] {turn.text_exact}" for turn in turns
    )


def split_into_ranges_within_budget(sizes: Sequence[int], budget: int) -> list[range]:
    """Chia dãy phần tử thành các đoạn LIÊN TIẾP sao cho tổng kích thước mỗi đoạn không vượt ngân sách.

    Chia tham lam từ trái sang phải. Một phần tử tự nó đã lớn hơn ngân sách vẫn
    được một đoạn riêng (không bị bỏ).

    Đầu vào:
        sizes: kích thước (số ký tự) của từng phần tử, theo thứ tự.
        budget: ngân sách tối đa cho tổng kích thước một đoạn.

    Đầu ra: danh sách ``range`` chỉ số, phủ hết các phần tử, đúng thứ tự.
    """

    ranges: list[range] = []
    start, used = 0, 0
    for index, size in enumerate(sizes):
        if index > start and used + size > budget:
            ranges.append(range(start, index))
            start, used = index, 0
        used += size
    if sizes:
        ranges.append(range(start, len(sizes)))
    return ranges


def make_speaker_initials(full_name: str) -> str:
    """Tạo chữ viết tắt của người nói theo quy ước trong tài liệu đích (docx mẫu).

    Lấy chữ cái đầu của từ đầu tiên và chữ cái đầu của từ cuối cùng, viết hoa.
    Ví dụ "Phạm Hồng Sơn" -> "PS", "Người nói không xác định 01" -> "N0".
    Đây là phép biến đổi cơ học nên làm bằng luật, không nhờ LLM (tránh nó bịa).

    Đầu vào: full_name (str) - họ tên đầy đủ.
    Đầu ra: str - chữ viết tắt, hoặc chuỗi rỗng nếu tên rỗng.
    """

    words = full_name.split()
    if not words:
        return ""
    return (words[0][0] + words[-1][0]).upper()


__all__ = [
    "split_dict_entries",
    "read_list_or_empty",
    "read_stripped_text",
    "validate_evidence_with_quotes",
    "validate_evidence_by_turn_ids",
    "read_confirm_turn_id",
    "check_action_evidence",
    "check_decision_evidence",
    "strip_assignment_prefix",
    "is_assignment_point",
    "merge_duplicate_assignments",
    "merge_duplicate_decisions",
    "get_turns_of_segment",
    "list_distinct_speaker_names",
    "match_claimed_name_to_real_speaker",
    "make_actor_grouping_key",
    "is_bare_personal_pronoun",
    "is_non_identifying_actor",
    "collect_names_and_assignments_of_topic",
    "format_previous_context",
    "format_turns_as_transcript",
    "split_into_ranges_within_budget",
    "make_speaker_initials",
]
