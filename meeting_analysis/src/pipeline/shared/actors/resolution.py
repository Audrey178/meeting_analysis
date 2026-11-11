"""Xác định bên nhận một việc giao là người nào, đơn vị nào, hay chưa xác định được (chỉ bằng luật).

Trong họp hành chính, việc hay được giao cho đơn vị ("giao Sở Tài chính chủ trì"), còn người thì
thường chỉ được gọi bằng tên ("anh Sơn"), trong khi có thể có hai người trùng tên. Vì vậy mỗi cách
gọi được so với danh bạ và chấm điểm từng ứng viên, theo thứ tự ưu tiên:

  - Mã danh bạ: agent được xem danh bạ có kèm mã ngắn cho từng người/đơn vị; nếu agent ghi đúng mã
    và mã không mâu thuẫn với tên thì nhận luôn.
  - Tên: khớp đầy đủ được điểm cao nhất, khớp một phần hoặc chỉ khớp tên gọi được điểm thấp hơn.
  - Ngữ cảnh: người lên tiếng ngay sau câu giao việc thường là người nhận; người đang giao việc thì
    không tự gọi mình bằng tên.
  - Chức năng: chỉ khi các cách trên chưa phân định được, so nội dung việc với lĩnh vực phụ trách
    của từng đơn vị.

Khi một việc có nhiều bên (một bên chủ trì, các bên phối hợp), mỗi bên được xác định riêng. Chỉ khi
một ứng viên vừa đủ điểm vừa bỏ xa người thứ hai mới coi là rõ ràng; nếu không thì việc vẫn được giữ
nhưng đánh dấu là chưa rõ người nhận, kèm danh sách ứng viên.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, fields, replace

from ....utils.contracts import SpeakerTurn
from ..meeting_inputs.attendees import AttendeeOrganization
from ..schemas import (
    ActionItemCandidate,
    ActionItem,
    ActorAssignee,
    ActorCandidate,
    ActorType,
    AssigneeMention,
    SpeakerRegistry,
)
from ..text import VN_STOPWORDS, word_tokens
from .assignees import declares_unknown_assignees, format_actor, read_assignee_mentions
from .names import name_key

CLEAR_MIN_SCORE = 0.6
CLEAR_MIN_MARGIN = 0.2

FULL_NAME_SCORE = 1.0
# Bằng ngưỡng: tên gọi khớp DUY NHẤT một người là đủ rõ; hai người cùng tên thì hoà điểm.
GIVEN_NAME_SCORE = CLEAR_MIN_SCORE
PARTIAL_ORG_NAME_SCORE = 0.7
UNLISTED_ORG_SCORE = 0.6
# Người/bên chỉ được nhắc tên trong bản ghi (không phát biểu, không trong danh sách): đủ rõ nếu không ai khác khớp.
MENTIONED_ONLY_SCORE = 0.6
RESPONDER_BONUS = 0.3
ASSIGNER_PENALTY = 0.3
SELF_COMMIT_BONUS = 0.3
FUNCTION_BONUS_PER_TERM = 0.1
FUNCTION_BONUS_MAX = 0.3
# Số lượt sau lượt chốt được xem là "người nhận việc trả lời" ("Dạ em nhận"). Chỉ 1:
# rộng hơn thì lượt GIAO VIỆC MỚI của người khác cũng bị tính là trả lời.
RESPONSE_WINDOW_TURNS = 1

PERSON_CODE_PREFIX = "N"
ORGANIZATION_CODE_PREFIX = "D"

AMBIGUOUS_FLAG = "ambiguous"
MISSING_FLAG = "missing"


@dataclass(frozen=True, slots=True)
class _PersonProfile:
    """Hồ sơ một người có thể là bên nhận việc: người trong danh sách tham dự và/hoặc người nói.

    Attributes:
        name: Họ tên trong danh sách tham dự, hoặc nhãn người nói nếu người đó ngoài danh sách.
        ref_id: Mã người trong danh sách tham dự; None với người nói ngoài danh sách.
        speaker_names: Các nhãn người nói trong bản ghi ứng với người này (rỗng nếu không phát biểu).
        function_terms: Âm tiết nội dung của chức vụ và đơn vị, dùng cho tín hiệu chức năng.
    """

    name: str
    ref_id: str | None
    speaker_names: frozenset[str]
    function_terms: frozenset[str]


def _content_terms(text: str) -> frozenset[str]:
    """Lấy tập âm tiết nội dung (bỏ từ chức năng và âm tiết một ký tự) để so khớp chức năng."""

    return frozenset(token for token in word_tokens(text) if token not in VN_STOPWORDS and len(token) > 1)


def _given_name(name_key: str) -> str:
    """Lấy tên gọi (âm tiết cuối) từ khoá họ tên đã chuẩn hoá."""

    return name_key.rsplit(" ", 1)[-1]


def _organization_terms(org: AttendeeOrganization | None) -> frozenset[str]:
    """Lấy âm tiết nội dung của tên đơn vị và các mảng việc đơn vị phụ trách; rỗng nếu không có đơn vị."""

    if org is None:
        return frozenset()
    return _content_terms(" ".join((org.name, *org.functions)))


def _match_speaker_to_roster(speaker: str, roster_keys: dict[str, str]) -> str | None:
    """Quy một nhãn người nói trong bản ghi về mã người trong danh sách tham dự.

    Khớp họ tên đầy đủ trước; nếu không được thì chấp nhận khi nhãn chỉ là tên gọi và DUY NHẤT một
    người trong danh sách có tên gọi đó (ví dụ nhãn "Sơn" khi chỉ có một người tên Sơn).

    Args:
        speaker: Nhãn người nói trong bản ghi.
        roster_keys: Bảng khoá họ tên đã chuẩn hoá -> mã người.

    Returns:
        Mã người, hoặc None nếu không khớp hoặc khớp nhiều người.
    """

    key = name_key(speaker)
    if key in roster_keys:
        return roster_keys[key]
    same_given_name = [person_id for name_key, person_id in roster_keys.items() if _given_name(name_key) == key]
    return same_given_name[0] if len(same_given_name) == 1 else None


def _build_person_profiles(registry: SpeakerRegistry) -> list[_PersonProfile]:
    """Gộp người trong danh sách tham dự với người nói trong bản ghi thành danh sách ứng viên.

    Người nói được quy về danh sách theo mã trước (mã người nói trùng mã người), không có thì theo
    tên. Người nói không quy được vẫn là một ứng viên riêng, không có ``ref_id``. Thứ tự kết quả cố
    định (người trong danh sách trước, người nói ngoài danh sách sau) vì mã danh bạ dựa vào nó.

    Args:
        registry: Danh bạ người nói kèm danh sách tham dự.

    Returns:
        Danh sách hồ sơ người.
    """

    roster = registry.roster
    roster_keys = {name_key(person.full_name): person.person_id for person in roster.people}
    speakers_by_person: dict[str, set[str]] = {person.person_id: set() for person in roster.people}
    unlisted_speakers: list[str] = []
    for index, speaker in enumerate(registry.names):
        speaker_id = registry.speaker_ids[index] if index < len(registry.speaker_ids) else None
        person_id = speaker_id if speaker_id in speakers_by_person else _match_speaker_to_roster(speaker, roster_keys)
        if person_id is None:
            unlisted_speakers.append(speaker)
        else:
            speakers_by_person[person_id].add(speaker)
    profiles = [
        _PersonProfile(
            name=person.full_name,
            ref_id=person.person_id,
            speaker_names=frozenset(speakers_by_person[person.person_id]),
            function_terms=_content_terms(person.position) | _organization_terms(roster.find_organization(person.org_id)),
        )
        for person in roster.people
    ]
    profiles.extend(
        _PersonProfile(name=speaker, ref_id=None, speaker_names=frozenset({speaker}), function_terms=frozenset())
        for speaker in unlisted_speakers
    )
    return profiles


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """Một người hoặc đơn vị trong danh bạ bên nhận việc đưa vào prompt, kèm mã ngắn.

    Agent được xem danh bạ này và khai lại mã ngắn cho từng bên nhận việc, để luật nhận đúng người
    mà không phải đoán theo tên.

    Attributes:
        code: Mã ngắn trong prompt ("N1", "N2"... cho người, "D1", "D2"... cho đơn vị). Chỉ có nghĩa
            trong một cuộc họp; dựng lại được từ danh bạ nên không cần lưu.
        name: Họ tên trong danh sách tham dự, nhãn người nói (người ngoài danh sách) hoặc tên đơn vị.
        actor_type: "person" hoặc "organization".
        ref_id: Mã người/đơn vị trong danh sách tham dự; None với người nói ngoài danh sách.
        speaker_names: Các nhãn người nói của người này trong bản ghi; rỗng với đơn vị hoặc người
            không phát biểu.
    """

    code: str
    name: str
    actor_type: ActorType
    ref_id: str | None
    speaker_names: frozenset[str] = frozenset()


def build_actor_directory(registry: SpeakerRegistry) -> tuple[DirectoryEntry, ...]:
    """Dựng danh bạ bên nhận việc có mã ngắn, theo thứ tự cố định.

    Prompt và luật cùng gọi hàm này nên cùng một danh bạ luôn cho cùng một mã. Người được đánh mã
    "N1", "N2"... (người trong danh sách tham dự trước, người nói ngoài danh sách sau); đơn vị được
    đánh mã "D1", "D2"... theo thứ tự trong danh sách. Dùng mã ngắn thay cho mã gốc dạng UUID vì
    mô hình hay chép sai UUID.

    Args:
        registry: Danh bạ người nói kèm danh sách tham dự.

    Returns:
        Các mục danh bạ, người trước đơn vị sau; rỗng nếu không có người nói lẫn danh sách.
    """

    people = [
        DirectoryEntry(f"{PERSON_CODE_PREFIX}{index}", profile.name, "person", profile.ref_id, profile.speaker_names)
        for index, profile in enumerate(_build_person_profiles(registry), 1)
    ]
    organizations = [
        DirectoryEntry(f"{ORGANIZATION_CODE_PREFIX}{index}", org.name, "organization", org.org_id)
        for index, org in enumerate(registry.roster.organizations, 1)
    ]
    return (*people, *organizations)


def _score_person_name(alias_key: str, profile: _PersonProfile) -> tuple[float, str]:
    """Chấm điểm khớp tên giữa một cách gọi và một người.

    Khớp trọn họ tên hoặc nhãn người nói được điểm tối đa; cách gọi là phần cuối của họ tên (thường
    là tên gọi, ví dụ "Sơn" với "Phạm Hồng Sơn") được điểm bằng ngưỡng rõ ràng.

    Args:
        alias_key: Khoá đã chuẩn hoá của cách gọi.
        profile: Người cần so.

    Returns:
        Cặp (điểm, lý do); điểm 0 nghĩa là không khớp.
    """

    full_keys = {name_key(profile.name)} | {name_key(name) for name in profile.speaker_names}
    if alias_key in full_keys:
        return FULL_NAME_SCORE, "khớp họ tên/tên người nói"
    if any(key.endswith(" " + alias_key) for key in full_keys):
        return GIVEN_NAME_SCORE, "khớp tên gọi"
    return 0.0, ""


def _score_organization_name(alias_key: str, org: AttendeeOrganization) -> tuple[float, str]:
    """Chấm điểm khớp tên giữa một cách gọi và một đơn vị (tên chính và các tên gọi tắt).

    Khớp trọn tên hoặc tên gọi tắt được điểm tối đa. Cách gọi nhiều âm tiết nằm trong tên đơn vị
    (hoặc ngược lại) được điểm khớp một phần; cách gọi một âm tiết không được xét khớp một phần để
    tránh khớp nhầm.

    Args:
        alias_key: Khoá đã chuẩn hoá của cách gọi.
        org: Đơn vị trong danh sách tham dự.

    Returns:
        Cặp (điểm, lý do); điểm 0 nghĩa là không khớp.
    """

    org_key = name_key(org.name)
    short_keys = [name_key(short) for short in org.aliases]
    if alias_key == org_key:
        return FULL_NAME_SCORE, "khớp tên đơn vị"
    if alias_key in short_keys:
        return FULL_NAME_SCORE, "khớp tên gọi tắt của đơn vị"
    if " " in alias_key and any(alias_key in key or key in alias_key for key in (org_key, *short_keys)):
        return PARTIAL_ORG_NAME_SCORE, "khớp một phần tên đơn vị"
    return 0.0, ""


@dataclass(slots=True)
class _ScoredCandidate:
    """Ứng viên đang được chấm điểm; điểm và lý do được sửa tại chỗ khi cộng các tín hiệu.

    Attributes:
        name: Tên chuẩn của ứng viên.
        actor_type: "person", "organization" hoặc "unknown".
        score: Điểm hiện tại, có thể tạm vượt khỏi [0, 1] trước khi chốt.
        reasons: Các lý do đã cộng/trừ điểm, theo thứ tự.
        ref_id: Mã trong danh sách tham dự; None nếu không có.
        speaker_names: Nhãn người nói của ứng viên, dùng cho tín hiệu ngữ cảnh.
        function_terms: Âm tiết chức năng, dùng cho tín hiệu chức năng.
    """

    name: str
    actor_type: ActorType
    score: float
    reasons: list[str]
    ref_id: str | None
    speaker_names: frozenset[str]
    function_terms: frozenset[str]

    def freeze(self) -> ActorCandidate:
        """Chốt thành ``ActorCandidate``: điểm kẹp trong [0, 1], làm tròn 2 chữ số, các lý do nối lại."""

        return ActorCandidate(
            name=self.name,
            actor_type=self.actor_type,
            score=round(min(1.0, max(0.0, self.score)), 2),
            reason="; ".join(self.reasons),
            ref_id=self.ref_id,
        )


def _is_mentioned_in_meeting(name: str, meeting_turns: Sequence[SpeakerTurn]) -> bool:
    """Kiểm tra một tên có xuất hiện trọn từ trong nguyên văn của ít nhất một lượt nói hay không.

    Cả tên lẫn lượt nói đều được chuẩn hoá như khi so tên trước khi tìm.

    Args:
        name: Tên người hoặc đơn vị.
        meeting_turns: Các lượt nói của cả cuộc họp.

    Returns:
        True nếu tên được nhắc trong bản ghi; False nếu không, hoặc tên rỗng sau chuẩn hoá.
    """

    key = name_key(name)
    pattern = re.compile(rf"(?<!\w){re.escape(key)}(?!\w)")
    return bool(key) and any(pattern.search(name_key(turn.text_exact)) for turn in meeting_turns)


def _collect_name_matches(
    alias: str,
    registry: SpeakerRegistry,
    meeting_turns: Sequence[SpeakerTurn] = (),
    declared_type: str | None = None,
) -> list[_ScoredCandidate]:
    """Tìm mọi người và đơn vị khớp tên với một cách gọi (bước 1 của việc chấm điểm).

    Nếu không ai trong danh bạ khớp nhưng tên được nhắc trong bản ghi, tạo MỘT ứng viên "chỉ được
    nhắc tên" theo loại agent khai: đơn vị ngoài danh sách, hoặc người được giao việc nhưng không
    phát biểu (ví dụ "giao Hiếu chuẩn bị số liệu" mà Hiếu không nói câu nào). Không có lượt nói
    hoặc agent không khai loại thì không tạo, nhờ vậy tên mô hình bịa ra không thành ứng viên.

    Args:
        alias: Cách gọi bên nhận việc.
        registry: Danh bạ người nói kèm danh sách tham dự.
        meeting_turns: Các lượt nói của cả cuộc họp, dùng để kiểm tên có được nhắc hay không.
        declared_type: Loại agent khai cho cách gọi: "person", "organization", "unknown" hoặc None.

    Returns:
        Các ứng viên có điểm tên lớn hơn 0; rỗng nếu không ai khớp.
    """

    alias_key = name_key(alias)
    if not alias_key:
        return []
    matches: list[_ScoredCandidate] = []
    for org in registry.roster.organizations:
        score, reason = _score_organization_name(alias_key, org)
        if score:
            matches.append(
                _ScoredCandidate(org.name, "organization", score, [reason], org.org_id, frozenset(), _organization_terms(org))
            )
    for profile in _build_person_profiles(registry):
        score, reason = _score_person_name(alias_key, profile)
        if score:
            matches.append(
                _ScoredCandidate(profile.name, "person", score, [reason], profile.ref_id,
                                 profile.speaker_names, profile.function_terms)
            )
    if not matches and declared_type is not None and _is_mentioned_in_meeting(alias, meeting_turns):
        if declared_type == "organization":
            matches.append(_ScoredCandidate(alias.strip(), "organization", UNLISTED_ORG_SCORE,
                                            ["đơn vị không có trong danh sách tham dự, được nhắc trong bản ghi"],
                                            None, frozenset(), frozenset()))
        else:
            actor_type: ActorType = "person" if declared_type == "person" else "unknown"
            matches.append(_ScoredCandidate(alias.strip(), actor_type, MENTIONED_ONLY_SCORE,
                                            ["được nhắc tên trong bản ghi, không có trong danh bạ"],
                                            None, frozenset(), frozenset()))
    return matches


def _apply_context_signals(
    candidates: list[_ScoredCandidate],
    meeting_turns: Sequence[SpeakerTurn],
    context_turn_id: str | None,
    is_self_committed: bool,
) -> None:
    """Cộng/trừ điểm theo người nói ở lượt chốt và người nói ngay sau đó (bước 2, được ưu tiên).

    Chỉ áp cho ứng viên là người. Người nói lượt chốt được cộng điểm nếu việc là tự nhận, bị trừ điểm
    nếu không (người giao việc không tự gọi mình bằng tên). Người phát biểu ngay sau lượt chốt được
    cộng điểm, vì người nhận việc thường đáp lại ("Dạ em nhận"). Điểm của ``candidates`` được sửa
    tại chỗ.

    Args:
        candidates: Các ứng viên đã khớp tên.
        meeting_turns: Các lượt nói của cả cuộc họp, theo thứ tự.
        context_turn_id: Lượt chốt giao/nhận việc. None hoặc không có trong bản ghi thì bỏ qua bước này.
        is_self_committed: True nếu việc là tự nhận (người nói lượt chốt chính là bên nhận việc).
    """

    turn_ids = [turn.turn_id for turn in meeting_turns]
    if not context_turn_id or context_turn_id not in turn_ids:
        return
    index = turn_ids.index(context_turn_id)
    confirm_speaker = (meeting_turns[index].speaker or "").strip()
    responders = {
        (turn.speaker or "").strip()
        for turn in meeting_turns[index + 1 : index + 1 + RESPONSE_WINDOW_TURNS]
    } - {confirm_speaker, ""}
    for candidate in candidates:
        if candidate.actor_type != "person":
            continue
        if confirm_speaker in candidate.speaker_names:
            if is_self_committed:
                candidate.score += SELF_COMMIT_BONUS
                candidate.reasons.append(f"tự nhận việc ở lượt chốt {context_turn_id}")
            else:
                candidate.score -= ASSIGNER_PENALTY
                candidate.reasons.append(f"là người giao việc ở lượt chốt {context_turn_id}")
        elif candidate.speaker_names & responders:
            candidate.score += RESPONDER_BONUS
            candidate.reasons.append(f"phát biểu ngay sau lượt chốt {context_turn_id}")


def _apply_function_signals(candidates: list[_ScoredCandidate], task_text: str) -> None:
    """Cộng điểm khi nội dung việc trùng chức vụ, tên đơn vị hoặc mảng phụ trách (bước 3, dự phòng).

    Mỗi âm tiết trùng cộng một ít điểm, có trần. Điểm của ``candidates`` được sửa tại chỗ.

    Args:
        candidates: Các ứng viên đang chấm.
        task_text: Nội dung việc được giao.
    """

    task_terms = _content_terms(task_text)
    for candidate in candidates:
        matched = sorted(task_terms & candidate.function_terms)
        if matched:
            candidate.score += min(FUNCTION_BONUS_MAX, FUNCTION_BONUS_PER_TERM * len(matched))
            candidate.reasons.append(f"chức năng khớp nội dung việc: {', '.join(matched)}")


def _ranked(candidates: list[_ScoredCandidate]) -> tuple[ActorCandidate, ...]:
    """Chốt các ứng viên và sắp theo điểm giảm dần; hoà điểm thì giữ thứ tự ban đầu."""

    frozen = [candidate.freeze() for candidate in candidates]
    return tuple(sorted(frozen, key=lambda candidate: -candidate.score))


def is_clear_choice(candidates: Sequence[ActorCandidate]) -> bool:
    """Kiểm tra ứng viên đứng đầu có đủ rõ để chọn hay không.

    Rõ ràng nghĩa là vừa đủ điểm tối thiểu vừa bỏ xa ứng viên thứ hai một khoảng tối thiểu; một ứng
    viên duy nhất chỉ cần đủ điểm. Hai người trùng tên gọi sẽ hoà điểm nên không bao giờ rõ ràng
    nếu không có thêm tín hiệu.

    Args:
        candidates: Các ứng viên đã sắp theo điểm giảm dần.

    Returns:
        True nếu chọn được ứng viên đứng đầu; False nếu danh sách rỗng, điểm thấp hoặc quá sát nhau.
    """

    if not candidates or candidates[0].score < CLEAR_MIN_SCORE:
        return False
    return len(candidates) == 1 or candidates[0].score - candidates[1].score >= CLEAR_MIN_MARGIN


def rank_actor_candidates(
    alias: str,
    registry: SpeakerRegistry,
    *,
    meeting_turns: Sequence[SpeakerTurn] = (),
    context_turn_id: str | None = None,
    task_text: str = "",
    is_self_committed: bool = False,
    declared_type: str | None = None,
) -> tuple[ActorCandidate, ...]:
    """Chấm điểm mọi ứng viên cho một cách gọi bên nhận việc.

    Thứ tự tín hiệu: khớp tên, rồi ngữ cảnh lượt chốt; tín hiệu chức năng chỉ được xét khi hai
    tín hiệu trên chưa cho ra một ứng viên rõ ràng (xem ``is_clear_choice``).

    Args:
        alias: Cách gọi bên nhận việc, ví dụ "Sơn", "anh Phong", "Sở Tài chính".
        registry: Danh bạ người nói kèm danh sách tham dự.
        meeting_turns: Các lượt nói của cả cuộc họp, cho tín hiệu ngữ cảnh và kiểm tên được nhắc.
        context_turn_id: Lượt chốt giao/nhận việc; None thì bỏ tín hiệu ngữ cảnh.
        task_text: Nội dung việc, cho tín hiệu chức năng; rỗng thì bỏ tín hiệu này.
        is_self_committed: True nếu việc là tự nhận.
        declared_type: Loại agent khai cho cách gọi; None thì không tạo ứng viên "chỉ được nhắc tên".

    Returns:
        Các ứng viên theo điểm giảm dần; rỗng nếu không ai khớp tên.
    """

    candidates = _collect_name_matches(alias, registry, meeting_turns, declared_type)
    _apply_context_signals(candidates, meeting_turns, context_turn_id, is_self_committed)
    if task_text and not is_clear_choice(_ranked(candidates)):
        _apply_function_signals(candidates, task_text)
    return _ranked(candidates)


def to_action_item(item: ActionItemCandidate, **changes) -> ActionItem:
    """Chuyển một candidate việc giao thành ``ActionItem``, giữ mọi trường cũ và đặt thêm trường mới.

    Args:
        item: Candidate việc giao, hoặc một ``ActionItem`` có sẵn (khi đó chỉ thay các trường).
        **changes: Các trường cần đặt hoặc ghi đè.

    Returns:
        ``ActionItem`` mới.
    """

    if isinstance(item, ActionItem):
        return replace(item, **changes)
    base = {field.name: getattr(item, field.name) for field in fields(ActionItemCandidate)}
    return ActionItem(**{**base, **changes})


def _rank_for_item(
    item: ActionItemCandidate, registry: SpeakerRegistry, meeting_turns, alias: str, declared_type: str | None = None
):
    """Chấm ứng viên cho một cách gọi, lấy lượt chốt, nội dung và kiểu tự nhận từ chính việc giao."""

    return rank_actor_candidates(
        alias,
        registry,
        meeting_turns=meeting_turns,
        context_turn_id=item.confirm_turn_id,
        task_text=item.text,
        is_self_committed=item.status == "self_committed",
        declared_type=declared_type,
    )


_ROLE_ORDER = {"lead": 0, "joint": 1, "support": 2}


def split_item_mentions(item: ActionItemCandidate) -> tuple[AssigneeMention, ...]:
    """Lấy các bên nhận việc mà agent khai cho một việc giao.

    Nếu candidate chỉ có chuỗi ``actor`` (không có danh sách bên nhận việc) thì cả chuỗi là MỘT bên
    chủ trì; không tự tách chuỗi theo "và" hay "phối hợp".

    Args:
        item: Việc giao.

    Returns:
        Các bên nhận việc; rỗng nếu không có bên nào.
    """

    if item.mentions:
        return item.mentions
    actor = (item.actor or "").strip()
    return (AssigneeMention(actor, "lead"),) if actor else ()


def _same_actor(candidate: ActorCandidate, entry: DirectoryEntry) -> bool:
    """Kiểm tra một ứng viên và một mục danh bạ có cùng là một người/đơn vị hay không.

    So theo mã trong danh sách tham dự nếu một trong hai có mã, không thì so theo tên.
    """

    if candidate.actor_type != entry.actor_type:
        return False
    if candidate.ref_id or entry.ref_id:
        return candidate.ref_id == entry.ref_id
    return candidate.name == entry.name


def _resolve_by_code(
    item: ActionItemCandidate, registry: SpeakerRegistry, meeting_turns, mention: AssigneeMention
) -> ActorAssignee | None:
    """Xác định MỘT bên nhận việc theo mã danh bạ mà agent khai.

    Mã chỉ được nhận khi có trong danh bạ VÀ tên agent chép không trỏ sang bên khác: nếu tên khớp
    được ai đó thì bên theo mã phải nằm trong số đó. Tên không khớp ai (cách gọi riêng, chức vụ)
    thì tin mã. Nhờ vậy, khi có hai người cùng tên "Sơn", mã chọn được đúng người mà luật chấm điểm
    để hoà.

    Args:
        item: Việc giao, cung cấp ngữ cảnh chấm điểm.
        registry: Danh bạ người nói kèm danh sách tham dự.
        meeting_turns: Các lượt nói của cả cuộc họp.
        mention: Bên nhận việc do agent khai, có thể kèm mã.

    Returns:
        Bên nhận việc đã xác định, hoặc None (không có mã, mã lạ, hoặc tên mâu thuẫn với mã) để
        nơi gọi chuyển sang luật chấm điểm.
    """

    if not mention.code:
        return None
    entry = next((entry for entry in build_actor_directory(registry) if entry.code == mention.code), None)
    if entry is None:
        return None
    candidates = _rank_for_item(item, registry, meeting_turns, mention.name, mention.actor_type)
    if candidates and not any(_same_actor(candidate, entry) for candidate in candidates):
        return None
    chosen = ActorCandidate(entry.name, entry.actor_type, FULL_NAME_SCORE, f"agent khai mã {entry.code}", entry.ref_id)
    others = tuple(candidate for candidate in candidates if not _same_actor(candidate, entry))
    return ActorAssignee(mention.name, mention.role, entry.name, entry.actor_type, (chosen, *others), None,
                         f"Agent khai mã {entry.code} ({entry.name}).", entry.ref_id)


def _resolve_mention(
    item: ActionItemCandidate, registry: SpeakerRegistry, meeting_turns, mention: AssigneeMention
) -> ActorAssignee:
    """Xác định MỘT bên nhận việc: theo mã danh bạ nếu nhận được, không thì theo luật chấm điểm.

    Args:
        item: Việc giao, cung cấp ngữ cảnh chấm điểm.
        registry: Danh bạ người nói kèm danh sách tham dự.
        meeting_turns: Các lượt nói của cả cuộc họp.
        mention: Cách gọi và vai trò của bên nhận việc.

    Returns:
        Bên nhận việc. Không có ứng viên rõ ràng thì ``name`` là None, loại là "unknown", kèm cờ
        chưa rõ và danh sách ứng viên.
    """

    coded = _resolve_by_code(item, registry, meeting_turns, mention)
    if coded is not None:
        return coded
    candidates = _rank_for_item(item, registry, meeting_turns, mention.name, mention.actor_type)
    if is_clear_choice(candidates):
        top = candidates[0]
        return ActorAssignee(mention.name, mention.role, top.name, top.actor_type, candidates, None,
                             f"Luật chấm điểm: {top.reason}", top.ref_id)
    return ActorAssignee(mention.name, mention.role, None, "unknown", candidates, AMBIGUOUS_FLAG,
                         f"Không có ứng viên rõ ràng cho '{mention.name}'.")


def _summarize_assignees(item: ActionItemCandidate, assignees: Sequence[ActorAssignee]) -> ActionItem:
    """Gắn các bên nhận việc vào việc giao và tóm tắt thành các trường actor của cả việc.

    Bên chính là bên đứng đầu sau khi xếp chủ trì -> cùng thực hiện -> phối hợp; loại, ứng viên và
    lý do của việc lấy theo bên chính. Chuỗi ``actor`` là tên chuẩn của mọi bên (bên chưa xác định
    thì dùng cách gọi gốc), nối bằng ", ". Chỉ cần một bên chưa rõ là cả việc bị gắn cờ chưa rõ.

    Args:
        item: Việc giao.
        assignees: Các bên đã xác định, không rỗng.

    Returns:
        ``ActionItem`` đã gắn bên nhận việc.
    """

    ordered = tuple(sorted(assignees, key=lambda assignee: _ROLE_ORDER[assignee.role]))
    primary = ordered[0]
    return to_action_item(
        item,
        actor=", ".join(assignee.name or assignee.mention for assignee in ordered),
        actor_type=primary.actor_type,
        actor_candidates=primary.candidates,
        actor_flag=AMBIGUOUS_FLAG if any(assignee.flag for assignee in ordered) else None,
        actor_reason=primary.reason,
        assignees=ordered,
    )


def resolve_actor(
    item: ActionItemCandidate, registry: SpeakerRegistry, meeting_turns: Sequence[SpeakerTurn]
) -> ActionItem:
    """Xác định mọi bên nhận việc của một việc giao chỉ bằng luật (khi Verifier không chọn).

    Bên nào rõ ràng thì đổi về tên chuẩn của ứng viên đứng đầu; bên nào không rõ thì giữ cách gọi
    gốc, loại "unknown", kèm ứng viên và cờ chưa rõ. Việc không có bên nào được gắn cờ thiếu bên
    nhận việc.

    Args:
        item: Việc giao.
        registry: Danh bạ người nói kèm danh sách tham dự.
        meeting_turns: Các lượt nói của cả cuộc họp.

    Returns:
        ``ActionItem`` đã gắn bên nhận việc.
    """

    mentions = split_item_mentions(item)
    if not mentions:
        return to_action_item(item, actor_type="unknown", actor_flag=MISSING_FLAG,
                                 actor_reason="Agent không nêu được người/đơn vị phụ trách.", assignees=())
    return _summarize_assignees(item, [_resolve_mention(item, registry, meeting_turns, m) for m in mentions])


def _pick_verified_assignee(
    item: ActionItemCandidate, registry: SpeakerRegistry, meeting_turns, mention: AssigneeMention, reason: str
) -> ActorAssignee | None:
    """Nhận MỘT bên nhận việc mà Verifier nêu, nếu tên đó đúng là một người/đơn vị có thật.

    "Có thật" là người nói, người hoặc đơn vị trong danh sách tham dự, hoặc tên được nhắc trong bản
    ghi; nhờ vậy Verifier không thể bịa ra tên mới. Mã danh bạ (nếu có và hợp lệ) được dùng trước;
    không thì tên Verifier nêu phải khớp chính xác (sau chuẩn hoá) tên một ứng viên.

    Args:
        item: Việc giao, cung cấp ngữ cảnh chấm điểm.
        registry: Danh bạ người nói kèm danh sách tham dự.
        meeting_turns: Các lượt nói của cả cuộc họp.
        mention: Bên nhận việc do Verifier nêu.
        reason: Lý do Verifier đưa ra, ghi lại vào kết quả.

    Returns:
        Bên nhận việc đã xác định, hoặc None nếu tên không khớp chính xác ứng viên nào.
    """

    coded = _resolve_by_code(item, registry, meeting_turns, mention)
    if coded is not None:
        return replace(coded, reason=f"Verifier: {reason}")
    mention_key = name_key(mention.name)
    candidates = _rank_for_item(item, registry, meeting_turns, mention.name, mention.actor_type)
    picked = next((c for c in candidates if name_key(c.name) == mention_key), None)
    if picked is None:
        return None
    return ActorAssignee(mention.name, mention.role, picked.name, picked.actor_type, candidates, None,
                         f"Verifier: {reason}", picked.ref_id)


def apply_verifier_actor_choice(
    item: ActionItemCandidate,
    choice: dict,
    registry: SpeakerRegistry,
    meeting_turns: Sequence[SpeakerTurn],
    *,
    original_mentions: Sequence[AssigneeMention] = (),
) -> ActionItem:
    """Áp lựa chọn bên nhận việc của Verifier vào một việc giao, nếu lựa chọn đó dùng được.

    Có ba trường hợp:

    - Verifier khai mọi bên là "unknown": giữ các bên ban đầu nhưng đánh dấu tất cả là chưa rõ.
    - Verifier có nêu lý do và MỌI bên Verifier nêu (hoặc các bên sẵn có, nếu Verifier không nêu
      bên nào) đều là ứng viên có thật: dùng lựa chọn đó.
    - Còn lại (thiếu lý do, có bên không có thật...): bỏ qua Verifier, xác định lại bằng luật.

    Args:
        item: Việc giao sau các luật kiểm tra.
        choice: JSON lượt trả lời cuối của Verifier; ``{}`` nếu không có.
        registry: Danh bạ người nói kèm danh sách tham dự.
        meeting_turns: Các lượt nói của cả cuộc họp.
        original_mentions: Các bên nhận việc lúc việc được gửi Verifier, dùng làm cách gọi gốc khi
            Verifier khai "unknown"; rỗng thì lấy từ chính việc giao.

    Returns:
        ``ActionItem`` đã gắn bên nhận việc.
    """

    reason = (choice.get("actor_reason") or "").strip()
    chosen = read_assignee_mentions(choice.get("revised_assignees"))
    if declares_unknown_assignees(choice.get("revised_assignees")):
        baseline = tuple(original_mentions) or split_item_mentions(item)
        if not baseline:
            return resolve_actor(item, registry, meeting_turns)
        unknown_reason = reason or "Verifier không xác định được người/đơn vị phụ trách."
        assignees = [
            ActorAssignee(m.name, m.role, None, "unknown",
                          _rank_for_item(item, registry, meeting_turns, m.name, m.actor_type),
                          AMBIGUOUS_FLAG, unknown_reason)
            for m in baseline
        ]
        return _summarize_assignees(replace(item, actor=format_actor(baseline), mentions=baseline), assignees)
    mentions = chosen or split_item_mentions(item)
    if reason and mentions:
        picked = [_pick_verified_assignee(item, registry, meeting_turns, m, reason) for m in mentions]
        if all(picked):
            return _summarize_assignees(replace(item, actor=format_actor(mentions), mentions=tuple(mentions)), picked)
    return resolve_actor(item, registry, meeting_turns)


__all__ = [
    "AMBIGUOUS_FLAG",
    "DirectoryEntry",
    "build_actor_directory",
    "CLEAR_MIN_MARGIN",
    "CLEAR_MIN_SCORE",
    "MISSING_FLAG",
    "apply_verifier_actor_choice",
    "is_clear_choice",
    "rank_actor_candidates",
    "resolve_actor",
    "split_item_mentions",
    "to_action_item",
]
