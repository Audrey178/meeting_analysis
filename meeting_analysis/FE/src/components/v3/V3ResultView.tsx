import type { AnalyzeResponse, AnalyzeV3Result } from "../../api/types";
import { ResultView } from "../ResultView";
import { TaskProgressBlock } from "./TaskProgressBlock";
import { VerifierRecordsBlock } from "./VerifierRecordsBlock";

interface V3ResultViewProps {
  data: AnalyzeV3Result;
  elapsedMs: number;
  selectedPointKey: string | null;
  onSelectPoint: (key: string, evidenceIds: string[]) => void;
}

const AGENT_LABEL: Record<string, string> = { action_agent: "Giao việc", decision_agent: "Kết luận" };

// Kết quả v3 dùng lại ResultView của v1 (cùng ba phần output); tab Kiểm chứng đổi sang
// bản ghi Verifier, thêm tab Tiến độ khi request có danh sách việc cần báo cáo, và ghi
// chú các agent bị Planner bỏ qua.
export function V3ResultView({ data, elapsedMs, selectedPointKey, onSelectPoint }: V3ResultViewProps) {
  const asV1: AnalyzeResponse = { ...data, debate_records: [] };
  const records = data.verification_records;
  const kept = records.filter((record) => record.verdict === "keep" || record.verdict === "revise" || record.verdict === "unresolved").length;
  const skipped = data.skipped_agents;
  const progress = data.task_progress ?? [];

  const notice =
    skipped.length > 0 ? (
      <>
        Planner bỏ qua {skipped.length} lời gọi agent ở chủ đề không có từ giao/chốt việc:{" "}
        {skipped.map((item) => `${item.segment_id} (${AGENT_LABEL[item.agent] ?? item.agent})`).join(", ")}.
      </>
    ) : null;

  return (
    <ResultView
      data={asV1}
      elapsedMs={elapsedMs}
      selectedPointKey={selectedPointKey}
      onSelectPoint={onSelectPoint}
      notice={notice}
      extraTab={
        progress.length > 0
          ? {
              label: `Tiến độ (${progress.length})`,
              render: ({ topicIndexById }) => (
                <TaskProgressBlock
                  items={progress}
                  topicIndexById={topicIndexById}
                  selectedPointKey={selectedPointKey}
                  onSelectPoint={onSelectPoint}
                />
              ),
            }
          : undefined
      }
      verification={{
        count: records.length,
        kept,
        statLabel: "giữ sau Verifier",
        render: ({ topicIndexById }) => (
          <VerifierRecordsBlock
            records={records}
            topicIndexById={topicIndexById}
            selectedPointKey={selectedPointKey}
            onSelectPoint={onSelectPoint}
          />
        ),
      }}
    />
  );
}
