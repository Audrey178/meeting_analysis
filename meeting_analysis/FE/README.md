# Meeting Analysis — frontend

React + TypeScript + Tailwind CSS v4 + Vite. Implements the **Inspector**
first-run direction from the Claude Design handoff
(`../First-run experience redesign-handoff/`): the transcript stays pinned
on the left, results render on the right, and clicking any result item
highlights the exact transcript lines behind its `segment_ids`.

Wired to the real backend — `POST /v3/meetings/{content,tasks,decisions}` run
the pipeline synchronously and make real, billed LLM calls.

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

Dev server proxies `/health` and `/v3` to `http://localhost:8000`
(see `vite.config.ts`) — no CORS setup needed, no `.env` required. For a
production deploy where the API lives elsewhere, set `VITE_API_BASE_URL`
(see `.env.example`).

## Pipeline

- **Agentic v3** — ba document `POST /v3/meetings/content|tasks|decisions` gọi song song
  (`hooks/useMeetingDocuments.ts`). Backend dùng chung một lần cắt chủ đề + nhãn và cache từng
  document, nên document nào về trước hiện trước. Mỗi tab có nút tính lại riêng document của nó
  (`?refresh=true`, cùng chủ đề + nhãn); hàng thống kê có "Chạy lại toàn bộ" (`refresh_base`).
  Tải lại trang lấy lại từng document từ cache
  (`GET /v3/meetings/analyses/{input_fingerprint}/{document_key}`, phiên lưu ở `sessionStorage`).
  Trích dẫn ở mức dòng transcript (`segment_ids`): transcript tô đúng các dòng được trích trong lượt nói.
  Ngày họp tùy chọn (quy hạn "tuần sau" ra ngày). Có thể nạp kèm danh sách tham dự
  (`*.attendees.json`: `people`, `organizations` với `aliases`/`functions` tùy chọn) để actor của
  việc giao được quy về đúng người hoặc đơn vị. Giao việc hiện nhãn Cá nhân/Đơn vị, vai trò (chủ
  trì/phối hợp), "từ “Đảng ủy ban”" khi actor được quy từ cách gọi khác, và ứng viên kèm điểm khi
  actor còn mơ hồ.

## Design system

Tokens and component classes (`.btn`, `.field`, `.input`, `.tag`, `.table`,
`.hr`, `.grayscale`) are ported from
`_ds/modernist-98b41d50-.../styles.css` into `src/index.css`, registered
under Tailwind v4's `@theme` so they're also real utilities
(`bg-accent`, `text-neutral-700`, `border-divider`, `font-heading`,
`rounded-md` = 0, ...). Modify tokens there, not per-component.

## Known gaps

- Each document request is synchronous with no server-side progress, so the
  "running" screen shows a spinner + elapsed timer until the first document arrives.
- No docx export endpoint exists yet, so the design's "Tải .docx" /
  "Export .docx" action isn't wired up here.
