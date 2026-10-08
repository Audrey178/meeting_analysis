import type { MrgGiaoViec, MrgTask } from "../../api/types";
import {
  ASSIGNMENT_STATUS_LABEL,
  PRECISION_LABEL,
  type SelectEvidence,
  allTraceEvidence,
  formatValue,
  traceToEvidence,
} from "../../lib/mrg";
import { TraceButton } from "./TraceButton";

interface MrgAssignmentsProps {
  giaoViec: MrgGiaoViec;
  selectedKey: string | null;
  onSelect: SelectEvidence;
}

const ROLE_LABEL: Record<string, string> = { chair: "chủ trì phiên họp", member: "thành viên", external: "bên ngoài" };

function statusTag(status: string) {
  const strong = status === "confirmed" || status === "self_committed";
  return (
    <span className={`tag ${strong ? "tag-accent" : "tag-outline"}`}>
      {ASSIGNMENT_STATUS_LABEL[status] ?? status}
    </span>
  );
}

function TaskCard({ task, keyPrefix, selectedKey, onSelect }: {
  task: MrgTask;
  keyPrefix: string;
  selectedKey: string | null;
  onSelect: SelectEvidence;
}) {
  const fields: [string, string, string][] = [
    ["assigned_by", "Người giao", task.assigned_by ?? "—"],
    [
      "deadline",
      "Hạn",
      task.deadline_norm
        ? `${task.deadline_norm}${PRECISION_LABEL[task.deadline_precision] ? ` (${PRECISION_LABEL[task.deadline_precision]})` : ""} · “${task.deadline_raw}”`
        : task.deadline_raw
          ? `“${task.deadline_raw}”`
          : "—",
    ],
  ];
  return (
    <div className="flex flex-col gap-1.5 border-t border-divider py-2.5 first:border-t-0">
      <TraceButton
        traceKey={`${keyPrefix}:all`}
        evidence={allTraceEvidence(task.fold_trace)}
        selectedKey={selectedKey}
        onSelect={onSelect}
        className="flex items-baseline gap-2.5 px-2.5 py-1.5"
      >
        <span className="min-w-0 flex-1 text-[14px] leading-snug font-semibold">{task.task || task.task_id}</span>
        <span className="tag tag-neutral">{task.task_role === "lead" ? "chủ trì" : "phối hợp"}</span>
        {statusTag(task.assignment_status)}
      </TraceButton>
      <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-0.5 pl-2.5 text-[12.5px]">
        {fields.map(([field, label, value]) => (
          <div key={field} className="contents">
            <span className="text-neutral-700">{label}</span>
            <TraceButton
              traceKey={`${keyPrefix}:${field}`}
              evidence={traceToEvidence(task.fold_trace[field])}
              selectedKey={selectedKey}
              onSelect={onSelect}
              className="px-1.5"
            >
              {value}
            </TraceButton>
          </div>
        ))}
        {task.co_actors.length > 0 && (
          <>
            <span className="text-neutral-700">Cùng làm</span>
            <span className="px-1.5">
              {task.co_actors.map((actor) => `${actor.person} (${actor.task_role === "lead" ? "chủ trì" : "phối hợp"})`).join(", ")}
            </span>
          </>
        )}
        {task.superseded.length > 0 && (
          <>
            <span className="text-neutral-700">Bị thay thế</span>
            <span className="px-1.5 text-neutral-700">
              {task.superseded.map((item) => `${item.field}: ${formatValue(item.raw)}`).join(" · ")}
            </span>
          </>
        )}
        {task.condition && (
          <>
            <span className="text-neutral-700">Điều kiện</span>
            <span className="px-1.5">{task.condition}</span>
          </>
        )}
        {task.segments.length > 1 && (
          <>
            <span className="text-neutral-700">Xuất hiện ở</span>
            <span className="px-1.5 font-mono text-[11.5px]">{task.segments.join(", ")}</span>
          </>
        )}
      </div>
      {task.warnings.length > 0 && (
        <ul className="m-0 list-none pl-2.5 text-[12px] text-accent-700">
          {task.warnings.map((warning, idx) => (
            <li key={idx}>⚠ {warning}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function MrgAssignments({ giaoViec, selectedKey, onSelect }: MrgAssignmentsProps) {
  const { people, warnings, notes } = giaoViec;
  return (
    <div className="flex flex-col gap-6">
      {people.length === 0 && (
        <p className="text-[13px] text-neutral-700">Không có việc nào được giao (xem mục chưa giao xong bên dưới).</p>
      )}
      {people.map((person, personIdx) => (
        <div key={`${person.person}-${personIdx}`} className="grid grid-cols-[170px_minmax(0,1fr)] gap-4">
          <div>
            <div className="font-heading text-[14px] font-extrabold">{person.person}</div>
            {person.role && <div className="text-[11px] text-neutral-700">{ROLE_LABEL[person.role] ?? person.role}</div>}
          </div>
          <div className="flex flex-col">
            {person.tasks.map((task, taskIdx) => (
              <TaskCard
                key={`${task.task_id}-${taskIdx}`}
                task={task}
                keyPrefix={`gv:${personIdx}:${taskIdx}`}
                selectedKey={selectedKey}
                onSelect={onSelect}
              />
            ))}
            {person.ongoing.map((item, idx) => (
              <TraceButton
                key={`${item.task_id}-ongoing-${idx}`}
                traceKey={`gv:${personIdx}:ongoing:${idx}`}
                evidence={traceToEvidence(item.fold_trace)}
                selectedKey={selectedKey}
                onSelect={onSelect}
                className="flex items-baseline gap-2.5 border-t border-divider px-2.5 py-2 text-[13px]"
              >
                <span className="flex-1">{item.task}</span>
                <span className="tag tag-neutral">đang làm</span>
                {item.progress && <span className="text-[12px] text-neutral-700">{item.progress}</span>}
              </TraceButton>
            ))}
          </div>
        </div>
      ))}

      {warnings.length > 0 && (
        <div>
          <h6 className="mb-2">Chưa giao xong ({warnings.length})</h6>
          <ul className="m-0 flex list-none flex-col gap-1 p-0 text-[13px]">
            {warnings.map((item) => (
              <li key={item.task_id} className="flex gap-2.5">
                <span className="tag tag-outline">{ASSIGNMENT_STATUS_LABEL[item.status] ?? item.status}</span>
                <span>{item.task || item.task_id}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {notes.length > 0 && (
        <div>
          <h6 className="mb-2">Đã hủy ({notes.length})</h6>
          <ul className="m-0 list-none p-0 text-[13px] text-neutral-700">
            {notes.map((item) => (
              <li key={item.task_id}>{item.task || item.task_id}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
