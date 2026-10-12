import { useEffect, useMemo, useState } from "react";
import { checkHealth } from "./api/client";
import type { AttendeesIn, Citation, DocumentKind, TasksIn, TranscriptItem } from "./api/types";
import { ErrorBanner } from "./components/ErrorBanner";
import { InputScreen } from "./components/InputScreen";
import { NavBar } from "./components/NavBar";
import { ResultView } from "./components/ResultView";
import { RunningScreen } from "./components/RunningScreen";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { DOCUMENT_KINDS, useMeetingDocuments } from "./hooks/useMeetingDocuments";
import { buildTranscriptIndex } from "./lib/citations";

interface Transcript {
  meeting_id?: string;
  revision_id?: string;
  items: TranscriptItem[];
}

export default function App() {
  const v3 = useMeetingDocuments();
  const { status } = v3;

  const [apiHealthy, setApiHealthy] = useState<boolean | null>(null);
  // Mục đang chọn; khoá mở đầu bằng tên document chứa mục ("content:", "tasks:", "decisions:").
  const [selected, setSelected] = useState<{ key: string; citation: Citation } | null>(null);
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
    v3.run({
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
    if (v3.request) v3.run(v3.request);
  }

  // Tính lại một document: các document khác giữ nguyên; khoá mục theo vị trí nên bỏ chọn nếu mục
  // đang chọn thuộc document đó (cùng khoá có thể trỏ sang mục khác).
  function handleReload(kind: DocumentKind) {
    void v3.reload(kind).then((applied) => {
      if (applied) setSelected((prev) => (prev?.key.startsWith(`${kind}:`) ? null : prev));
    });
  }

  function handleRefreshAll() {
    if (!v3.request) return;
    setSelected(null);
    v3.run(v3.request, { refreshBase: true });
  }

  function handleSelect(key: string, citation: Citation) {
    setSelected((prev) => (prev?.key === key ? null : { key, citation }));
  }

  const requestItems = v3.request?.items ?? null;
  const transcript = useMemo(() => buildTranscriptIndex(requestItems ?? []), [requestItems]);
  const loaded = DOCUMENT_KINDS.map((kind) => v3.docs[kind].data).find(Boolean);
  const meetingId = loaded?.meeting_id ?? v3.request?.meeting_id;
  const revisionId = v3.request?.revision_id;
  const turns = v3.docs.content.data?.data.turns ?? null;
  const firstError = DOCUMENT_KINDS.map((kind) => v3.docs[kind].error).find(Boolean);

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
          items={pendingItems ?? requestItems ?? (status === "idle" ? draftItems : null)}
          selected={selected?.citation ?? null}
        />

        {status === "idle" && <InputScreen onStart={handleStart} onPreview={setDraftItems} />}

        {status === "running" && (
          <RunningScreen elapsedMs={v3.elapsedMs} meetingId={v3.request?.meeting_id ?? ""} />
        )}

        {status === "error" && (
          <ErrorBanner message={firstError ?? "Lỗi không xác định."} onRetry={handleRetry} onEditInput={handleReset} />
        )}

        {status === "success" && (
          <ResultView
            docs={v3.docs}
            transcript={transcript}
            elapsedMs={v3.elapsedMs}
            selectedKey={selected?.key ?? null}
            onSelect={handleSelect}
            onReload={handleReload}
            onRefreshAll={handleRefreshAll}
          />
        )}
      </div>
    </div>
  );
}
