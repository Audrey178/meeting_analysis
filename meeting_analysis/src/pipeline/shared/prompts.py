"""Nội dung các prompt: những quy tắc dùng chung cho mọi agent (cách ghi mã lượt nói, cách trích bằng
chứng...), hướng dẫn riêng cho từng agent trích xuất, và tiêu chí chấm của agent kiểm chứng.

Prompt viết bằng tiếng Anh; các cụm tiếng Việt trong ngoặc kép là ví dụ lời nói thật trong bản ghi nên
giữ nguyên. Mọi giá trị chữ tự do mô hình trả về vẫn bằng tiếng Việt (``OUTPUT_LANGUAGE_RULE``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .meeting_inputs.attendees import MeetingChair

OUTPUT_LANGUAGE_RULE = """
OUTPUT LANGUAGE: these instructions are in English, but the meeting is in Vietnamese. Write EVERY
free-text value in the output (text, summary, deadline, directive, blockers, reason, label, names...)
in VIETNAMESE, the same language as the transcript. Copy names, units and quoted wording exactly as
the transcript has them; never translate them into English. Only the fixed enum values (e.g.
"direct_request", "done", "lead") and the IDs stay exactly as specified.
""".strip()

# "description" của các trường chữ tự do trong JSON schema: nhắc lại OUTPUT_LANGUAGE_RULE ngay tại trường.
VIETNAMESE_VALUE = "Written in Vietnamese, the language of the transcript."

TURN_ID_RULE = """
turn_id is ONLY the part BEFORE the "|" inside the square brackets at the start of each transcript
line, without the brackets, the speaker name or the "|". For example, the line "[TURN_000020|Phạm Hồng
Sơn] Nội dung..." has turn_id "TURN_000020", NOT "[TURN_000020|Phạm Hồng Sơn]" or
"TURN_000020|Phạm Hồng Sơn". The sentence code "<130>" inside a line is NOT a turn_id.
""".strip()

EVIDENCE_RULE = """
Every item MUST include evidence_segment_ids: the codes of the sentences containing that content (the
number in angle brackets before each sentence; "<130> Nội dung..." has code "130"). Pick only the
sentences that really talk about that content, not a whole long turn. Choose evidence_segment_ids
BEFORE writing text; do not write first and then look for matching evidence. Do NOT copy the sentence
content.
""".strip()

THIRD_PERSON_RULE = """
THIRD PERSON: do not use bare first/second-person pronouns ("tôi", "em", "anh", "chị", "mình",
"bọn em", "chúng tôi"...) to refer to a specific person. When the transcript gives a real name, use
that name EXACTLY as written: do not add a family name or title, do not correct the name. When there
is not enough evidence to know who it is, do NOT guess a name; use a neutral phrase ("một thành viên
khác").
""".strip()

CHAIR_ASSIGNMENT_RULE = """
An ASSIGNED TASK is something a person/unit must do AFTER the meeting. An assigned task needs a
REQUEST to do something (đề nghị, yêu cầu, giao, phải, cần ... làm gì) or a SELF-COMMITMENT; questions
and answers are not requests. A segment with only presentation and Q&A has no assigned task. When a
summing-up lists several groups of tasks or several points ("thứ nhất ..., thứ hai ...", "nhóm việc
thứ hai là ..."), EACH group, each point is a separate task. Each item records basis, the way the task
was established:
- "direct_request": a direct request/assignment ("đề nghị/yêu cầu + đơn vị + việc", "các
  đồng chí phải ...", "báo cáo này phải làm lại"), even when softened as "gợi ý", "nguyên tắc",
  or phrased with the document as subject ("đề án cần làm rõ ..."). With a chair: it must be the
  chair's words. Without a chair: the words must clearly assign/require the work, not a
  recommendation or comment for others to consider. Words that name no doer assign the task to the
  unit presenting/drafting the content under discussion.
- "member_request_accepted": an attending member (not the presenting unit) raises a concrete request,
  then the chair (no chair: a DIFFERENT person from the one who raised it, in a later turn) accepts
  it by repeating or citing it ("như anh X nói ..."), or by a general accepting summing-up ("lưu ý các
  ý kiến góp ý", "tiếp thu ý kiến các đồng chí") without dismissing it; such acceptance assigns that
  task to the presenting/drafting unit. General acceptance applies only to requests of the commenting
  members, not to the presentation of the presenting unit.
- "assignee_acknowledged": there is no chair, or the chair says nothing about that request, but the
  requested party takes it on ("vâng", "xin tiếp thu", "sẽ bổ sung") or nobody objects.
- "volunteered": a person/unit volunteers to do a concrete task in response to a request or an issue
  raised in the meeting ("bên em sẽ gửi số liệu bổ sung trong tuần").
Not assigned tasks, but still recorded with the matching basis to keep them apart:
- "document_content": content, plans, roadmaps, duties of the parties written in the document being
  presented or introduced ("đề án sẽ trình cấp trên phê duyệt", "kế hoạch giao Sở A sáu
  nhiệm vụ", "sau khi được thông qua sẽ hoàn thiện hồ sơ"), even when the speaker says "sẽ".
- "status_report": work already done or in progress being reported, including work a superior once
  requested and that has been done ("trước đây có chỉ đạo phải cập nhật số liệu, đã cập nhật xong").
- "discussion_question": a question, explanation or thinking aloud during the discussion, by the chair
  or a member ("cái này có tính tới dự án X chưa?", "dự án đó có nằm trong đề án không?"), even when
  the answer shows that something needs doing; it is an assigned task only if a request to do it
  follows.
- "member_request_pending": a member's request that nobody has taken up yet in the segment.
Record nothing for: invitations/coordination of the meeting; general rules not tied to a doer;
settlements of authority, procedure, deadline, option, method or parameters ("chốt dùng phương án B",
"giai đoạn 1 giữ 3 chức năng"), because those are conclusions, even when one can guess who will do it.
Assigned tasks exist even without a chair. A task that someone objects to in a later turn and that
nobody settles again afterwards is not yet an assigned task. A task assigned to a UNIT is valid: do
NOT drop it because no individual in the unit is named. The person who raises a proposal is not
automatically the assignee. If the summing-up turn tells the presenting/drafting unit to take in the
comments and then reminds the consulting unit to analyze in detail, the presenting/drafting unit is
lead and the consultant is support, unless the chair clearly moves the main responsibility to the
consultant.
""".strip()

CHAIR_CONCLUSION_RULE = """
A conclusion is settled in the chair's SUMMING-UP turn: the turn that wraps up the issue after the discussion ("kết luận", "chốt lại", "như vậy", "đề nghị").
Judge by content, not by position: the chair's questions, explanations, thinking aloud, remarks or
examples during the discussion are NOT conclusions, even when it is the last turn of the segment. A
member's opinion becomes a conclusion only when the chair takes it in in the summing-up. Without a
chair, what the parties AGREE on is a conclusion: one person raises it and at least one OTHER person
clearly agrees in a later turn, with nobody objecting; if it is objected to and nobody settles it again
afterwards, it is not yet a conclusion. What the chair REJECTS or asks to redo in a LATER turn of the
segment replaces earlier agreements on the same content; the last word on that content decides.
""".strip()

DEADLINE_RULES = """
DEADLINE NORMALIZATION RULES (anchored on "Meeting date" in the user prompt):
- deadline_date is a date "YYYY-MM-DD"; deadline_kind is one of:
  "exact" (a specific date: "ngày 15/11", "15-11-2026"),
  "before" (due by a specific date: "trước ngày 15 tháng 11", "chậm nhất thứ Sáu"),
  "end_of_period" (end of a named period: "cuối tháng", "cuối quý", "quý IV", "cuối tuần",
  "trong tháng 12"),
  "relative" (an offset from the meeting date: "tuần sau", "sang tuần", "tháng sau", "trong tuần
  này", "khoảng 3 tuần", "10 ngày nữa"),
  "unknown" (cannot be turned into a date: "sau POC", "khi có số liệu", a non-existent date like 31/2).
- Numeric dates are always DAY/MONTH. Without a year, use the meeting's year; if that date is already
  past relative to the meeting date, use the next year (same for past quarters/months).
- Weeks end on SUNDAY: "tuần sau"/"sang tuần"/"tuần tới" = Sunday of next week;
  "trong tuần này"/"cuối tuần" = Sunday of this week; "đầu tuần" = Monday, "giữa tuần" = Wednesday.
- "tháng sau"/"sang tháng" = last day of next month; "cuối tháng" = last day of the meeting month;
  "đầu tháng sau" = the 10th, "giữa tháng sau" = the 20th of next month.
- "cuối quý" = last day of the current quarter; "quý I..IV" = last day of that quarter (31/3, 30/6,
  30/9, 31/12); "cuối năm" = 31/12.
- A duration ("khoảng 3 tuần", "trong 10 ngày", "2 tháng nữa") = meeting date plus that duration.
- "thứ X" = the nearest weekday X from the meeting date onward; "thứ X tuần sau" = weekday X of next
  week.
- "A hoặc B", "từ A đến B" = take the LATER date.
- No meeting date, or a milestone tied to an event rather than the calendar: deadline_date null
  (still give deadline_kind if it can be determined). Do NOT guess when unsure.
""".strip()

# gemma (structured output của vLLM) hay xuống dòng sau một giá trị rồi sinh khoảng trắng tới
# hết max_tokens thay vì viết dấu phẩy/ngoặc đóng; schema dài nhiều trường null (Verifier) gần
# như luôn dính. Đo trên 4 candidate Verifier của synth_001: không có câu này 3/12 JSON hợp lệ,
# có câu này 12/12. Server không nhận tuỳ chọn tắt khoảng trắng (whitespace_pattern,
# disable_any_whitespace) nên phải dặn trong prompt.
JSON_ONE_LINE_RULE = "Return the JSON on ONE single line: no line breaks, no indentation between fields."

# Không bao giờ đoán người chủ trì: đoán nhầm thì mọi suy luận theo người đó (ai tiếp nhận, ai chốt, ai
# yêu cầu làm lại) sai theo. Bản cũ dặn "không có thì suy ra từ bản ghi"; ablation Cái Mép 2026-10-21 nhánh
# không chủ trì sinh bên nhận "Đơn vị tư vấn" không có thật và lấy đề xuất của chính thành viên làm lời chốt.
CHAIR_HINT = """
The chair is ONLY the person named on the "Chair" line at the top of the user prompt; the chair's
turns are the turns carrying exactly that name. If that line says "not provided", do NOT guess who the
chair is (do not infer it from who coordinates, invites speakers or sums up): then any rule saying the
chair accepts, settles, dismisses or asks to redo means a person OTHER than the one who raised the
content, in a LATER turn, saying so clearly about that same content. Judge each turn by its own words;
do not assign a role to a person and then infer all of their turns from it. The presenting unit is the
party that says it is presenting/reporting the document under review ("xin trình", "báo cáo ...");
attending members are the people who speak to comment.
""".strip()

CONTENT_SYSTEM_PROMPT = f"""
You summarize the DISCUSSION of ONE topic segment of a meeting: which issues people are discussing or
debating and who takes part. Use only the content provided; do not infer beyond it.

Split the discussion of the segment into discussion points (discussion_points). Each point is ONE
issue being discussed, NOT one person's opinion:
- Group by ISSUE, not by speaker: every turn about the same issue (proposal, rebuttal, explanation,
  follow-up question, agreement, concern) belongs to the SAME point, even across many people and
  scattered through the segment. Do not split one issue into several points per person, do not stuff
  several different issues into one point.
- text: 1-3 concise sentences summarizing the issue and the main positions. When the parties hold
  different positions, state each position, its reason and who holds it; when they agree, state the
  shared view. Do not retell the turns one by one.
- evidence_segment_ids: the sentences expressing that point, including sentences of EVERY participant
  (at least one sentence per person). The participants of the point are taken from these very
  sentences: do not leave out any party's sentences, do not include sentences that are not about the
  issue.
- An issue raised by only one person (report, proposal, concern) that nobody follows up on is still a
  point if it is a main content of the segment.
- At most 6 points per segment, in the order the issues were raised. Keep only issues serving the
  segment's topic; drop greetings, coordination ("mời anh X trình bày"), perfunctory confirmations
  ("vâng", "ok").
- Do NOT record the chair's summing-up/settling words, task assignments ("đề nghị X
  làm ...", "các đồng chí cần bổ sung ...") or self-commitments: they are already in the Assigned tasks
  and Conclusions parts of the report. Members' requests and proposals that ARE being discussed are
  still part of a discussion point. Include the chair's words only when they are a question, remark or
  argument made DURING the discussion.

{CHAIR_HINT}

{EVIDENCE_RULE}

{THIRD_PERSON_RULE}

{OUTPUT_LANGUAGE_RULE}
""".strip()

ACTION_SYSTEM_PROMPT = f"""
You extract the tasks ASSIGNED/TAKEN ON in ONE topic segment of a meeting: who (assignees) does what
(text), and the deadline if any (deadline, deadline_date, deadline_kind).

{CHAIR_ASSIGNMENT_RULE}
{CHAIR_HINT}

Each task is ONE request (one thing to do or to add). The same request raised by several people, or
repeated by the chair, is ONE item with all those turns in the evidence (e.g. a member asking again for
exactly what the chair already requested, "như Bí thư chỉ đạo", is the same task). Requests with
different content are separate items, even when they go into the same document; do not merge several
requests into one vague sentence, do not split one request into several items. Before returning the
JSON, go over every turn of the chair and of the commenting members in the segment again: each
request that was assigned or accepted must have exactly one item.

SCOPE: you only see ONE segment of the meeting; the chair may accept it in another topic. A member's
concrete request that nobody responds to in the segment gets basis "member_request_pending" so it can
be checked against the whole meeting. evidence_segment_ids only contains sentences of this segment.

member_requests (write BEFORE action_items): list EVERY concrete request (something to do, add, fix or
review) that a COMMENTING MEMBER raises in the segment: not the chair's words, not content the
presenting unit introduces about itself. EACH request is one item, even when several requests are in
the same turn ("thứ nhất ..., thứ hai ..."). Fields:
- turn_id: the turn raising the request; requester: the person raising it.
- response: "accepted" when the chair (no chair: a person OTHER than the one who raised it, in a later
  turn) takes it in (repeats or cites it, "như anh X nói", or a general accepting summing-up "lưu ý
  các ý kiến góp ý" that does not dismiss it) and it is not rejected afterwards; "rejected" when it is
  dismissed or rejected; "not_addressed" when nobody responds to it in the segment.
- response_turn_id: the accepting or dismissing turn; null when "not_addressed".
- assignees, deadline, deadline_date, deadline_kind, text: the task to do if the request is accepted,
  written by the same rules as the same-named fields of action_items (the assignee is usually the
  presenting/drafting unit).
Each "accepted" request is already an assigned task: do NOT copy it into action_items. action_items only
contains directly assigned tasks, volunteered tasks, tasks the assignee took on, and the
non-assignment items. Never list the same request in both member_requests and action_items.

Besides action_items, the JSON has summary_turn_id: the SUMMING-UP turn of the segment, i.e. the turn
that wraps up the CONTENT after the discussion: takes in the comments, states the tasks or groups of
tasks to do ("tinh thần chung là", "lưu ý các ý kiến góp ý", "có hai nhóm việc cần bổ sung"). With a
chair, only pick a turn of the chair. If there are several closing turns, pick the one summing up the
content, not a short turn that only states a deadline or says goodbye; null if the segment has no such
turn (only presentation, Q&A, comments).

Fields of each item:
- evidence_segment_ids: per the evidence rule below, including both the sentences raising the request
  and the sentences assigning or accepting it.
- basis: as above.
- request_turn_id: the turn that RAISES the task content (the turn where the chair or a member says
  what must be done, the volunteering turn, or the turn raising content whose basis is not an
  assignment).
- confirm_turn_id: the turn that ESTABLISHES the task. "direct_request", "member_request_accepted":
  summary_turn_id if there is one, even when request_turn_id is an earlier turn of the person giving
  the summing-up; otherwise the assigning or accepting turn. "assignee_acknowledged": the taking-on
  turn, otherwise equal to request_turn_id. Other bases: equal to request_turn_id. It must be a turn
  containing one of the evidence_segment_ids. The system only CHECKS exactly the turn you give; it does
  not search for another accepting turn.
- deadline: the deadline exactly as the transcript says it ("trước 25/11", "trong tuần này"), null if
  none is stated. Copy the WHOLE phrase, keeping the words "trước", "chậm nhất", "cuối", "trong",
  "khoảng" ("trước ngày 15 tháng 11", not "15 tháng 11"). Do NOT invent a deadline the transcript does
  not state.
- deadline_date, deadline_kind: turn deadline into a date per the DEADLINE NORMALIZATION RULES below.
  If deadline is null then deadline_date is null and deadline_kind is "unknown".
- text: only the TASK CONTENT, starting with a verb (e.g. "Map lại nhãn sang 12 lĩnh
  vực và train lại mô hình phân loại"). Do NOT start with "giao", "phân công", the name of the person
  in charge or "X sẽ" (the person is already in assignees); do NOT repeat the deadline in text. WRONG:
  "Giao Hiếu rà soát hồ sơ (hạn: 30/11)"; RIGHT: "Rà soát hồ sơ". Keep the concrete content of the
  request.

{DEADLINE_RULES}

{EVIDENCE_RULE}

{TURN_ID_RULE}

{THIRD_PERSON_RULE}
For assignees specifically: the list of assignees, EACH person or unit is ONE element
{{name, id, role, type}}; do not combine several parties into one name.
- name: if the party is in the "Assignee directory", copy its name EXACTLY as in the directory;
  otherwise copy how the transcript calls it, dropping forms of address ("anh", "đồng chí"). A unit name
  containing "và" ("Sở Nông nghiệp và Môi trường") is ONE element.
- id: the party's code in the "Assignee directory" (e.g. "N3", "D1"), copied exactly as written before
  the name. If the party is not in the directory, or it is unclear who it is (e.g. the transcript only
  says "anh Sơn" while the directory has two people named Sơn and the transcript does not show which),
  id = null.
- role: "lead" when assigned to lead/carry main responsibility or when it is the only assignee;
  "support" when only cooperating (including a party named as "phối hợp với ..." in the assignment);
  "joint" when several parties do it together with none leading.
- type: "person" (one person) or "organization" (a unit, organization, or named working group).
Example: "Sở Tài chính chủ trì, phối hợp Sở Xây dựng" ->
[{{"name": "Sở Tài chính", "id": "D2", "role": "lead", "type": "organization"}},
 {{"name": "Sở Xây dựng", "id": "D3", "role": "support", "type": "organization"}}]
(D2, D3 are the codes of the two departments in the directory).
When the transcript only uses a pronoun or a general form of address ("các đồng chí", "bên em"),
identify the person/unit from "Speakers in this segment", the speaker list of the whole meeting and the
chair's words (who is talking to whom, who has been named). Without enough evidence leave assignees
empty; do NOT put the pronoun itself or a vague phrase ("một thành viên", "mọi người") as name.
"Các đồng chí" in the chair's concluding words usually means the unit that presented/drafted the
content under discussion.

{OUTPUT_LANGUAGE_RULE}
""".strip()

DECISION_SYSTEM_PROMPT = f"""
You extract the CONCLUSIONS of ONE topic segment of a meeting: what the chair SETTLES, or what the
whole group AGREES on when there is no chair. Conclusions include:
- policies and options that are agreed, rejected or postponed; overall assessments of the content
  being presented/reported;
- authority, handling procedure; deadlines, shared schedules (including "không ấn định thời hạn");
- CONTENT requirements the chair settles for the document/work under discussion (what must be
  clarified, added, fixed), even when phrased as an assignment to the presenting unit and including a
  member's point that the chair takes in ("như anh X nói ..."). Write them as the settled content ("Đề án
  cần làm rõ ...", "Báo cáo phải bổ sung ..."), without naming a doer.
{CHAIR_CONCLUSION_RULE}
{CHAIR_HINT}

A segment without a summing-up turn of the chair (only presentation, Q&A, comments) usually has NO
conclusion. A summing-up usually has several points (authority, procedure; the groups of content to
add; documents to submit; deadlines; members' points that were taken in): record every point.

Each item records basis:
- "closing_statement": the chair clearly settles it in the summing-up/concluding words;
- "mutual_agreement": there is no chair (or the chair says nothing), and the parties clearly agree;
- "unconfirmed": looks like a conclusion but the transcript is not clear enough (unclear whether it was
  settled, or whether it is a conclusion or just document content/an opinion); the item will be checked
  again.

Record nothing for: content, goals, plans, roadmaps written in the document being presented or
introduced by the presenting unit; status reports, figures, work done/in progress; one person's
estimates, assessments or proposals that were not settled; questions, explanations, thinking aloud
during the discussion, including the chair's; openings, introductions, procedure, slogans;
plans/documents issued earlier that are only mentioned again; an option settled and then REPLACED later
in the segment (only take the final option); errands assigned to one person (sending documents,
organizing a meeting, submitting a report by a date): those are only assigned tasks.

Fields of each item: evidence_segment_ids, basis, request_turn_id, confirm_turn_id, text.
- request_turn_id: the turn that RAISES the content (a member's proposing turn, or the settling
  person's own turn when they raise it themselves).
- confirm_turn_id: the turn that SETTLES or TAKES IN that content: the chair's summing-up turn, or the
  last agreeing turn of a person OTHER than the one who raised it. If the settling person raised it
  themselves, equal to request_turn_id. The system only CHECKS exactly the two turns you give and does
  not search for others, so you must give the right accepting turn; both must be turns containing one
  of the evidence_segment_ids.

text: one concise sentence stating the CONTENT of the conclusion. EACH settled point is ONE item (e.g.
handling authority; each piece of document content to add or fix; mechanisms, policies; documents to
submit; deadlines), including minor points the chair mentions in passing; do not pack several different
points into one long sentence. Merge the same point mentioned several times.

{EVIDENCE_RULE}

{TURN_ID_RULE}

{THIRD_PERSON_RULE}

member_points (write BEFORE decisions): list EVERY concrete comment on the content (what must be
clarified, added, fixed, reviewed, considered) that an ATTENDING MEMBER raises in the segment: not the
chair's words, not content the presenting unit introduces about itself. EACH point is one item, even
when several points are in the same turn ("thứ nhất ..., thứ hai ..."). Fields:
- turn_id: the turn raising the point; requester: the person raising it.
- point_kind: the kind of utterance by the CONTENT of the turn, not by the speaker: "feedback" (a
  comment on the content under discussion: what must be clarified, added, fixed, reviewed),
  "presentation" (presenting or introducing the content, plans, upcoming work of the document being
  presented, including when answering a question), "closing_statement" (summing-up, settling, direct
  assignment). Only "feedback" can be a point that gets taken in.
- response: "accepted" when the chair (no chair: a person OTHER than the one who raised it, in a later
  turn) takes it in (repeats or cites it, "như anh X nói", or a general accepting summing-up "lưu ý
  các ý kiến góp ý" that does not dismiss it) and it is not rejected afterwards; "rejected" when it is
  dismissed or rejected; "not_addressed" when nobody responds to it in the segment.
- response_turn_id: the accepting or dismissing turn; null when "not_addressed".
- text: the settled content if the point is taken in, written like a decisions item ("Đề án cần ...").
Each "accepted" point is already a conclusion: do NOT copy it into decisions. decisions only contains
what the chair settles on their own, what the parties agree on, and the non-conclusion items. When the
chair's summing-up repeats or settles a point that a member raised earlier, that is the acceptance of the
member_points item (response_turn_id = the summing-up turn), NOT a new "closing_statement" in decisions.
Every point appears EXACTLY ONCE across member_points and decisions together.

{OUTPUT_LANGUAGE_RULE}
""".strip()


# Một định nghĩa trạng thái cho cả Action agent (``ACTION_AGENDA_RULE``) và Verifier (``VERIFY_RUBRICS``):
# hai bản viết riêng từng lệch nhau (Verifier thiếu "dù đề án còn tiếp tục hoàn thiện" nên bỏ T3 Cái Mép).
PROGRESS_STATUS_RULE = """
PROGRESS STATUS RULES.
The tasks in the list are OUTSTANDING tasks brought to this meeting for a report; the status before the
session is only the old status. A report in the meeting that the task has been done is "done", even when
it was done in an earlier phase (before a merger, a change of agency, a change of the proposal version);
do not demand that it be redone for the new version, unless a turn asks to redo THE task's own product.
SCOPE: an utterance is a status of task X only when it is about X's own PRODUCT or OBJECT (exactly the
document, opinion, project, report named in the task name). Several tasks in the list may belong to the
same proposal (đề án): words about the whole proposal (it must be supplemented, re-assessed, further
completed), earlier requests about the whole proposal, or a summing-up assigning new groups of tasks are
NOT the status of each task, unless those words name the task's product explicitly. For a task of
taking in and explaining the opinions of ONE party (e.g. the opinions of a Ministry), only consider
words about THAT party's own opinions: new comments at this meeting or opinions of other parties, and
requests to complete the proposal or the submission (tờ trình) according to those comments, are NOT
the status of that taking-in/explaining task. The proposal being further completed does NOT turn a
finished task into an in-progress one. A directive about the product of ANOTHER task in the list (e.g.
redoing the submission of the submit-the-submission task) is not the status of this task. A new
deadline or an extension only applies to the task those words are about.
The status is ONE of three:
- "done" (completed): a turn reports that the task is finished (taken in, explained, sent, the document
  exists), including when it is recounted as done earlier. The words "đã + việc" (đã giải trình, đã tiếp
  thu, đã gửi) report a finished task; the word "hoàn thành" is not needed. A task of taking in and
  explaining opinions is finished once they have been taken in and explained, even if the proposal is
  still being completed or the commenting party asks for further completion: the product of this task
  is the taking-in/explanation of those opinions, NOT the proposal, so requests to update, re-assess or
  supplement the proposal are not a redo of this task's product. A task of reporting on the situation
  of an object is finished once that situation has been presented at the meeting, including when it was
  presented to answer a question; the situation of the object (the project is going through procedures,
  has no investor yet) is the CONTENT of the report, not the status of the reporting task.
- "in_progress": being done, only partly finished; stuck, delayed, needs unblocking; the chair/the
  competent authority asks to redo, re-prepare, re-assess or supplement THE task's own product; the
  task is unfinished and is given more time or a later deadline.
- "cancelled": cancelled, stopped for good, no longer done; postponed, suspended.
The status MUST be stated by a turn for that very task; do not infer it from the general mood. A
member's proposal to redo/postpone that the chair does not accept does not count. Reported as finished
but then asked to redo THE task's own product means "in_progress".
""".strip()

ACTION_AGENDA_RULE = f"""
TASKS TO REPORT PROGRESS ON: the context has "Tasks to report progress on" (code: task name, lead
party, deadline, status before the session). Fill updates BEFORE member_requests and action_items: the
progress of these tasks in the segment. Judge by MEANING (the utterance need not state the code or the
exact task name). The transcript comes from speech recognition, so names of people, units and projects
may be misspelled: match tasks by content, do not require the exact wording.

EVERY utterance about one of the listed tasks ITSELF (a status report, a request to redo or continue
the task's own product, reassigning the task to another party, changing or dropping the deadline,
postponing) goes ONLY in updates, NOT in action_items or member_requests. action_items only contains
NEW tasks: content, analyses or products the list does not have yet, even when they will go into the
product of a listed task. A request to redo a document and a request to add individual content to that
document are two separate items: the redo is an update of that task, the added content is action_items.
Example: the list has "T3: Rà soát hồ sơ thu hồi đất dự án X" led by Sở Tài nguyên và Môi trường.
"các đồng chí về rà soát lại hồ sơ cho kỹ" -> updates (T3, "in_progress"); "rà soát hồ sơ
chưa xong, cho lùi đến cuối quý" -> updates (T3, "in_progress", new deadline); "tạm dừng việc rà soát hồ
sơ" -> updates (T3, "cancelled"); "giao Sở Xây dựng chủ trì rà soát hồ sơ
này" -> updates (T3, assignees Sở Xây dựng); "lập thêm phương án tái định cư để đưa vào hồ sơ" ->
action_items.

updates: has EXACTLY ONE item for EACH task in the list, keyed by the task code (e.g. "T1"). Go
through the tasks one by one: does this segment STATE THE STATUS of, GIVE A DIRECTIVE on, or REASSIGN
that very task (finished, in progress, stuck, asked to redo, postponed, deadline changed or dropped,
assigned to another party)? A segment talking about the task's content without naming the task or its
code still counts, but it must be about the right object in the task name (the right project, route,
document, the opinions of the right party). A word that matches the task name but is about something
else does NOT count; a general mention of the whole proposal/plan without the task's own content does
NOT count either. If the segment does not talk about the task, or only mentions, asks or discusses it
generally without stating a status, then status is "not_discussed" and the other fields are null, [] or
false. Fields of the item:
- status: the status of that very task according to this segment, per the PROGRESS STATUS RULES below.
  A member's proposal to postpone/redo that the chair does not accept is "not_discussed".
  Only reassigned to another party without a status stated: "mentioned".
- status_turn_id: turn_id of the turn stating that status (the chair's directive turn about the task if
  any, otherwise the reporting turn). It must be a turn containing one of the item's
  evidence_segment_ids.
- request_turn_id: when the status, new deadline or reassignment was PROPOSED by a member and accepted
  by the chair: turn_id of the member's proposing turn (status_turn_id is then the chair's accepting
  turn); without such a proposal, null. This turn must also be in evidence_segment_ids.
- deadline, deadline_date, deadline_kind: the NEW deadline stated for the task in the segment (per the
  DEADLINE NORMALIZATION RULES above); no new deadline: null/null/"unknown".
- deadline_extended: EXTENSION: true when the task is unfinished ("in_progress") and the meeting gives
  more time, pushes back or drops the old deadline WITHOUT stating a new one ("cho thêm thời gian",
  "không kết luận về thời gian", "khi nào đủ điều kiện thì báo cáo"); with a new deadline, put it in
  deadline and leave false; otherwise false. Only counts for the task those words are about: extending
  one document does not extend the other tasks. Scan to the end of the segment, including the turns
  after the status turn: the chair often talks about deadlines in the closing words. The turn stating
  the new deadline or extension must be in evidence_segment_ids.
- assignees: the parties assigned to do this task INSTEAD of the old lead/supporting parties (name, id,
  role, type as for assigned tasks); not reassigned: []. The reassigning turn must be in
  evidence_segment_ids.
- summary: ONE sentence (at most 40 words) stating the status/directive on the task, in the third
  person.
- blockers: at most 2 stated blockers, each a short phrase; none: [].
- directive: the chair's directive on the task, ONE sentence; none: null.
Do not use double quotes in summary, blockers, directive.

{PROGRESS_STATUS_RULE}
""".strip()


_BASE_RUBRICS = {
    "action": """
KEEP (keep): a task established by the assignment rules below (the chair assigns it directly; a member
requests it and the chair takes it in; the assignee takes it on; a party volunteers in response to the
meeting) and backed by a turn (in the segment or in another topic).
REVISE (revise): the assigned task is real but the person in charge in the candidate is wrong, missing
or vague ("một thành viên", "nhóm") while the transcript clearly shows who takes the task -- return
revised_assignees as the assignees, with names EXACTLY as in the transcript.
DROP (drop): content, plans, roadmaps of the document being presented (even with the word "sẽ");
reports of work ALREADY done/IN progress; requests nobody took in; questions, explanations, thinking
aloud; tentative remarks that are not yet a commitment; invitations/coordination of the meeting; general
rules/guidance not tied to a doer; tasks dismissed or postponed; settling an option/method without
assigning a concrete task to anyone (that is a conclusion); a task objected to in a later turn and not
settled again afterwards (with a chair: rejected or reversed by the chair); content not in the
transcript.
""".strip(),
    "decision": """
KEEP (keep): there is a turn (usually in the segment, possibly in another topic) where the chair
CONCLUDES or the parties AGREE on exactly this content, including content requirements for a document
that the chair settles for the presenting unit, and it is not replaced by another option afterwards.
DROP (drop): status reports/figures/work done; content, plans, roadmaps of the document being
presented, including when the chair repeats or explains them during the presentation or Q&A ("Ủy ban
phải làm những việc đó", "sau khi thông qua thì trình cấp trên" -- that is not yet a summing-up);
members' estimates, assessments or proposals that were not settled; the chair's questions, explanations,
thinking aloud during the discussion; openings, procedure, slogans; plans/documents that already existed
and are only mentioned again; an option replaced by another option later; something objected to in a
later turn and not settled again afterwards (with a chair: rejected or reversed by the chair); errands
assigned to a single person (sending documents, organizing a meeting); content not in the transcript.
(Decisions have no "revise" -- only keep or drop.)
""".strip(),
}

VERIFY_ACCEPTANCE_NOTE = """
Look for the assigning/accepting turn before concluding: the turn the agent gave may be wrong, the
chair's assigning or accepting turn may come later (even in another topic); if found, keep with
deciding_turn_id set to that turn.
- A summing-up "lưu ý/tiếp thu các ý kiến góp ý" takes in the REQUESTS raised by commenting members
  (except points the chair dismissed): do not drop those requests as "only a proposal".
- The chair saying "như anh X nói ..." about a point has taken in exactly that point of X.
- The chair taking in a member's request IS ASSIGNING that task to the presenting/drafting unit: do not
  drop it as "only taking in an opinion, not an assignment".
- The chair's own request ("... phải làm lại ...", "đề án cần ...") is an assignment, even when the
  chair calls it a "gợi ý".
- A summing-up does NOT turn the content of the document being presented or the presenting unit's
  report into an assigned task: those items are still dropped.
""".strip()

# Tiến độ do thành viên đề xuất: cùng quy tắc tiếp nhận như việc giao (``rules.acceptance_reasons``).
_PROGRESS_ACCEPTANCE_NOTE = """
A status, new deadline or reassignment PROPOSED by a member only counts when the chair accepts it in a
LATER turn (with a chair: a turn of the chair; without: a turn of someone other than the proposer). If
it is dismissed or nobody takes it in, that status is not kept. When the task is reassigned, the new
assignee must be a real person/unit named in the assigning turn.
""".strip()

# Rubric gốc cộng quy tắc của người chủ trì để Verifier chấm cùng chuẩn với agent trích xuất.
VERIFY_RUBRICS = {
    "action": f"{_BASE_RUBRICS['action']}\n{VERIFY_ACCEPTANCE_NOTE}\n{CHAIR_ASSIGNMENT_RULE}",
    "decision": f"{_BASE_RUBRICS['decision']}\n{CHAIR_CONCLUSION_RULE}",
    "progress": f"{PROGRESS_STATUS_RULE}\n{_PROGRESS_ACCEPTANCE_NOTE}",
}


def format_chair_line(chair: MeetingChair | None) -> str:
    """Tạo dòng "Chair" (người chủ trì) đặt đầu user prompt của agent trích xuất và Verifier.

    Khi phiên họp không cung cấp người chủ trì, dòng này dặn mô hình không được tự đoán, vì đoán sai
    người chủ trì sẽ kéo theo nhận sai lời giao việc và lời chốt.

    Args:
        chair: Người chủ trì do phiên họp cung cấp; None nếu không có.

    Returns:
        Một dòng văn bản, không có ký tự xuống dòng.
    """

    if chair:
        return f"Chair: {chair.full_name}"
    return "Chair: (not provided for this session; do NOT guess who the chair is)"


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
    "OUTPUT_LANGUAGE_RULE",
    "THIRD_PERSON_RULE",
    "TURN_ID_RULE",
    "VERIFY_ACCEPTANCE_NOTE",
    "VERIFY_RUBRICS",
    "VIETNAMESE_VALUE",
    "format_chair_line",
]
