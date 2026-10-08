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

- **MA-MRG (graph)** — mặc định. Cần ngày họp (chuẩn hóa hạn), chủ trì (tùy chọn) và thành viên
  (tùy chọn). Gọi `POST /meetings/mrg/jobs` rồi poll `GET /meetings/mrg/jobs/{id}` mỗi 1,5 s
  (`hooks/useMrgAnalysis.ts`), nên màn chạy hiện **tiến độ thật** theo stage. Kết quả
  (`components/mrg/`): Giao việc theo người (trạng thái, vai trò, hạn chuẩn hóa + giá trị bị thay
  thế), Kết luận theo trạng thái, Diễn biến theo thread, Thông báo, Cảnh báo, Audit, Raw JSON.
  Bấm một mục / một trường để tô **đúng span** bằng chứng (`fold_trace`) trên transcript; turn bị
  nghi gộp lời nhiều người có nhãn "nghi gộp".
- **Agentic (cũ)** — `POST /meetings/analyze` đồng bộ như trước.

## Design system

Tokens and component classes (`.btn`, `.field`, `.input`, `.tag`, `.table`,
`.hr`, `.grayscale`) are ported from
`_ds/modernist-98b41d50-.../styles.css` into `src/index.css`, registered
under Tailwind v4's `@theme` so they're also real utilities
(`bg-accent`, `text-neutral-700`, `border-divider`, `font-heading`,
`rounded-md` = 0, ...). Modify tokens there, not per-component.

## Known gaps

- The agentic pipeline (`/meetings/analyze`) still has no server-side
  progress (single synchronous request), so its "running" screen shows a
  spinner + elapsed timer. MA-MRG jobs report real per-stage progress.
- No docx export endpoint exists yet, so the design's "Tải .docx" /
  "Export .docx" action isn't wired up here.
