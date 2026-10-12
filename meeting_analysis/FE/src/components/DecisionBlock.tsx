import type { Citation, ContentTopic, DecisionsHeader, DecisionItem } from "../api/types";
import { quotesOf, type TranscriptIndex } from "../lib/citations";
import { topicNumber } from "../lib/format";
import { CitationCount, EmptyState, EvidenceItem, VerificationTag } from "./agentic/primitives";

interface DecisionBlockProps {
  header: DecisionsHeader;
  items: DecisionItem[];
  /** Chủ đề của Diễn biến để nhóm kết luận; rỗng khi document đó chưa có (hiện danh sách phẳng). */
  topics: ContentTopic[];
  transcript: TranscriptIndex;
  selectedKey: string | null;
  onSelect: (key: string, citation: Citation) => void;
}

/** Thông tin biên bản: chỉ hiện trường có giá trị. */
function HeaderCard({ header }: { header: DecisionsHeader }) {
  const attendance =
    header.so_nguoi_tham_gia !== null
      ? header.so_nguoi_co_mat !== null && header.so_nguoi_co_mat !== header.so_nguoi_tham_gia
        ? `có mặt ${header.so_nguoi_co_mat}/${header.so_nguoi_tham_gia}`
        : `${header.so_nguoi_tham_gia} người`
      : "";
  const rows: [string, string][] = [
    ["Ngày họp", header.ngay_hop],
    ["Chủ trì", header.chu_tri],
    ["Thành phần", [attendance, header.thanh_phan].filter(Boolean).join(" · ")],
  ];
  const shown = rows.filter(([, value]) => value);
  if (shown.length === 0) return null;
  return (
    <dl className="m-0 mb-5 grid grid-cols-[110px_minmax(0,1fr)] gap-x-4 gap-y-1.5 bg-surface px-4 py-3 text-[13px]">
      {shown.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="font-heading text-[11px] font-extrabold tracking-[0.06em] text-neutral-700 uppercase">{label}</dt>
          <dd className="m-0 leading-snug">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

// Kết luận cuộc họp, đánh số liên tục cả cuộc họp ("Kết luận 3" giống nhau dù nằm dưới chủ đề nào),
// nhóm theo chủ đề để đọc.
export function DecisionBlock({ header, items, topics, transcript, selectedKey, onSelect }: DecisionBlockProps) {
  const knownTopicIds = new Set(topics.map((topic) => topic.topic_id));
  const sections =
    topics.length === 0
      ? [{ key: "__all", heading: null as string | null, items }]
      : [
          ...topics.map((topic, topicIdx) => ({
            key: topic.topic_id,
            heading: `${topicNumber(topicIdx)} · ${topic.extracted.content.title || "(chưa có tiêu đề)"}`,
            items: items.filter((item) => item.extensions.topic_id === topic.topic_id),
          })),
          {
            key: "__other",
            heading: "Khác",
            items: items.filter((item) => !knownTopicIds.has(item.extensions.topic_id)),
          },
        ].filter((section) => section.items.length > 0);

  return (
    <div>
      <HeaderCard header={header} />
      {items.length === 0 ? (
        <EmptyState>Không có kết luận nào được xác nhận.</EmptyState>
      ) : (
        <div className="flex flex-col gap-5">
          {sections.map((section) => (
            <section key={section.key}>
              {section.heading && <h6 className="mb-1.5 text-neutral-700">{section.heading}</h6>}
              <ol className="m-0 list-none bg-surface p-1.5">
                {section.items.map((item) => {
                  const key = `decisions:${item.extensions.decision_id}`;
                  const verification = item.extensions.verification;
                  return (
                    <li key={key}>
                      <EvidenceItem
                        selected={key === selectedKey}
                        onSelect={() => onSelect(key, { segmentIds: item.segment_ids, turnIds: item.turn_ids })}
                        quotes={quotesOf(transcript, item.segment_ids)}
                        leading={
                          <span className="w-6 flex-none pt-px text-right font-heading text-[13px] font-extrabold text-accent">
                            {item.so_thu_tu}
                          </span>
                        }
                        trailing={<CitationCount count={item.segment_ids.length} />}
                        meta={verification && verification !== "rule" ? <VerificationTag verification={verification} /> : undefined}
                      >
                        {item.noi_dung}
                      </EvidenceItem>
                    </li>
                  );
                })}
              </ol>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
