# Stage 2: running FinQA ingestion in Microsoft Fabric

Goal: the same bronze -> silver load that passes locally, running in Fabric as a
parameterized pipeline. Each step lists the Fabric concept it teaches.
Fabric's UI changes often; if a label below differs, the concept is what matters.

## 1. Capacity and workspace
- Start a Fabric trial (or a small pay-as-you-go F-SKU you pause when idle).
- Create workspace `finsight-dev` on that capacity.
  - *Learn:* capacities vs. workspaces; how compute is billed (capacity units); workspace roles.

## 2. Lakehouse
- Create lakehouse `lh_finsight`.
- Note its two areas: **Files** (unmanaged files, our bronze landing zone) and
  **Tables** (managed Delta tables).
  - *Learn:* OneLake as one logical lake; Files vs. Tables; the auto-created SQL analytics endpoint.
- Design choice (record it in decisions.md): one lakehouse with `bronze_/silver_/gold_`
  table prefixes. Many enterprise setups use one lakehouse per layer; revisit
  once you've seen how your work project structures it.

## 3. Environment with the finsight wheel
- Build the wheel: `pip wheel . --no-deps -w dist` (CI also uploads it as an artifact).
- Create Environment `env_finsight`, upload `finsight-0.1.0-py3-none-any.whl`
  as a custom library, and **publish** it (publishing takes a few minutes).
- Confirm the runtime is 1.3 (Spark 3.5, Python 3.11), which is what CI tests against.
  - *Learn:* why executors need the package (we hit `ModuleNotFoundError: finsight`
    locally for exactly this reason); Environments as versioned, shareable dependency sets.

## 4. Notebook
- Import `notebooks/nb_finqa_bronze_to_silver.ipynb`.
- Attach `lh_finsight` as the default lakehouse and `env_finsight` as the environment.
- Make sure the first code cell is marked as the **parameter cell**.
  - *Learn:* default lakehouse and relative paths (`Files/...`, table names); parameter cells;
    `notebookutils.notebook.exit()` for returning values to a pipeline.

## 5. Pipeline `pl_finqa_ingest`
Parameters: `commit` (string, `0f16e2867befa6840783e58be38c9efb9229d742`),
`splits` (array, `["train","dev","test"]`).

1. **ForEach** over `@pipeline().parameters.splits`, containing a **Copy data** activity:
   - Source: HTTP connection, base URL `https://raw.githubusercontent.com/czyssrs/FinQA/`,
     relative URL `@concat(pipeline().parameters.commit, '/dataset/', item(), '.json')`, binary copy.
   - Sink: `lh_finsight` Files, folder `@concat('bronze/finqa/', pipeline().parameters.commit)`,
     file name `@concat(item(), '.json')`.
2. On success -> **Notebook** activity running `nb_finqa_bronze_to_silver` with base parameters
   `source_commit = @pipeline().parameters.commit` and `run_id = @pipeline().RunId`.
3. Run it, then open the run in the **Monitor** hub and find the notebook's exit value.
   - *Learn:* pipeline parameters and expressions, ForEach, connections, activity
     dependencies (success/failure paths), passing outputs between activities, monitoring.

## 6. Verify
- In the SQL analytics endpoint:
  ```sql
  SELECT split, COUNT(*) FROM silver_finqa_questions GROUP BY split;
  -- expect train 6251, dev 883, test 1147
  ```
- Run the pipeline a **second time**. Silver counts must not change (MERGE is idempotent);
  `bronze_finqa_records` will hold two runs, told apart by `_run_id`.
  - *Learn:* idempotency; append-only bronze vs. upserted silver.

## 7. Break it on purpose
- Upload a copy of `test.json` renamed `dev.json` into the bronze folder and rerun the notebook.
  The quality check should fail with "pages appear in more than one split", the notebook
  should fail, and silver should be untouched. Restore the real `dev.json` afterwards.
  - *Learn:* failure handling, and what a failed run looks like in Monitor, before it matters at work.

## Expected results (from the local run)
| Table | Rows |
|---|---|
| silver_finqa_documents | 2,789 |
| silver_finqa_evidence_units | 86,421 |
| silver_finqa_questions | 8,281 |

Executor agreement: 1.0 on every split.
