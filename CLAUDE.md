# FinSight AI: context for Claude Code

## What this project is
A financial QA system that measures its own reliability: evaluation, tracing, failure
diagnosis (root-cause taxonomy), and counterfactual validation of fixes, on real data
(FinQA benchmark + SEC EDGAR/XBRL). Portfolio project for AI engineer roles.

Two goals, both first-class:
1. Demonstrate AI engineering a hiring team would recognize: RAG, LLM evaluation,
   agents + MCP, observability, experiment tracking, CI quality gates.
2. Learn Microsoft Fabric **data engineering** in depth (Lakehouse, PySpark notebooks,
   Data Factory pipelines, incremental loads, Environments, Git integration, deployment
   pipelines). Power BI, Real-Time Intelligence, Data Activator get a lighter touch.

## Non-negotiable rules
- Never invent, estimate, or round up metrics. Every number in docs or the README comes
  from a run that is reproducible from this repo.
- Never use synthetic financial data. (Controlled fault injection into the *pipeline* is
  allowed and planned, for scoring the root-cause investigator.)
- The LLM never does arithmetic that the deterministic executor (`finsight.calc.program`)
  can do.
- Distinguish observed fact, inference, and recommendation in anything the investigator says.
- Every technology must have a real job in the system; no keyword-driven additions.

## Working agreement
- Build in small stages. Each stage: implement -> run tests -> inspect real outputs ->
  record findings and decisions in `docs/decisions.md` (numbered D-entries with actual
  numbers) -> update README status -> commit.
- Explain non-obvious decisions as you make them. The author must be able to defend every
  design choice in an interview; prefer clarity over cleverness.
- Show diffs and summarize changes before committing. Don't push without being asked.
- The Fabric UI work is done by hand on purpose (it's the learning). Help with code that
  runs in Fabric, write step-by-step guides, and debug errors, but don't try to automate
  the UI steps away.

## Environment
- macOS, zsh. Python 3.11 via pyenv (`.python-version` in repo). Venv at `.venv`.
  Note: pyenv's global default on this machine is 3.9, so always work inside the venv.
- Java 17 (Homebrew `openjdk@17`, `JAVA_HOME` set in `~/.zshrc`); needed for Spark tests.
- Install: `pip install -e ".[dev,spark,local,retrieval]"`
- FinQA pinned at commit `0f16e2867befa6840783e58be38c9efb9229d742`;
  fetch with `./scripts/fetch_finqa.sh data/external/FinQA`.
- Local ingestion: `python -m finsight.ingestion.finqa --src data/external/FinQA`
- Tests: `pytest -q` (27 tests; Spark parity tests take about 45 s).
- Lint: `ruff check src tests`

## Repository map
- `src/finsight/calc/program.py`: deterministic FinQA DSL executor (incl. table ops).
- `src/finsight/ingestion/finqa.py`: local bronze -> silver, label-quality classification.
- `src/finsight/schemas/finqa.py`: Pydantic silver models.
- `src/finsight/spark/finqa_silver.py`: same transforms in PySpark (runs in Fabric).
- `src/finsight/spark/delta_io.py`: idempotent Delta MERGE helper.
- `src/finsight/storage/lakehouse.py`: local Delta I/O (`deltalake`, local-only extra).
- `notebooks/nb_finqa_bronze_to_silver.ipynb`: Fabric notebook (parameter cell, exit value).
- `docs/decisions.md`: decision log D1-D10. Read it before changing data logic.
- `docs/fabric-setup.md`: Stage 2 Fabric guide (capacity, lakehouse, Environment, pipeline).
- `.github/workflows/ci.yml`: lint, tests (incl. Spark), builds the wheel artifact.

## Key facts established so far (see decisions.md for detail)
- FinQA: 8,281 answered questions (train 6,251 / dev 883 / test 1,147), 2,789 pages,
  135 tickers, 1999-2019. MIT license. `private_test` has no answers; excluded.
- FinQA is page-level: report in-page and corpus-level retrieval separately, never mixed.
- Executor reproduces FinQA `exe_ans` on 100% of questions.
- Test-split label status: 933 consistent, 86 rounding, 81 conflict, 27 non-numeric,
  20 boolean. Headline accuracy excludes `conflict`; conflicts seed DATA_FAILURE.
- Percent-scale tolerance is opt-in; a 100x error is a failure, never a pass.
- Spark and Python pipelines agree with 0 mismatches on the full dataset.
- Fabric is the primary environment from Stage 2; local Spark keeps CI capacity-free.
- SEC access: declared User-Agent with contact email, target 5 req/s (limit 10), cache everything.

## Status
- [x] Stage 1: FinQA bronze -> silver locally, executor, label audit
- [x] Stage 2 (code): PySpark pipeline + Fabric notebook + wheel; parity-tested
- [ ] Stage 2 (Fabric, by hand): follow `docs/fabric-setup.md`
- [x] First push to GitHub + green CI run
- [ ] Stage 3: evaluation harness + in-page retrieval baselines (BM25, dense, hybrid,
      cross-encoder rerank); Recall@3/5/10, MRR, NDCG; results to a Fabric Warehouse
- [ ] Stage 4: SEC EDGAR + XBRL ingestion via Fabric pipelines (incremental loads);
      ~20 companies first; XBRL facts as verifiable answers for a held-out SEC question set
- [ ] Stage 5: answer pipeline (LLM proposes program, executor computes) + OpenTelemetry traces
- [ ] Stage 6: MCP tools (FastMCP) + investigator on Microsoft Agent Framework 1.0;
      fault injection for labeled failures; counterfactual reruns
- [ ] Stage 7: Power BI (Direct Lake), Data Activator alerts, deployment pipelines,
      CI quality gates that fail on metric regressions

## Planned stack
Python 3.11, Pydantic, pytest, ruff; Fabric (OneLake, Lakehouse, PySpark notebooks,
Data Factory pipelines, Warehouse/SQL endpoint, MLflow in Data Science, Power BI);
Delta Lake; bm25s; sentence-transformers (BGE) + Azure OpenAI embeddings; FAISS or
LanceDB locally, Azure AI Search as the managed comparison; cross-encoder reranker;
Azure OpenAI primary LLM, Claude as second provider; MCP Python SDK; Microsoft Agent
Framework; OpenTelemetry; FastAPI + Streamlit; GitHub Actions; Docker.
Deliberately excluded: LangChain/LlamaIndex, Terraform, Kubernetes.
