# Supplier Contract Review — Backend

FastAPI service for SCM SENSEI's Supplier Contract Review agentic workflow.
Follows the same pattern as the RFP/RFQ backends: stateless computation,
frontend owns state, deployed to Cloud Run via Buildpacks.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET  | `/health` | Health check |
| POST | `/api/contracts/reviews/extract` | Extract text from an uploaded contract (PDF/DOCX/TXT/CSV/XLSX). No LLM. |
| POST | `/api/contracts/reviews/generate` | Run the full clause-by-clause review (Gemini 2.5 Pro), returns output-schema JSON. |
| POST | `/api/contracts/reviews/followup` | Answer a follow-up question about a completed review; may return `revised_redlines` for a clause. |
| POST | `/api/contracts/reviews/export/redlines` | Render a review's redlines to a Word (.docx) attachment. |

`/generate` returns `{"status": "success", "data": <output-schema>}`.

## Agent

`agents/supplier_contract_review/` inherits `BaseRAGAgent` and loads
`system-prompt.md` (the master prompt with the full Supplier Contract Review
Skill embedded). v1 runs with `use_rag=False`: the Skill is the knowledge layer
and reviews always report `review_basis = "standard_positions"` with an honest
`review_basis_note`. No client playbook corpus is connected yet.

Model: `gemini-2.5-pro`.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in PROJECT_ID / FIREBASE_PROJECT_ID / LOCATION
./dev-venv             # serves on http://localhost:8089
```

Requires Google Application Default Credentials for Vertex AI and Firebase
Admin (`gcloud auth application-default login`).

## Deployment

Push to git — Cloud Build + Developer Connect deploy on Buildpacks
(`Procfile` + `.python-version`). Service name:
`sensei-workflow-supplier-contract-backend-git`, region `us-west1`.

Required Cloud Run env vars:

- `PROJECT_ID`
- `FIREBASE_PROJECT_ID`
- `LOCATION` (us-west1)
- `RAG_CORPUS` (optional — unused in v1)
