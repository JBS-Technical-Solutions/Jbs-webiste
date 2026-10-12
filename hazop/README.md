# HAZOP Studio

Upload a P&ID (PDF or image) together with the project **piping specification** and **risk matrix** (Excel, Word,
PDF or image) and get a draft **HAZOP worksheet** — nodes, guide-word deviations, causes, consequences, safeguards, C × L risk
ranking and recommendations — shown as an editable table in the browser and downloadable as **Word (company
template)** or **Excel**.

```
hazop-studio/
├── backend/                 Python analysis engine (FastAPI)
│   ├── app/
│   │   ├── main.py          REST API
│   │   ├── jobs.py          background jobs + progress
│   │   ├── pipeline/
│   │   │   ├── render.py    PDF / image loading
│   │   │   ├── ocr.py       PDF text layer or tiled OCR (RapidOCR + onnxruntime) incl. vertical text
│   │   │   ├── parse.py     tags -> equipment, instruments, lines, valves, off-page connectors
│   │   │   ├── rules.py     HAZOP rule engine (nodes, deviations, safeguards, risk, recommendations)
│   │   │   └── ai.py        optional vision-LLM review (OpenAI / Anthropic / Gemini)
│   │   ├── exporters/       Word (template-based) and Excel writers
│   │   ├── documents.py     piping spec / risk matrix parsers (Excel, Word, PDF, image), optional documents
│   │   ├── knowledge.py     project standards loader
│   │   └── risk.py          risk matrix (default 5 x 5, or the project's uploaded 5 x 5 / 6 x 6 ...)
│   ├── knowledge/           ISA 5.1 letters, API RP 14C codes, line services, piping specs (A9A, E3)
│   ├── models/              PP-OCRv4 ONNX models used by the OCR engine (bundled, works offline)
│   ├── templates/           HAZOP worksheet Word template
│   ├── samples/             PID-1.pdf sample drawing
│   └── scripts/             smoke test and debug helpers
├── frontend/                Next.js 16 web app (React 19, Tailwind 4)
├── deploy/                  Caddyfile, install.sh and update.sh for a Linux server (see DEPLOY.md)
├── docker-compose.yml       production: web app + engine + Caddy (HTTPS)
├── setup.bat                one-time install
└── start.bat                launch engine + web app
```

## Quick start (Windows)

Requirements: **Python 3.14** (3.13 and 3.12 also work; 3.15 is not supported yet by onnxruntime) and
**Node.js 20+**.

```bat
setup.bat      :: first time only - creates backend\.venv with the newest supported Python and installs node modules
start.bat      :: starts the engine on :8000 and the web app on :3000, then opens the browser
```

Manual start:

```bat
cd backend
.venv\Scripts\python -m uvicorn app.main:app --port 8000

cd frontend
npm run dev
```

Open <http://localhost:3000> and on the upload card:

1. Drop the **P&ID** (PDF, PNG, JPG, TIFF).
2. Add the **piping specification** and **risk matrix** (both required). Each can be an Excel workbook (`.xlsx`), a
   Word document (`.docx`, its tables), a PDF or an image (JPG, PNG, TIFF). The file is checked as soon as it is
   chosen. Excel, Word and text PDFs are read exactly; scanned PDFs and images are read with OCR (clear, straight,
   ruled tables work best), so check the summary. Example layouts are available from
   `/api/templates/piping-spec.xlsx` and `/api/templates/risk-matrix.xlsx`.
   * Piping specification: one row per piping class with Piping Specification, Services, ANSI Rating, Material,
     Design Temperature and Design Pressure columns (temperatures and pressures one per line in the cell).
   * Risk matrix: consequence levels (1, 2, 3 ...) down the first column, likelihood levels across the header row
     and Low / Medium / High / Very High in the cells. 5 × 5 and 6 × 6 (any size from 3 to 8) are detected
     automatically; optional *Consequence* and *Likelihood* sheets (or Word tables under those headings) give the
     level names and descriptions. Cell colours are picked up from Excel fills, Word shading or the image.
     Matrices with risk numbers in the cells (e.g. ranks 1–10, or C × L scores) also work: a legend such as
     "1, 2, 3, 4 – Short-term risk reduction required" groups the numbers into bands (ordered red → green), otherwise
     the cell colours decide. Level indices may run either way (e.g. 1 = Catastrophic); they are re-numbered so that
     the highest level is the most severe / most likely.
3. Optionally attach **other documents** (PFD, cause & effect, datasheets ... up to 5). They are listed in the
   worksheet's reference documents and, in AI-assisted mode, sent to the AI review.
4. Choose **HAZOP nodes**: *Automated* (nodes identified from the drawing) or *User-defined* — the drawing is read
   first, then you review the proposed nodes, add / remove / rename them and pick their tags on the drawing before
   the worksheet is generated.

