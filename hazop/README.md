# HAZOP Studio

Upload a P&ID (PDF or image) and get a draft **HAZOP worksheet** — nodes, guide-word deviations, causes,
consequences, safeguards, C × L risk ranking and recommendations — shown as an editable table in the browser and
downloadable as **Word (company template)**, **Excel** or **JSON**.

```
hazop-studio/
├── backend/                 Python analysis engine (FastAPI)
│   ├── app/
│   │   ├── main.py          REST API
│   │   ├── jobs.py          background jobs + progress
│   │   ├── pipeline/
│   │   │   ├── render.py    PDF / image loading
│   │   │   ├── ocr.py       PDF text layer or tiled OCR (RapidOCR) incl. vertical text
│   │   │   ├── parse.py     tags -> equipment, instruments, lines, valves, off-page connectors
│   │   │   ├── rules.py     HAZOP rule engine (nodes, deviations, safeguards, risk, recommendations)
│   │   │   └── ai.py        optional vision-LLM review (OpenAI / Anthropic / Gemini)
│   │   ├── exporters/       Word (template-based) and Excel writers
│   │   ├── knowledge.py     project standards loader
│   │   └── risk.py          5 x 5 risk matrix
│   ├── knowledge/           ISA 5.1 letters, API RP 14C codes, line services, piping specs (A9A, E3)
│   ├── templates/           HAZOP worksheet Word template
│   ├── samples/             PID-1.pdf sample drawing
│   └── scripts/             smoke test and debug helpers
├── frontend/                Next.js 16 web app (React 19, Tailwind 4)
├── setup.bat                one-time install
└── start.bat                launch engine + web app
```

## Quick start (Windows)

Requirements: **Python 3.12** (3.13+ is not supported by the OCR engine) and **Node.js 20+**.

```bat
setup.bat      :: first time only - creates backend\.venv and installs node modules
start.bat      :: starts the engine on :8000 and the web app on :3000, then opens the browser
```

Manual start:

```bat
cd backend
.venv\Scripts\python -m uvicorn app.main:app --port 8000

cd frontend
npm run dev
```

Open <http://localhost:3000>, drop a P&ID on the upload card (or click **Try the sample P&ID**), and wait for the
worksheet. The first OCR run on a scanned sheet takes about a minute; repeat runs of the same drawing are cached.

## Using the app

| Tab | What you get |
| --- | --- |
| **HAZOP worksheet** | Node boundary / design intent / design conditions, then the worksheet table (Deviation, Causes, Consequences, CC, Safeguards, Tag #, C, L, Risk, Recommendations). Filter by node, risk band or text. Change **C** or **L** in any row and the risk updates instantly. Click a tag to locate it on the drawing. |
| **P&ID & extracted data** | Zoomable drawing with colour-coded overlays for equipment, instruments, lines, valves and off-page connectors, plus a searchable list of everything that was extracted. |
| **Recommendations** | All actions with the deviations they close, their highest risk, and the study assumptions. |
| **Risk matrix** | 5 × 5 heat map of worksheet causes; click a cell to see those rows. |

**Download** exports the worksheet as currently shown (including your C / L edits).

## How the analysis works

1. **Read** – PDFs with a text layer are read directly; scanned drawings are rendered at 300 dpi and OCR'd in
   overlapping tiles, with tall labels re-read rotated so vertical line numbers are captured.
2. **Parse** – tokens are decoded with the project standards in `backend/knowledge/`:
   ISA 5.1 instrument letters (letter-over-number bubbles), API RP 14C equipment codes, line designation
   `size-service-spec-number-insulation`, piping specs (rating, material, temperature limits, sour service),
   valve codes (VB/VGL/VC/VN), off-page FROM/TO connectors, design data blocks, set points, fail actions, voting.
3. **Analyse** – the rule engine builds nodes (major equipment, control valve / letdown, relief & flare) and applies
   guide words. Safeguards are credited only when they appear on the drawing. It checks design pressure against
   piping-class rating, design temperature against spec limits, JT cooling after letdown, single relief valves,
   car-sealed relief paths, missing SIS final elements and more, and ranks risk on a 5 × 5 matrix.
4. **AI review (optional)** – add an API key to `backend/.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or
   `GEMINI_API_KEY`) to enable *AI-assisted* mode. The drawing, extracted entities, piping specs and the draft
   worksheet are sent to the vision model, which returns an improved worksheet in the same schema; risk is always
   recomputed locally. If the call fails, the rule-based worksheet is kept.

## Adapting to your project

* **Piping specs, services, codes** – edit the JSON files in `backend/knowledge/`.
* **Word layout** – replace `backend/templates/hazop_template.docx` (the first table's two header rows and first
  data row are used as the row prototype).
* **Risk matrix** – `backend/app/risk.py` and `frontend/src/lib/risk.ts`.
* **Settings** – `backend/.env` (`RENDER_DPI`, `MAX_UPLOAD_MB`, `CORS_ORIGINS`, AI keys/models);
  `frontend/.env.local` → `NEXT_PUBLIC_API_URL` if the engine is not on `http://localhost:8000`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | status, configured AI providers, samples |
| POST | `/api/jobs` | multipart: `file`, `mode` (`rules`/`ai`), `provider`, `study` (JSON) |
| POST | `/api/jobs/sample` | run the bundled sample drawing |
| GET | `/api/jobs/{id}` | status, stage, progress, result |
| GET | `/api/jobs/{id}/image` | rendered drawing (PNG) |
| POST | `/api/export/{docx\|xlsx\|json}` | body `{worksheet, extraction}` → file |

`python backend/scripts/smoke_test.py [--file drawing.pdf]` runs a full upload → analysis → export check against a
running engine.

> The generated worksheet is a starting draft for a facilitated HAZOP team review. It does not replace the team's
> judgement, and every row should be verified against the full drawing set, cause-and-effect charts and notes.
