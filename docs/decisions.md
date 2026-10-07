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

## D11. In-page BM25 is our own ~40 lines, checked against bm25s
A page has ~30 units (median 30 on dev and test; min 6, max 266), so speed is irrelevant
in-page. Writing BM25 ourselves lets us choose where IDF comes from: the page's own units
(`idf_scope="page"`) or the train-split pages (`"corpus"`, steadier for tiny pages, no
label leakage). Scoring follows bm25s `method="lucene"`; `tests/test_bm25.py` asserts equal
scores on the same tokens. bm25s stays a dev dependency in that reference role; it may
earn a runtime role in the corpus-level setting (D2), which has 86,421 units.

## D12. Retrieval evaluation protocol
- **Metrics** (`finsight/eval/metrics.py`), all from the 1-based ranks of the gold units in a
  full ranking of the page: Recall@k, **AllGold@k** (every gold unit in the top k), MRR,
  NDCG@k (binary), k in 1/3/5/10. AllGold@k is the selection metric (AllGold@5): Stage 5
  builds a program from the retrieved units and needs all of them. About half the questions
  have 2+ gold units (dev 467/883, test 579/1,147), where Recall@k flatters a retriever.
- **Random baseline, exact.** Expected value of every metric under a uniformly random ranking,
  in closed form, tested against brute-force enumeration. Reported next to every number:
  with ~30 candidates, Recall@10 for a random ranking is already 0.387 (dev).
- **Ties.** Broken by a hash of `unit_id`, never page order, so position on the page earns no
  credit. Scores are rounded to 9 decimals before tie-breaking and query terms are summed in
  sorted order. Before that fix, set iteration order (which varies per process) changed the
  last bit of mathematically equal scores and flipped the order of two rows on 1 of 883 dev
  questions (0 of 1,147 test). After the fix, written runs reproduce with 0 mismatches under
  three different `PYTHONHASHSEED` values on both splits.
- **All questions are scored**, including `conflict` labels: D3's trust status is about the
  answer, while retrieval is scored against `gold_inds`. The `label_status` breakdown is
  reported anyway; it shows no consistent pattern across splits (conflict AllGold@5: dev
  0.733, test 0.654; consistent: dev 0.705, test 0.706).
- **Discipline.** Configs are compared on dev only (the CLI refuses `--grid` on test); test
  runs only the chosen config. Results are written only from a clean tree, and each run
  records the git commit and Delta versions of the silver tables. Uncertainty: 1,000-sample
  bootstrap over questions (seed 0); configs are compared with a paired bootstrap.

## D13. BM25 baseline: config chosen on dev, then one test run
Dev grid at commit a9eb084 (`python -m finsight.eval.retrieval --split dev --grid`),
k1=1.2, b=0.75:

| stopwords | IDF | stem | AllGold@5 | Recall@5 | MRR | NDCG@10 |
|---|---|---|---|---|---|---|
| random (exact) | | | 0.108 | 0.196 | 0.200 | 0.204 |
| no | page | no | 0.584 | 0.718 | 0.648 | 0.664 |
| no | corpus | no | 0.651 | 0.770 | 0.723 | 0.725 |
| yes | page | no | 0.701 | 0.819 | 0.727 | 0.749 |
| yes | corpus | no | 0.695 | 0.808 | 0.734 | 0.748 |
| yes | page | yes | 0.704 | 0.818 | 0.728 | 0.750 |
| yes | corpus | yes | 0.692 | 0.805 | 0.733 | 0.745 |

(Stemmed variants without stopwords omitted: AllGold@5 0.576 page, 0.653 corpus, each
within 0.01 of its unstemmed version.)
- Stopword removal is the largest effect. Corpus IDF helps only without stopwords
  (AllGold@5 0.584 -> 0.651); inference: both mainly down-weight common words.
- Against the best on AllGold@5 (page/stopwords/stem), the paired 95% intervals of the other
  three stopword configs all include 0 (e.g. no stemming: -0.003 [-0.016, +0.008]).
- **Rule: among configs dev cannot separate, take the simplest.** Chosen: page IDF,
  stopwords, no stemming. It is the code default, and needs no PyStemmer.

Test, run once at commit 96382bd (run `20261007T162822-0e63b187`, silver tables at version 0):

| metric | BM25 | 95% CI | random |
|---|---|---|---|
| Recall@3 / @5 / @10 | 0.697 / 0.808 / 0.902 | @5: [0.789, 0.826] | 0.118 / 0.197 / 0.389 |
| AllGold@3 / @5 / @10 | 0.554 / 0.694 / 0.830 | @5: [0.668, 0.721] | 0.064 / 0.115 / 0.269 |
| MRR | 0.724 | [0.705, 0.745] | 0.196 |
| NDCG@5 / @10 | 0.697 / 0.734 | @10: [0.720, 0.750] | 0.132 / 0.202 |

AllGold@5 on test by gold-unit count: 1 -> 0.919 (n=568), 2 -> 0.562 (n=454),
3+ -> 0.152 (n=125). By evidence type: text 0.848 (n=283), table 0.718 (n=706),
table+text 0.310 (n=158).

What the misses look like (dev, observed): table rows carry no table title, so a question
naming the table ("proved undeveloped reserves") matches only the caption sentence and the
gold rows rank 20-21; some tables have numbers as headers (`total | 83382: $ 249038`);
some questions need reasoning ("next 36 months" -> rows 2004-2006).
Recommendation, not yet tested: add the table's caption context to row rendering, as its
own experiment after dense retrieval (3b).

## D14. One lakehouse, one schema per layer (supersedes the table-prefix plan)
`lh_finsight` is created with Lakehouse schemas enabled and holds three schemas: `bronze`,
`silver`, `gold`. Tables are addressed as `schema.table` (`bronze.finqa_records`,
`silver.finqa_documents`, `silver.finqa_evidence_units`, `silver.finqa_questions`).
Alternatives considered:
- **Table-name prefixes** in one lakehouse (`silver_finqa_questions`; the original Stage 2
  guide): no namespace or permission boundary between layers; everything sits in `dbo`.
- **One lakehouse per layer**: the strongest isolation, but three items, three SQL
  endpoints, and cross-lakehouse references (shortcuts or three-part names) for every
  layer-to-layer read. More moving parts than a one-person project needs right now.

Why schemas: it matches common enterprise practice, it allows schema-level permissions
later (e.g. consumers read `gold` only), and names read the same in Spark and in the SQL
analytics endpoint. **Schema-enabled is effectively permanent for a lakehouse**, so this is
decided at creation time; changing it means a new lakehouse and reloading the tables.
Consequences:
- The notebook runs `CREATE SCHEMA IF NOT EXISTS` for all three (idempotent); the fallback is
  creating them in the lakehouse explorer.
- The Files area is unchanged: raw JSON still lands in `Files/bronze/finqa/<commit>/`.
- `merge_into` takes the qualified name as is. Verified locally on Spark 3.5.9 + Delta 3.2.1
  (create, then merge, rerun idempotent, table lands in `silver` not `default`); not yet
  verified against Fabric's catalog. The first Fabric run is that check (fabric-setup.md, step 6).
- Stage 3 gold tables go in the `gold` schema. Local paths already mirror the layout
  (`data/lakehouse/silver/finqa_questions`).