The first OCR run on a scanned sheet takes about a minute; repeat runs of the same drawing are cached.

To put the site online on a Linux server (Docker, HTTPS on your own subdomain) see [DEPLOY.md](DEPLOY.md).

## Using the app

| Tab | What you get |
| --- | --- |
| **HAZOP worksheet** | Node boundary / design intent / design conditions, then the worksheet table (Deviation, Causes, Consequences, CC, Safeguards, Tag #, C, L, Risk, Recommendations). Filter by node, risk band or text. Change **C** or **L** in any row and the risk updates instantly. Click a tag to locate it on the drawing. |
| **P&ID & extracted data** | Zoomable drawing with colour-coded overlays for equipment, instruments, lines, valves and off-page connectors, plus a searchable list of everything that was extracted. |
| **Recommendations** | All actions with the deviations they close, their highest risk, and the study assumptions. |
| **Risk matrix** | Heat map of worksheet causes on the project matrix (5 × 5, 6 × 6 ...); click a cell to see those rows. |

**Download** exports the worksheet as currently shown (including your C / L edits).

## How the analysis works

1. **Read** – PDFs with a text layer are read directly; scanned drawings are rendered at 300 dpi and OCR'd in
   overlapping tiles, with tall labels re-read rotated so vertical line numbers are captured.
2. **Parse** – tokens are decoded with the project standards in `backend/knowledge/`:
   ISA 5.1 instrument letters (letter-over-number bubbles), API RP 14C equipment codes, line designation
   `size-service-spec-number-insulation`, piping specs (rating, material, temperature limits, sour service),
   valve codes (VB/VGL/VC/VN), off-page FROM/TO connectors, design data blocks, set points, fail actions, voting.
3. **Analyse** – the rule engine builds nodes (major equipment, control valve / letdown, relief & flare — or the
   user-defined nodes) and evaluates risk scenarios against each guide word. Safeguards are credited only when they
   appear on the drawing. It checks design pressure against the uploaded piping-class rating, design temperature
   against spec limits, JT cooling after letdown, single relief valves, car-sealed relief paths, missing SIS final
   elements and more, and ranks risk on the uploaded risk matrix.
4. **AI review (optional)** – add an API key to `backend/.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or
   `GEMINI_API_KEY`) to enable *AI-assisted* mode. The drawing, extracted entities, piping specs, risk matrix,
   optional documents and the draft worksheet are sent to the vision model, which returns an improved worksheet in
   the same schema; risk is always recomputed locally on the project matrix. If the call fails, the rule-based
   worksheet is kept.

## Adapting to your project

* **Piping specs and risk matrix** – upload them with each study (see the templates).
* **Services, instrument letters, equipment codes** – edit the JSON files in `backend/knowledge/`.
* **Word layout** – replace `backend/templates/hazop_template.docx` (the first table's two header rows and first
  data row are used as the row prototype).
* **Settings** – `backend/.env` (`RENDER_DPI`, `MAX_UPLOAD_MB`, `CORS_ORIGINS`, AI keys/models);
  `frontend/.env.local` → `NEXT_PUBLIC_API_URL` if the engine is not on `http://localhost:8000`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | status, configured AI providers, samples |
| GET | `/api/templates/{piping-spec\|risk-matrix}.xlsx` | Excel templates |
| POST | `/api/documents/{piping-spec\|risk-matrix}` | multipart `file` → validation summary (or a 400 with the problem) |
| POST | `/api/jobs` | multipart: `file`, `piping_spec`, `risk_matrix`, `optional_docs` (0-5), `mode` (`rules`/`ai`), `provider`, `node_mode` (`auto`/`user`), `study` (JSON) |
| POST | `/api/jobs/sample` | run the bundled sample drawing with the built-in specs and default matrix (testing) |
| GET | `/api/jobs/{id}` | status (`queued`/`running`/`review`/`done`/`error`), stage, progress, proposed nodes, result |
| POST | `/api/jobs/{id}/nodes` | body `{nodes: [{title, tags, design_intent}]}` — continues a `review` job |
| GET | `/api/jobs/{id}/image` | rendered drawing (PNG) |
| POST | `/api/export/{docx\|xlsx}` | body `{worksheet, extraction}` → file |

`python backend/scripts/smoke_test.py [--file drawing.pdf] [--spec spec.xlsx|.docx|.pdf|.png] [--matrix matrix.xlsx|.docx|.pdf|.png] [--node-mode user]`
runs a full upload → analysis → export check against a running engine (the templates are used when no spec / matrix
is given).

> Generated worksheets are a starting point to support a facilitated HAZOP team review, not a substitute for the
> final HAZOP report. Every row should be verified against the full drawing set, cause-and-effect charts and notes.
