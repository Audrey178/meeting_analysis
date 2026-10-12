import { useEffect, useState } from "react";
import { checkHealth } from "./api/client";
import type { AttendeesIn, EvidenceRef, TasksIn, TranscriptItem, V3Part } from "./api/types";
import { ErrorBanner } from "./components/ErrorBanner";
import { InputScreen } from "./components/InputScreen";
import { NavBar } from "./components/NavBar";
import { RunningScreen } from "./components/RunningScreen";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { useV3Analysis } from "./hooks/useV3Analysis";
import { V3ResultView } from "./components/v3/V3ResultView";
import { selectionBelongsToPart } from "./lib/v3Selection";

interface Transcript {
  meeting_id?: string;
  revision_id?: string;
  items: TranscriptItem[];
}

export default function App() {
  const v3 = useV3Analysis();
  const { status } = v3;

  const [apiHealthy, setApiHealthy] = useState<boolean | null>(null);
  const [selected, setSelected] = useState<{ key: string; evidence: EvidenceRef[] } | null>(null);
  const [pendingItems, setPendingItems] = useState<TranscriptItem[] | null>(null);
  const [draftItems, setDraftItems] = useState<TranscriptItem[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    checkHealth().then((ok) => {
      if (!cancelled) setApiHealthy(ok);
    });
    return () => {
      cancelled = true;
    };
  }, [status]);

  function handleStart(
    transcript: Transcript,
    meetingDate: string,
    chair: string,
    attendees: AttendeesIn | null,
    tasks: TasksIn | null,
  ) {
    setSelected(null);
    setPendingItems(transcript.items);
    void v3.run({
      meeting_id: transcript.meeting_id,
      revision_id: transcript.revision_id,
      items: transcript.items,
      ...(meetingDate ? { meeting_date: meetingDate } : {}),
      ...(chair ? { chair } : {}),
      ...(attendees ? { attendees } : {}),
      ...(tasks ? { tasks } : {}),
    });
  }

  function handleReset() {
    setSelected(null);
    setPendingItems(null);
    v3.reset();
  }

  function handleRetry() {
    if (v3.request) void v3.run(v3.request);
  }

  // Chạy lại một phần v3: các phần khác giữ nguyên, chỉ bỏ chọn nếu mục đang chọn thuộc phần đó.
  function handleReloadPart(part: V3Part) {
    void v3.reloadPart(part).then((applied) => {
      if (applied) setSelected((prev) => (prev && selectionBelongsToPart(part, prev.key) ? null : prev));
    });
  }

  function handleRefreshAll() {
    if (!v3.request) return;
    setSelected(null);
    void v3.run(v3.request, { refresh: true });
  }

  function handleSelect(key: string, evidence: EvidenceRef[]) {
    setSelected((prev) => (prev?.key === key ? null : { key, evidence }));
  }

  // Kết quả chỉ có turn_id làm bằng chứng (tô cả lượt nói).
  function handleSelectTurns(key: string, evidenceIds: string[]) {
    handleSelect(key, evidenceIds.map((turn_id) => ({ turn_id, span: null })));
  }

  const meetingId = v3.data?.meeting_id ?? v3.request?.meeting_id;
  const revisionId = v3.data?.revision_id ?? v3.request?.revision_id;
  const turns = v3.data?.turns ?? null;

  return (
    <div className="flex h-screen flex-col">
      <NavBar
        status={status}
        meetingId={meetingId}
        revisionId={revisionId}
        apiHealthy={apiHealthy}
        onReset={handleReset}
      />

      <div className="grid min-h-0 flex-1 grid-cols-[480px_minmax(0,1fr)]">
        <TranscriptPanel
          turns={turns}
          items={turns ? null : (pendingItems ?? v3.request?.items ?? (status === "idle" ? draftItems : null))}
          selectedEvidence={selected?.evidence ?? null}
        />

        {status === "idle" && <InputScreen onStart={handleStart} onPreview={setDraftItems} />}

        {status === "running" && (
          <RunningScreen elapsedMs={v3.elapsedMs} meetingId={v3.request?.meeting_id ?? ""} />
        )}

        {status === "error" && (
          <ErrorBanner message={v3.error ?? "Lỗi không xác định."} onRetry={handleRetry} onEditInput={handleReset} />
        )}

        {status === "success" && v3.data && (
          <V3ResultView
            data={v3.data}
            elapsedMs={v3.elapsedMs}
            selectedPointKey={selected?.key ?? null}
            onSelectPoint={handleSelectTurns}
            reloading={v3.reloading}
            partErrors={v3.partErrors}
            onReloadPart={handleReloadPart}
            onRefreshAll={handleRefreshAll}
          />
        )}
      </div>
    </div>
  );
}
