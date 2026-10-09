"""Định danh actor của việc giao (luật, 0 token): người, đơn vị hay chưa xác định.

Họp hành chính hay giao việc cho đơn vị ("giao Sở Tài chính chủ trì"), và tên gọi
trong bản ghi thường chỉ là tên ("anh Sơn") trong khi có thể có hai người cùng tên.
Module này chấm điểm các ứng viên cho một cách gọi, theo thứ tự ưu tiên:

1. Tên: khớp họ tên/tên đơn vị/tên người nói (1.0), khớp một phần tên đơn vị (0.7),
   khớp tên gọi (0.6), dạng tên đơn vị nhưng không có trong danh sách (0.6).
2. Ngữ cảnh bản ghi quanh lượt chốt (ưu tiên trước): người phát biểu ngay sau lượt
   chốt (thường là người nhận việc) được cộng; người nói lượt chốt bị trừ khi việc là
   được giao (không ai tự gọi mình là "anh Sơn").
3. Chức năng (CHỈ khi ngữ cảnh chưa phân định được): từ nội dung việc trùng với chức vị,
   tên đơn vị hoặc ``functions`` của đơn vị trong file danh sách.

Actor ghép ("Sở Tài chính chủ trì, phối hợp Sở Xây dựng") được tách thành nhiều bên nhận
việc kèm vai trò (``mentions.py``), mỗi bên định danh riêng (``ActorAssignee``).

Một ứng viên là RÕ RÀNG khi điểm >= ``CLEAR_MIN_SCORE`` và hơn ứng viên thứ hai ít nhất
``CLEAR_MIN_MARGIN``. Không rõ thì ``actor_type = "unknown"``, giữ danh sách ứng viên và
gắn cờ ``actor_flag = "ambiguous"``, không bỏ việc giao.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, fields, replace

from ...agentic.schemas import ActionItemCandidate
from ...stages._shared import VN_STOPWORDS, word_tokens
from ...utils.contracts import SpeakerTurn
from .mentions import ActorMention, find_support_names_in_text, split_actor_mentions
from .attendees import AttendeeOrganization
from ..schemas import ActionItemV3, ActorAssignee, ActorCandidate, ActorType, SpeakerRegistry

CLEAR_MIN_SCORE = 0.6
CLEAR_MIN_MARGIN = 0.2

FULL_NAME_SCORE = 1.0
# Bằng ngưỡng: tên gọi khớp DUY NHẤT một người là đủ rõ; hai người cùng tên thì hoà điểm.
GIVEN_NAME_SCORE = CLEAR_MIN_SCORE
PARTIAL_ORG_NAME_SCORE = 0.7
UNLISTED_ORG_SCORE = 0.6
RESPONDER_BONUS = 0.3
ASSIGNER_PENALTY = 0.3
SELF_COMMIT_BONUS = 0.3
FUNCTION_BONUS_PER_TERM = 0.1
FUNCTION_BONUS_MAX = 0.3
# Số lượt sau lượt chốt được xem là "người nhận việc trả lời" ("Dạ em nhận"). Chỉ 1:
# rộng hơn thì lượt GIAO VIỆC MỚI của người khác cũng bị tính là trả lời.
RESPONSE_WINDOW_TURNS = 1

AMBIGUOUS_FLAG = "ambiguous"
MISSING_FLAG = "missing"

# Viết tắt hay gặp trong tên đơn vị. Cùng với việc bỏ "nhân dân" sau "ủy ban"/"hội đồng"
# (``_CANONICAL_PEOPLE_COUNCIL``), "UBND TP", "Ủy ban nhân dân Thành phố" và "Ủy ban Thành
# phố" cùng về một khoá "ủy ban thành phố"; HĐND vẫn khác UBND ("hội đồng" ≠ "ủy ban").
_ORGANIZATION_ABBREVIATIONS = {"ubnd": "ủy ban", "hđnd": "hội đồng", "tp": "thành phố"}
_CANONICAL_PEOPLE_COUNCIL = re.compile(r"(?<!\w)(ủy ban|hội đồng) nhân dân(?!\w)")
_ADDRESS_PREFIXES = ("đồng chí", "đ/c", "anh", "chị", "em", "bạn", "cô", "chú", "bác", "ông", "bà")
_ORGANIZATION_PATTERN = re.compile(
    r"^(sở|ban|ủy ban|hội đồng|bộ|cục|chi cục|tổng cục|phòng|văn phòng|"
    r"trung tâm|công ty|tổng công ty|thành ủy|đảng ủy|cảng vụ|viện|tổ công tác)(?!\w)"
)


def normalize_name_key(text: str) -> str:
    """Khoá so sánh tên: NFC, hạ chữ thường, bỏ phần trong ngoặc, bỏ từ xưng hô đứng đầu,
    thống nhất "uỷ"/"ủy", mở rộng viết tắt UBND/HĐND/TP và bỏ "nhân dân" sau "ủy ban"/"hội đồng".

    Vd. "Đ/c Thông (HNI)" -> "thông", "anh Phạm Hồng Sơn" -> "phạm hồng sơn",
    "UBND TP", "Ủy ban nhân dân Thành phố", "Ủy ban Thành phố" -> "ủy ban thành phố".

    Đầu vào: text - tên người/đơn vị như bản ghi hoặc model viết.
    Đầu ra: str - khoá đã chuẩn hoá.
    """

    key = unicodedata.normalize("NFC", text).casefold()
    key = re.sub(r"\([^)]*\)", " ", key).replace("uỷ", "ủy")
    for abbreviation, expansion in _ORGANIZATION_ABBREVIATIONS.items():
        key = re.sub(rf"(?<!\w){abbreviation}(?!\w)", expansion, key)
    key = _CANONICAL_PEOPLE_COUNCIL.sub(r"\1", key)
    key = re.sub(r"\s+", " ", key).strip()
    for prefix in _ADDRESS_PREFIXES:
        if key.startswith(prefix + " "):
            key = key[len(prefix) + 1 :].strip()
            break
    return key


def looks_like_organization(text: str) -> bool:
    """Cụm có dạng tên đơn vị (bắt đầu bằng "Sở", "Ban", "UBND"...) hay không.

    Đầu vào: text - actor do model nêu.
    Đầu ra: bool.
    """

    return bool(_ORGANIZATION_PATTERN.match(normalize_name_key(text)))


@dataclass(frozen=True, slots=True)
class _PersonProfile:
    """Một người có thể là actor: người trong danh sách và/hoặc người nói trong bản ghi."""

    name: str
    ref_id: str | None
    speaker_names: frozenset[str]
    function_terms: frozenset[str]


def _content_terms(text: str) -> frozenset[str]:
    """Âm tiết nội dung (bỏ hư từ) của một chuỗi, để so khớp chức năng."""

    return frozenset(token for token in word_tokens(text) if token not in VN_STOPWORDS and len(token) > 1)


def _given_name(name_key: str) -> str:
    """Tên gọi (âm tiết cuối) của một khoá họ tên."""

    return name_key.rsplit(" ", 1)[-1]


def _organization_terms(org: AttendeeOrganization | None) -> frozenset[str]:
    """Âm tiết nội dung của tên đơn vị và các mảng việc đơn vị phụ trách."""

    if org is None:
        return frozenset()
    return _content_terms(" ".join((org.name, *org.functions)))


def _match_speaker_to_roster(speaker: str, roster_keys: dict[str, str]) -> str | None:
    """Quy một tên người nói trong bản ghi về mã người trong danh sách.

    Khớp họ tên đầy đủ trước; không có thì khớp tên gọi nếu DUY NHẤT một người trong
    danh sách có tên gọi đó.

    Đầu vào: speaker - tên người nói; roster_keys - khoá họ tên -> mã người.
    Đầu ra: mã người, hoặc None nếu không khớp/mơ hồ.
    """

    key = normalize_name_key(speaker)
    if key in roster_keys:
        return roster_keys[key]
    same_given_name = [person_id for name_key, person_id in roster_keys.items() if _given_name(name_key) == key]
    return same_given_name[0] if len(same_given_name) == 1 else None


def _build_person_profiles(registry: SpeakerRegistry) -> list[_PersonProfile]:
    """Gộp người trong danh sách với người nói trong bản ghi thành một danh sách ứng viên.

    Người nói không quy được về danh sách vẫn là một ứng viên (không có ``ref_id``).

    Đầu vào: registry - danh bạ người nói + danh sách tham dự.
    Đầu ra: list _PersonProfile.
    """

    roster = registry.roster
    roster_keys = {normalize_name_key(person.full_name): person.person_id for person in roster.people}
    speakers_by_person: dict[str, set[str]] = {person.person_id: set() for person in roster.people}
    unlisted_speakers: list[str] = []
    for speaker in registry.names:
        person_id = _match_speaker_to_roster(speaker, roster_keys)
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


def _score_person_name(alias_key: str, profile: _PersonProfile) -> tuple[float, str]:
    """Điểm khớp tên giữa cách gọi và một người.

    Đầu vào: alias_key - khoá cách gọi; profile - người cần so.
    Đầu ra: (điểm, lý do); điểm 0 nghĩa là không khớp.
    """

    full_keys = {normalize_name_key(profile.name)} | {normalize_name_key(name) for name in profile.speaker_names}
    if alias_key in full_keys:
        return FULL_NAME_SCORE, "khớp họ tên/tên người nói"
    if any(key.endswith(" " + alias_key) for key in full_keys):
        return GIVEN_NAME_SCORE, "khớp tên gọi"
    return 0.0, ""


def _score_organization_name(alias_key: str, org: AttendeeOrganization) -> tuple[float, str]:
    """Điểm khớp tên giữa cách gọi và một đơn vị trong danh sách (tên chính và tên gọi tắt).

    Đầu vào: alias_key - khoá cách gọi; org - đơn vị.
    Đầu ra: (điểm, lý do); điểm 0 nghĩa là không khớp.
    """

    org_key = normalize_name_key(org.name)
    short_keys = [normalize_name_key(short) for short in org.aliases]
    if alias_key == org_key:
        return FULL_NAME_SCORE, "khớp tên đơn vị"
    if alias_key in short_keys:
        return FULL_NAME_SCORE, "khớp tên gọi tắt của đơn vị"
    if " " in alias_key and any(alias_key in key or key in alias_key for key in (org_key, *short_keys)):
        return PARTIAL_ORG_NAME_SCORE, "khớp một phần tên đơn vị"
    return 0.0, ""


@dataclass(slots=True)
class _ScoredCandidate:
    """Ứng viên đang được chấm điểm (mutable trong lúc cộng tín hiệu)."""

    name: str
    actor_type: ActorType
    score: float
    reasons: list[str]
    ref_id: str | None
    speaker_names: frozenset[str]
    function_terms: frozenset[str]

    def freeze(self) -> ActorCandidate:
        """Chốt thành ``ActorCandidate`` (điểm kẹp trong [0, 1], làm tròn 2 chữ số)."""

        return ActorCandidate(
            name=self.name,
            actor_type=self.actor_type,
            score=round(min(1.0, max(0.0, self.score)), 2),
            reason="; ".join(self.reasons),
            ref_id=self.ref_id,
        )


def _collect_name_matches(alias: str, registry: SpeakerRegistry) -> list[_ScoredCandidate]:
    """Bước 1: mọi người/đơn vị khớp tên với cách gọi.

    Đầu vào: alias - cách gọi; registry - danh bạ + danh sách tham dự.
    Đầu ra: list ứng viên có điểm tên > 0.
    """

    alias_key = normalize_name_key(alias)
    if not alias_key:
        return []
    matches: list[_ScoredCandidate] = []
    for org in registry.roster.organizations:
        score, reason = _score_organization_name(alias_key, org)
        if score:
            matches.append(
                _ScoredCandidate(org.name, "organization", score, [reason], org.org_id, frozenset(), _organization_terms(org))
            )
    if not matches and looks_like_organization(alias):
        matches.append(
            _ScoredCandidate(alias.strip(), "organization", UNLISTED_ORG_SCORE,
                             ["dạng tên đơn vị, không có trong danh sách tham dự"], None, frozenset(), frozenset())
        )
    for profile in _build_person_profiles(registry):
        score, reason = _score_person_name(alias_key, profile)
        if score:
            matches.append(
                _ScoredCandidate(profile.name, "person", score, [reason], profile.ref_id,
                                 profile.speaker_names, profile.function_terms)
            )
    return matches


def _apply_context_signals(
    candidates: list[_ScoredCandidate],
    meeting_turns: Sequence[SpeakerTurn],
    context_turn_id: str | None,
    is_self_committed: bool,
) -> None:
    """Bước 2 (ưu tiên): cộng/trừ điểm theo ai nói ở lượt chốt và ngay sau đó.

    Sửa điểm của ``candidates`` tại chỗ.

    Đầu vào:
        candidates: ứng viên đã khớp tên.
        meeting_turns: lượt nói của cả cuộc họp, theo thứ tự.
        context_turn_id: lượt chốt giao/nhận việc (None thì bỏ qua bước này).
        is_self_committed: True nếu việc là tự nhận (người nói lượt chốt chính là actor).
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
    """Bước 3 (dự phòng): cộng điểm khi nội dung việc trùng chức vị/đơn vị/chức năng.

    Sửa điểm của ``candidates`` tại chỗ.

    Đầu vào: candidates - ứng viên; task_text - nội dung việc được giao.
    """

    task_terms = _content_terms(task_text)
    for candidate in candidates:
        matched = sorted(task_terms & candidate.function_terms)
        if matched:
            candidate.score += min(FUNCTION_BONUS_MAX, FUNCTION_BONUS_PER_TERM * len(matched))
            candidate.reasons.append(f"chức năng khớp nội dung việc: {', '.join(matched)}")


