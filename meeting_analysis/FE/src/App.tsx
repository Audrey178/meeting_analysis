import { useEffect, useMemo, useState } from "react";
import { checkHealth } from "./api/client";
import type { EvidenceRef, PipelineKind, TranscriptItem } from "./api/types";
import { ErrorBanner } from "./components/ErrorBanner";
import { InputScreen, type MrgSettings } from "./components/InputScreen";
import { MrgResultView } from "./components/mrg/MrgResultView";
import { MrgRunningScreen } from "./components/mrg/MrgRunningScreen";
import { NavBar } from "./components/NavBar";
import { ResultView } from "./components/ResultView";
import { RunningScreen } from "./components/RunningScreen";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { useAnalysis } from "./hooks/useAnalysis";
import { useMrgAnalysis } from "./hooks/useMrgAnalysis";
import { useV3Analysis } from "./hooks/useV3Analysis";
import { V3ResultView } from "./components/v3/V3ResultView";

interface Transcript {
  meeting_id?: string;
  revision_id?: string;
  items: TranscriptItem[];
}

export default function App() {
  const agentic = useAnalysis();
  const mrg = useMrgAnalysis();
  const v3 = useV3Analysis();
  const [pipeline, setPipeline] = useState<PipelineKind>("mrg");
  const active = pipeline === "mrg" ? mrg : pipeline === "v3" ? v3 : agentic;
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
    settings: MrgSettings | null,
  ) {
    setSelected(null);
    setPendingItems(transcript.items);
    setPipeline(kind);
    const base = { meeting_id: transcript.meeting_id, revision_id: transcript.revision_id, items: transcript.items };
    if (kind === "mrg" && settings) {
      void mrg.run({ ...base, ...settings });
      return;
    }
    const request = meetingDate ? { ...base, meeting_date: meetingDate } : base;
    if (kind === "v3") {
      void v3.run(chair ? { ...request, chair } : request);
    } else {
      void agentic.run(request);
    }
  }

  function handleReset() {
    setSelected(null);
    setPendingItems(null);
    agentic.reset();
    mrg.reset();
    v3.reset();
  }

  function handleRetry() {
    if (pipeline === "mrg" && mrg.request) void mrg.run(mrg.request);
    else if (pipeline === "v3" && v3.request) void v3.run(v3.request);
    else if (agentic.request) void agentic.run(agentic.request);
  }

  function handleSelect(key: string, evidence: EvidenceRef[]) {
    setSelected((prev) => (prev?.key === key ? null : { key, evidence }));
  }

  // Pipeline agentic chỉ có turn_id làm bằng chứng (tô cả lượt nói).
  function handleSelectAgentic(key: string, evidenceIds: string[]) {
    handleSelect(key, evidenceIds.map((turn_id) => ({ turn_id, span: null })));
  }

  const meetingId = pipeline === "mrg"
    ? (mrg.data?.meeting_id ?? mrg.request?.meeting_id)
    : pipeline === "v3"
      ? (v3.data?.meeting_id ?? v3.request?.meeting_id)
      : (agentic.data?.meeting_id ?? agentic.request?.meeting_id);
  const revisionId = pipeline === "mrg"
    ? (mrg.data?.revision_id ?? mrg.request?.revision_id)
    : pipeline === "v3"
      ? (v3.data?.revision_id ?? v3.request?.revision_id)
      : (agentic.data?.revision_id ?? agentic.request?.revision_id);
  const turns = pipeline === "mrg"
    ? (mrg.data?.turns ?? null)
    : pipeline === "v3"
      ? (v3.data?.turns ?? null)
      : (agentic.data?.turns ?? null);
  const segmentTitles = useMemo(
    () => (mrg.data ? Object.fromEntries(mrg.data.segments.map((s) => [s.segment_id, s.title])) : undefined),
    [mrg.data],
  );

  return (
    <div className="flex h-screen flex-col">
      <NavBar
        status={status}
        meetingId={meetingId}
        revisionId={revisionId}
        pipelineLabel={pipeline === "mrg" ? "MA-MRG" : pipeline === "v3" ? "Agentic v3" : "Agentic"}
        apiHealthy={apiHealthy}
        onReset={handleReset}
      />

      <div className="grid min-h-0 flex-1 grid-cols-[480px_minmax(0,1fr)]">
        <TranscriptPanel
          turns={turns}
          items={turns ? null : (pendingItems ?? (status === "idle" ? draftItems : null))}
          selectedEvidence={selected?.evidence ?? null}
          segmentTitles={pipeline === "mrg" ? segmentTitles : undefined}
        />

        {status === "idle" && <InputScreen onStart={handleStart} onPreview={setDraftItems} />}

        {status === "running" &&
          (pipeline === "mrg" ? (
            <MrgRunningScreen job={mrg.job} elapsedMs={mrg.elapsedMs} meetingId={mrg.request?.meeting_id ?? ""} />
          ) : (
            <RunningScreen elapsedMs={active.elapsedMs} meetingId={active.request?.meeting_id ?? ""} />
          ))}

        {status === "error" && (
          <ErrorBanner message={active.error ?? "Lỗi không xác định."} onRetry={handleRetry} onEditInput={handleReset} />
        )}

        {status === "success" && pipeline === "mrg" && mrg.data && (
          <MrgResultView data={mrg.data} elapsedMs={mrg.elapsedMs} selectedKey={selected?.key ?? null} onSelect={handleSelect} />
        )}
        {status === "success" && pipeline === "v3" && v3.data && (
          <V3ResultView
            data={v3.data}
            elapsedMs={v3.elapsedMs}
            selectedPointKey={selected?.key ?? null}
            onSelectPoint={handleSelectAgentic}
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
