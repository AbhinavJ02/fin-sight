# FinSight AI

Financial QA system built to measure its own reliability: evaluation, tracing,
failure diagnosis, and counterfactual validation of fixes, on real SEC and FinQA data.

## Status
- [x] Stage 1: FinQA bronze -> silver (Delta), deterministic program executor, label-quality audit
- [x] Stage 2: same load in PySpark for Fabric (notebook + pipeline), parity-tested against Stage 1 — see `docs/fabric-setup.md`
- [ ] Stage 3: evaluation harness + retrieval baselines (BM25, dense, hybrid, rerank); results to a Fabric Warehouse
- [ ] Stage 4: SEC EDGAR + XBRL ingestion via Fabric pipelines (incremental loads)
- [ ] Stage 5: answer pipeline (LLM proposes program, executor computes) + OpenTelemetry traces
- [ ] Stage 6: MCP tools + investigator agent + counterfactual runs
- [ ] Stage 7: Power BI, deployment pipelines, CI quality gates

## Quickstart
```bash
pip install -e ".[dev,spark,local]"   # spark tests need Java 17
./scripts/fetch_finqa.sh data/external/FinQA
python -m finsight.ingestion.finqa --src data/external/FinQA
pytest -q
```
Outputs: `data/lakehouse/silver/finqa_{documents,evidence_units,questions}` (Delta)
and `data/lakehouse/reports/finqa_quality.json`.

See `docs/decisions.md` for what the data actually looks like and why.
