# Decision log

Each entry: what we observed, what we decided, why.

## D1. FinQA is the benchmark; pinned at commit 0f16e28
- License: MIT (repo LICENSE). HF mirrors list CC-BY-4.0; we use the GitHub source.
- 8,281 answered questions (train 6,251 / dev 883 / test 1,147) over 2,789 report
  pages, 135 tickers, fiscal years 1999-2019. `private_test.json` has questions only
  and is excluded.
- No page appears in more than one split (checked at ingestion; build fails otherwise).

## D2. FinQA is page-level, not corpus-level
Each question ships with exactly one page (pre_text, table, post_text). The original
task retrieves sentences/rows *within* that page. ~23% of test questions mention no
year, and many name no company ("what percent of total recourse debt is current?").
Decision: report two retrieval settings separately and never mix them:
- **In-page**: candidates = units of the gold page (comparable to the FinQA paper).
- **Corpus**: candidates = all pages, question rewritten with ticker + year from
  the filename. The rewrite is a documented benchmark transformation, not a leak.

## D3. Labels carry a measured trust status
Executing every gold program with our executor reproduces FinQA's `exe_ans` on
100% of train/dev/test. Comparing `exe_ans` with the human `answer` text on test:
933 consistent, 86 rounding-only, 81 conflict, 27 non-numeric, 20 boolean.
Decision: score numeric accuracy against `exe_ans`; report headline accuracy on
`consistent + rounding + boolean`, and report `conflict` items separately.
Conflicts are seed material for the DATA_FAILURE category.

## D4. Ambiguous table row labels
Some tables repeat row labels under year sub-headers (e.g. DISH/2014/page_64:
"first quarter" for 2014 and 2013). FinQA's executor takes the last match. We do
the same for fidelity and emit an `ambiguous_row` warning instead of hiding it.

## D5. Percent scale is never silently forgiven when scoring the system
`numbers_match(..., allow_percent_scale=False)` by default. A 100x error is a
DATA_FAILURE, not a pass. (A unit test caught the label classifier accepting
"380" vs 3.8; fixed.)

## D6. Local-first storage, Fabric as deployment target
Silver/Gold are Delta tables written with `deltalake`. The same files load into a
Fabric Lakehouse (OneLake) unchanged, and CI runs without Fabric capacity.

## D7. SEC EDGAR access
Declared User-Agent with contact email (required), <= 10 req/s (we target 5),
cache every response in bronze, prefer data.sec.gov JSON APIs and bulk files over
per-filing HTML crawling.

## D8. Fabric is the primary environment from Stage 2 (revises D6)
Fabric skills are needed for work, so pipelines and notebooks run in Fabric now,
not at the end. Local Spark stays so CI can test without capacity.

## D9. Spark and Python pipelines must agree exactly
The PySpark silver transforms are checked field-by-field against the Stage 1 Python
pipeline. On the full dataset: 0 mismatches across 2,789 documents, 86,421 evidence
units, 8,281 questions. Two engine differences were found and fixed on the way:
Spark `trim()` strips only spaces (Python `strip()` strips all whitespace), and Spark
renders JSON numbers in Java format (`1.0E-5` vs `1e-05`).

## D10. Explicit schemas, quality gates before writes, idempotent loads
- Explicit JSON schema; inference would turn `gold_inds` into a struct with hundreds of fields.
- Quality checks run before any silver write and raise to fail the pipeline.
- Bronze is append-only with `_run_id`; silver uses MERGE on natural keys, so reruns are safe.
- `deltalake` is a local-only extra; the Fabric wheel depends only on pydantic and pyyaml.
