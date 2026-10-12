import { useEffect, useState } from "react";
import { checkHealth } from "./api/client";
import type { AttendeesIn, EvidenceRef, PipelineKind, TasksIn, TranscriptItem, V3Part } from "./api/types";
import { ErrorBanner } from "./components/ErrorBanner";
import { InputScreen } from "./components/InputScreen";
import { NavBar } from "./components/NavBar";
import { ResultView } from "./components/ResultView";
import { RunningScreen } from "./components/RunningScreen";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { useAnalysis } from "./hooks/useAnalysis";
import { useV3Analysis } from "./hooks/useV3Analysis";
import { V3ResultView } from "./components/v3/V3ResultView";
import { selectionBelongsToPart } from "./lib/v3Selection";

interface Transcript {
  meeting_id?: string;
  revision_id?: string;
  items: TranscriptItem[];
}

export default function App() {
  const agentic = useAnalysis();
  const v3 = useV3Analysis();
  const [pipeline, setPipeline] = useState<PipelineKind>("v3");
  const active = pipeline === "v3" ? v3 : agentic;
  const { status } = active;

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
    kind: PipelineKind,
    meetingDate: string,
    chair: string,
    attendees: AttendeesIn | null,
    tasks: TasksIn | null,
  ) {
    setSelected(null);
    setPendingItems(transcript.items);
    setPipeline(kind);
    const base = { meeting_id: transcript.meeting_id, revision_id: transcript.revision_id, items: transcript.items };
    const request = meetingDate ? { ...base, meeting_date: meetingDate } : base;
    if (kind === "v3") {
      const v3Request = {
        ...request,
        ...(chair ? { chair } : {}),
        ...(attendees ? { attendees } : {}),
        ...(tasks ? { tasks } : {}),
      };
      void v3.run(v3Request);
    } else {
      // Bỏ phiên v3 đang lưu để tải lại trang không khôi phục nhầm kết quả v3.
      v3.reset();
      void agentic.run(request);
    }
  }

  function handleReset() {
    setSelected(null);
    setPendingItems(null);
    agentic.reset();
    v3.reset();
  }

  function handleRetry() {
    if (pipeline === "v3" && v3.request) void v3.run(v3.request);
    else if (agentic.request) void agentic.run(agentic.request);
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

  // Pipeline agentic chỉ có turn_id làm bằng chứng (tô cả lượt nói).
  function handleSelectAgentic(key: string, evidenceIds: string[]) {
    handleSelect(key, evidenceIds.map((turn_id) => ({ turn_id, span: null })));
  }

  const meetingId = pipeline === "v3"
    ? (v3.data?.meeting_id ?? v3.request?.meeting_id)
    : (agentic.data?.meeting_id ?? agentic.request?.meeting_id);
  const revisionId = pipeline === "v3"
    ? (v3.data?.revision_id ?? v3.request?.revision_id)
    : (agentic.data?.revision_id ?? agentic.request?.revision_id);
  const turns = pipeline === "v3" ? (v3.data?.turns ?? null) : (agentic.data?.turns ?? null);

  return (
    <div className="flex h-screen flex-col">
      <NavBar
        status={status}
        meetingId={meetingId}
        revisionId={revisionId}
        pipelineLabel={pipeline === "v3" ? "Agentic v3" : "Agentic"}
        apiHealthy={apiHealthy}
        onReset={handleReset}
      />

      <div className="grid min-h-0 flex-1 grid-cols-[480px_minmax(0,1fr)]">
        <TranscriptPanel
          turns={turns}
          items={turns ? null : (pendingItems ?? active.request?.items ?? (status === "idle" ? draftItems : null))}
          selectedEvidence={selected?.evidence ?? null}
        />

        {status === "idle" && <InputScreen onStart={handleStart} onPreview={setDraftItems} />}

        {status === "running" && (
          <RunningScreen elapsedMs={active.elapsedMs} meetingId={active.request?.meeting_id ?? ""} />
        )}

        {status === "error" && (
          <ErrorBanner message={active.error ?? "Lỗi không xác định."} onRetry={handleRetry} onEditInput={handleReset} />
        )}

        {status === "success" && pipeline === "v3" && v3.data && (
          <V3ResultView
            data={v3.data}
            elapsedMs={v3.elapsedMs}
            selectedPointKey={selected?.key ?? null}
            onSelectPoint={handleSelectAgentic}
            reloading={v3.reloading}
            partErrors={v3.partErrors}
            onReloadPart={handleReloadPart}
            onRefreshAll={handleRefreshAll}
          />
        )}
        {status === "success" && pipeline === "agentic" && agentic.data && (
          <ResultView
            data={agentic.data}
            elapsedMs={agentic.elapsedMs}
            selectedPointKey={selected?.key ?? null}
            onSelectPoint={handleSelectAgentic}
          />
        )}
      </div>
    </div>
  );
}