def _ranked(candidates: list[_ScoredCandidate]) -> tuple[ActorCandidate, ...]:
    """Chốt và sắp ứng viên theo điểm giảm dần (hoà điểm giữ thứ tự gốc)."""

    frozen = [candidate.freeze() for candidate in candidates]
    return tuple(sorted(frozen, key=lambda candidate: -candidate.score))


def is_clear_choice(candidates: Sequence[ActorCandidate]) -> bool:
    """Ứng viên đứng đầu có đủ rõ để chọn hay không.

    Đầu vào: candidates - đã sắp điểm giảm dần.
    Đầu ra: True nếu điểm đầu >= ``CLEAR_MIN_SCORE`` và hơn ứng viên thứ hai ít nhất
        ``CLEAR_MIN_MARGIN``.
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
) -> tuple[ActorCandidate, ...]:
    """Chấm điểm mọi ứng viên cho một cách gọi actor.

    Ngữ cảnh bản ghi được xét trước; chức năng chỉ được xét khi ngữ cảnh chưa cho ra
    một ứng viên rõ ràng (``is_clear_choice``).

    Đầu vào:
        alias: cách gọi actor, vd "Sơn", "anh Phong", "Sở Tài chính".
        registry: danh bạ người nói + danh sách tham dự.
        meeting_turns: lượt nói của cả cuộc họp (cho tín hiệu ngữ cảnh).
        context_turn_id: lượt chốt giao/nhận việc.
        task_text: nội dung việc (cho tín hiệu chức năng).
        is_self_committed: việc là tự nhận.
    Đầu ra: tuple ActorCandidate, điểm giảm dần (rỗng nếu không ai khớp tên).
    """

    candidates = _collect_name_matches(alias, registry)
    _apply_context_signals(candidates, meeting_turns, context_turn_id, is_self_committed)
    if task_text and not is_clear_choice(_ranked(candidates)):
        _apply_function_signals(candidates, task_text)
    return _ranked(candidates)


def to_action_item_v3(item: ActionItemCandidate, **changes) -> ActionItemV3:
    """Chuyển một việc giao của v1 thành ``ActionItemV3`` (giữ nguyên mọi trường cũ).

    Đầu vào: item - ActionItemCandidate hoặc ActionItemV3; changes - trường cần đặt.
    Đầu ra: ActionItemV3.
    """

    if isinstance(item, ActionItemV3):
        return replace(item, **changes)
    base = {field.name: getattr(item, field.name) for field in fields(ActionItemCandidate)}
    return ActionItemV3(**{**base, **changes})


def _rank_for_item(item: ActionItemCandidate, registry: SpeakerRegistry, meeting_turns, alias: str):
    """Chấm ứng viên cho một cách gọi, lấy ngữ cảnh từ chính việc giao."""

    return rank_actor_candidates(
        alias,
        registry,
        meeting_turns=meeting_turns,
        context_turn_id=item.confirm_turn_id,
        task_text=item.text,
        is_self_committed=item.status == "self_committed",
    )


_ROLE_ORDER = {"lead": 0, "joint": 1, "support": 2}


def split_item_mentions(item: ActionItemCandidate, registry: SpeakerRegistry) -> tuple[ActorMention, ...]:
    """Tách actor của một việc giao thành các bên nhận việc kèm vai trò.

    Ngoài actor, bên phối hợp ghi trong NỘI DUNG việc ("…, phối hợp với Sở Xây dựng")
    cũng được thêm, nhưng chỉ khi là người/đơn vị trong danh sách tham dự.

    Đầu vào: item - việc giao; registry - danh bạ + danh sách tham dự.
    Đầu ra: tuple ActorMention (rỗng nếu không có actor).
    """

    known_names = list_known_actor_names(registry)
    mentions = list(
        split_actor_mentions(
            item.actor or "",
            protected_names=known_names,
            is_known_entity=lambda text: bool(rank_actor_candidates(text, registry)),
            looks_like_organization=looks_like_organization,
        )
    )
    if not mentions:
        return ()
    taken = {normalize_name_key(mention.text) for mention in mentions}
    roster_names = [person.full_name for person in registry.roster.people] + [
        name for org in registry.roster.organizations for name in (org.name, *org.aliases)
    ]
    for name in find_support_names_in_text(item.text, roster_names):
        if normalize_name_key(name) not in taken:
            mentions.append(ActorMention(name, "support"))
            taken.add(normalize_name_key(name))
    if any(mention.role == "support" for mention in mentions):
        mentions = [ActorMention(m.text, "lead") if m.role == "joint" else m for m in mentions]
    return tuple(mentions)


def _resolve_mention(
    item: ActionItemCandidate, registry: SpeakerRegistry, meeting_turns, mention: ActorMention
) -> ActorAssignee:
    """Định danh MỘT bên nhận việc bằng luật chấm điểm.

    Đầu vào: item - việc giao (cho ngữ cảnh); registry; meeting_turns; mention - cách gọi + vai trò.
    Đầu ra: ActorAssignee (``name=None``, gắn cờ nếu không có ứng viên rõ ràng).
    """

    candidates = _rank_for_item(item, registry, meeting_turns, mention.text)
    if is_clear_choice(candidates):
        top = candidates[0]
        return ActorAssignee(mention.text, mention.role, top.name, top.actor_type, candidates, None,
                             f"Luật chấm điểm: {top.reason}", top.ref_id)
    return ActorAssignee(mention.text, mention.role, None, "unknown", candidates, AMBIGUOUS_FLAG,
                         f"Không có ứng viên rõ ràng cho '{mention.text}'.")


def _summarize_assignees(item: ActionItemCandidate, assignees: Sequence[ActorAssignee]) -> ActionItemV3:
    """Gắn các bên nhận việc vào việc giao và tóm tắt ra các trường actor của cả việc.

    Bên chính là bên đầu tiên sau khi xếp chủ trì -> cùng thực hiện -> phối hợp.
    ``actor`` là tên chuẩn (hoặc cách gọi gốc nếu chưa xác định) của mọi bên, nối bằng ", ".

    Đầu vào: item - việc giao; assignees - các bên đã định danh.
    Đầu ra: ActionItemV3.
    """

    ordered = tuple(sorted(assignees, key=lambda assignee: _ROLE_ORDER[assignee.role]))
    primary = ordered[0]
    return to_action_item_v3(
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
) -> ActionItemV3:
    """Định danh mọi bên nhận việc của một việc giao bằng luật (khi Verifier không chọn).

    Bên nào rõ ràng thì đổi về tên chuẩn của ứng viên đứng đầu; bên nào không rõ thì
    giữ cách gọi gốc, ``actor_type = "unknown"``, giữ ứng viên và gắn cờ.

    Đầu vào: item - việc giao; registry - danh bạ; meeting_turns - lượt nói cả cuộc họp.
    Đầu ra: ActionItemV3.
    """

    mentions = split_item_mentions(item, registry)
    if not mentions:
        return to_action_item_v3(item, actor_type="unknown", actor_flag=MISSING_FLAG,
                                 actor_reason="Agent không nêu được người/đơn vị phụ trách.", assignees=())
    return _summarize_assignees(item, [_resolve_mention(item, registry, meeting_turns, m) for m in mentions])


def _is_mentioned_in_meeting(name: str, meeting_turns: Sequence[SpeakerTurn]) -> bool:
    """Tên (đã chuẩn hoá) có xuất hiện trọn từ trong nguyên văn một lượt nói nào không.

    Đầu vào: name - tên người/đơn vị; meeting_turns - lượt nói cả cuộc họp.
    Đầu ra: bool.
    """

    key = normalize_name_key(name)
    pattern = re.compile(rf"(?<!\w){re.escape(key)}(?!\w)")
    return bool(key) and any(pattern.search(normalize_name_key(turn.text_exact)) for turn in meeting_turns)


def _pick_verified_assignee(
    item: ActionItemCandidate, registry: SpeakerRegistry, meeting_turns, mention: ActorMention, reason: str
) -> ActorAssignee | None:
    """Nhận MỘT bên Verifier nêu nếu tên đó là đúng một người/đơn vị có thật.

    "Có thật": người nói / người hoặc đơn vị trong danh sách tham dự; đơn vị NGOÀI danh
    sách chỉ được nhận khi tên có trong bản ghi (không thì Verifier bịa được tên đơn vị).

    Đầu vào: item; registry; meeting_turns; mention - bên Verifier nêu; reason - lý do Verifier.
    Đầu ra: ActorAssignee, hoặc None nếu tên không khớp chính xác ứng viên nào.
    """

    mention_key = normalize_name_key(mention.text)
    candidates = _rank_for_item(item, registry, meeting_turns, mention.text)
    picked = next((c for c in candidates if normalize_name_key(c.name) == mention_key), None)
    if picked is None:
        return None
    is_unlisted_organization = picked.actor_type == "organization" and picked.ref_id is None
    if is_unlisted_organization and not _is_mentioned_in_meeting(picked.name, meeting_turns):
        return None
    return ActorAssignee(mention.text, mention.role, picked.name, picked.actor_type, candidates, None,
                         f"Verifier: {reason}", picked.ref_id)


def apply_verifier_actor_choice(
    item: ActionItemCandidate,
    choice: dict,
    registry: SpeakerRegistry,
    meeting_turns: Sequence[SpeakerTurn],
    *,
    original_actor: str | None = None,
) -> ActionItemV3:
    """Áp lựa chọn actor của Verifier, chỉ khi MỌI bên Verifier nêu đều là ứng viên có thật.

    - ``revised_actor_type == "unknown"``: mọi bên chưa xác định, giữ ứng viên, gắn cờ.
    - Verifier nêu các bên (đúng tên chuẩn, có thể kèm "(chủ trì)"/"(phối hợp)") KÈM lý
      do, và mọi bên đều khớp đúng một ứng viên: lấy các bên đó.
    - Còn lại (không có lý do, có bên không khớp ứng viên nào, loại không khớp): bỏ cả lựa
      chọn, dùng luật (``resolve_actor``) -- chặn actor bịa lọt vào kết quả.

    Đầu vào:
        item: việc giao sau luật hậu kiểm.
        choice: JSON lượt cuối của Verifier (``revised_actor``, ``revised_actor_type``,
            ``actor_reason``); {} nếu không có.
        registry, meeting_turns: như ``resolve_actor``.
        original_actor: actor lúc vào Verifier (cách gọi gốc của các bên khi "unknown").
    Đầu ra: ActionItemV3.
    """

    reason = (choice.get("actor_reason") or "").strip()
    chosen_type = choice.get("revised_actor_type")
    chosen_actor = (choice.get("revised_actor") or "").strip() or (item.actor or "")
    if chosen_type == "unknown":
        baseline = replace(item, actor=original_actor or item.actor)
        mentions = split_item_mentions(baseline, registry)
        if not mentions:
            return resolve_actor(item, registry, meeting_turns)
        unknown_reason = reason or "Verifier không xác định được người/đơn vị phụ trách."
        assignees = [
            ActorAssignee(m.text, m.role, None, "unknown", _rank_for_item(item, registry, meeting_turns, m.text),
                          AMBIGUOUS_FLAG, unknown_reason)
            for m in mentions
        ]
        return _summarize_assignees(baseline, assignees)
    if reason and chosen_actor:
        mentions = split_item_mentions(replace(item, actor=chosen_actor), registry)
        picked = [_pick_verified_assignee(item, registry, meeting_turns, m, reason) for m in mentions]
        type_matches = len(picked) != 1 or picked[0] is None or chosen_type in (None, picked[0].actor_type)
        if picked and all(picked) and type_matches:
            return _summarize_assignees(item, picked)
    return resolve_actor(item, registry, meeting_turns)


def list_known_actor_names(registry: SpeakerRegistry) -> tuple[str, ...]:
    """Mọi tên được coi là có căn cứ khi kiểm actor: người nói, người và đơn vị tham dự.

    Đầu vào: registry - danh bạ + danh sách tham dự.
    Đầu ra: tuple tên (không trùng, giữ thứ tự).
    """

    names = [
        *registry.names,
        *(person.full_name for person in registry.roster.people),
        *(name for org in registry.roster.organizations for name in (org.name, *org.aliases)),
    ]
    return tuple(dict.fromkeys(names))


__all__ = [
    "AMBIGUOUS_FLAG",
    "CLEAR_MIN_MARGIN",
    "CLEAR_MIN_SCORE",
    "MISSING_FLAG",
    "apply_verifier_actor_choice",
    "is_clear_choice",
    "list_known_actor_names",
    "looks_like_organization",
    "normalize_name_key",
    "rank_actor_candidates",
    "resolve_actor",
    "split_item_mentions",
    "to_action_item_v3",
]
