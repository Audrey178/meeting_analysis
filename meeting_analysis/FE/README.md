# Meeting Analysis — frontend

React + TypeScript + Tailwind CSS v4 + Vite. Implements the **Inspector**
first-run direction from the Claude Design handoff
(`../First-run experience redesign-handoff/`): the transcript stays pinned
on the left, results render on the right, and clicking a `luận điểm`
highlights the exact turns behind its `evidence_ids` in the transcript.

Wired to the real backend — `POST /meetings/analyze` runs the full
pipeline synchronously and makes real, billed LLM calls.

## Run it

Backend (from `meeting_analysis/`):

```bash
uvicorn --app-dir be main:app
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Dev server proxies `/health` and `/meetings` to `http://localhost:8000`
(see `vite.config.ts`) — no CORS setup needed, no `.env` required. For a
production deploy where the API lives elsewhere, set `VITE_API_BASE_URL`
(see `.env.example`).

## Hai pipeline

Màn nạp transcript cho chọn pipeline:

- **Agentic v3** — mặc định. `POST /v3/meetings/analyze` đồng bộ (`hooks/useV3Analysis.ts`).
  Ngày họp tùy chọn (quy hạn "tuần sau" ra ngày). Có thể nạp kèm danh sách tham dự
  (`*.attendees.json`: `people`, `organizations` với `aliases`/`functions` tùy chọn) để actor của
  việc giao được quy về đúng người hoặc đơn vị. Giao việc hiện nhãn Cá nhân/Đơn vị, vai trò (chủ
  trì/phối hợp), "từ “Đảng ủy ban”" khi actor được quy từ cách gọi khác, và ứng viên kèm điểm khi
  actor còn mơ hồ.
- **Agentic (cũ)** — `POST /meetings/analyze` đồng bộ như trước.

## Design system

Tokens and component classes (`.btn`, `.field`, `.input`, `.tag`, `.table`,
`.hr`, `.grayscale`) are ported from
`_ds/modernist-98b41d50-.../styles.css` into `src/index.css`, registered
under Tailwind v4's `@theme` so they're also real utilities
(`bg-accent`, `text-neutral-700`, `border-divider`, `font-heading`,
`rounded-md` = 0, ...). Modify tokens there, not per-component.

## Known gaps

- Both pipelines (`/meetings/analyze`, `/v3/meetings/analyze`) have no
  server-side progress (single synchronous request), so the "running" screen
  shows a spinner + elapsed timer.
- No docx export endpoint exists yet, so the design's "Tải .docx" /
  "Export .docx" action isn't wired up here.
