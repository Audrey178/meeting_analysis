import type { MrgReport, MrgWarning } from "../../api/types";
import { RULE_LABEL } from "../../lib/mrg";

export function MrgWarnings({ warnings }: { warnings: MrgWarning[] }) {
  if (warnings.length === 0) {
    return <p className="text-[13px] text-neutral-700">Không có cảnh báo.</p>;
  }
  const groups = new Map<string, MrgWarning[]>();
  for (const warning of warnings) {
    groups.set(warning.rule, [...(groups.get(warning.rule) ?? []), warning]);
  }
  return (
    <div className="flex flex-col gap-4">
      {[...groups.entries()].map(([rule, items]) => (
        <div key={rule}>
          <h6 className="mb-1.5 flex items-baseline gap-2">
            <span className="tag tag-accent">{rule}</span>
            <span>{RULE_LABEL[rule] ?? ""}</span>
            <span className="text-neutral-600">({items.length})</span>
          </h6>
          <ul className="m-0 list-none p-0 text-[12.5px]">
            {items.map((item, idx) => (
              <li key={`${item.anomaly_id ?? idx}`} className="border-t border-divider py-1">
                {item.message}
                {item.anomaly_id && <span className="ml-2 font-mono text-[11px] text-neutral-600">{item.anomaly_id}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between border-b border-divider py-1 text-[13px]">
      <span className="text-neutral-700">{label}</span>
      <span className="font-heading font-extrabold">{value}</span>
    </div>
  );
}

const pct = (value: number) => `${(value * 100).toFixed(1)}%`;

// Audit: số liệu từng stage để người dùng thấy hệ thống đã làm gì (SPEC 11.2), không chỉ kết quả cuối.
export function MrgAudit({ report }: { report: MrgReport }) {
  const { stage1, stage2, stage3 } = report;
  return (
    <div className="grid grid-cols-2 gap-x-8 gap-y-6">
      <div>
        <h6 className="mb-2">Stage 1 — trích Act + grounding</h6>
        <Stat label="Mục LLM đề xuất" value={stage1.proposed} />
        <Stat label="Giữ sau grounding" value={stage1.kept} />
        <Stat label="Act trên đồ thị" value={stage1.acts} />
        <Stat label="Tỷ lệ bị loại" value={pct(stage1.drop_rate)} />
        <Stat label="Quote mơ hồ (ambiguous)" value={pct(stage1.ambiguous_rate)} />
        <Stat label="Khớp mờ (fuzzy)" value={pct(stage1.fuzzy_rate)} />
        {stage1.failed_branches.length > 0 && (
          <p className="mt-1 text-[12px] text-accent-700">Nhánh lỗi: {stage1.failed_branches.join(", ")}</p>
        )}
      </div>
      <div>
        <h6 className="mb-2">Kết quả</h6>
        <Stat label="Task" value={report.tasks} />
        <Stat label="Vấn đề (Issue)" value={report.issues} />
        <Stat label="Thread diễn biến" value={report.threads} />
        <Stat label="Vi phạm nhất quán (10.4)" value={report.consistency_violations.length} />
        <Stat label="KB" value={report.kb_version} />
      </div>
      <div className="col-span-2">
        <h6 className="mb-2">
          Stage 2 — trao đổi ({stage2.messages} message: {stage2.accepted} nhận, {stage2.rejected} từ chối,{" "}
          {stage2.conflicts} xung đột)
        </h6>
        <table className="table">
          <thead>
            <tr>
              <th>Vòng</th>
              <th>Owner chạy</th>
              <th>Gửi</th>
              <th>Nhận</th>
              <th>Từ chối</th>
              <th>Xung đột</th>
              <th>Anomaly mới</th>
            </tr>
          </thead>
          <tbody>
            {stage2.rounds.map((round) => (
              <tr key={round.round}>
                <td>{round.round === 0 ? "0 (rule khác role)" : round.round}</td>
                <td>{round.active ?? "—"}</td>
                <td>{round.submitted}</td>
                <td>{round.accepted}</td>
                <td>{round.rejected ?? "—"}</td>
                <td>{round.conflicts ?? "—"}</td>
                <td>{round.new_anomalies ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="col-span-2">
        <h6 className="mb-2">Stage 3 — Reviewer ({stage3.decisions.length} xung đột phân xử)</h6>
        {stage3.decisions.length === 0 ? (
          <p className="text-[13px] text-neutral-600">Không có xung đột.</p>
        ) : (
          <ul className="m-0 list-none p-0 text-[12.5px]">
            {stage3.decisions.map((decision) => (
              <li key={decision.conflict_id} className="border-t border-divider py-1">
                <span className="font-mono">{decision.conflict_id}</span> {decision.kind} · {decision.target} → thắng{" "}
                <b>{decision.winner ?? "—"}</b>
                {decision.margin !== null && ` (cách ${decision.margin.toFixed(3)})`}
                {decision.warning && <span className="text-accent-700"> · {decision.warning}</span>}
              </li>
            ))}
          </ul>
        )}
        {stage3.feedback_round && (
          <p className="mt-2 text-[12.5px]">
            Feedback: {stage3.feedback.length} mục gửi {stage3.feedback_round.owners.length} owner, vòng bổ sung nhận{" "}
            {stage3.feedback_round.accepted} thay đổi.
          </p>
        )}
      </div>
      <div>
        <h6 className="mb-2">Anomaly còn lại</h6>
        {Object.entries(report.anomalies).map(([rule, count]) => (
          <Stat key={rule} label={`${rule} ${RULE_LABEL[rule] ?? ""}`} value={count} />
        ))}
      </div>
      <div>
        <h6 className="mb-2">Phiên bản prompt</h6>
        {Object.entries(report.prompt_versions).map(([role, version]) => (
          <Stat key={role} label={role} value={version} />
        ))}
      </div>
    </div>
  );
}
