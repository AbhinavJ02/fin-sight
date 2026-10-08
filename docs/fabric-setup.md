# Stage 2: running FinQA ingestion in Microsoft Fabric

Goal: the same bronze -> silver load that passes locally, running in Fabric as a
parameterized pipeline. Each step lists the Fabric concept it teaches.
Fabric's UI changes often; if a label below differs, the concept is what matters.

## 1. Capacity and workspace
- Start a Fabric trial (or a small pay-as-you-go F-SKU you pause when idle).
- Create workspace `finsight-dev` on that capacity.
  - *Learn:* capacities vs. workspaces; how compute is billed (capacity units); workspace roles.

## 2. Lakehouse
- Create lakehouse `lh_finsight` with **Lakehouse schemas enabled** (a checkbox in the create
  dialog). Decide before you click: treat this setting as permanent for the lakehouse (D14).
- Note its two areas: **Files** (unmanaged files, our bronze landing zone) and
  **Tables** (managed Delta tables, now grouped by schema; `dbo` exists by default).
  - *Learn:* OneLake as one logical lake; Files vs. Tables; schemas as namespaces inside one
    lakehouse; the auto-created SQL analytics endpoint.
- Layout (D14): one lakehouse, one schema per layer: `bronze`, `silver`, `gold`. The notebook
  creates them with `CREATE SCHEMA IF NOT EXISTS`.
- **Fallback** if that cell fails (permissions, or a runtime that rejects it): in the lakehouse
  explorer, use **New schema** under Tables to create `bronze`, `silver` and `gold` by hand,
  then rerun the notebook. The cell is idempotent, so it passes once they exist.

## 3. Environment with the finsight wheel
- Build the wheel from a committed, clean tree: `rm -rf dist && pip wheel . --no-deps -w dist`
  (CI also uploads one per pushed commit). Note the commit you built it from; Stage 3
  will bump the version so the Environment can tell the two apart.
- Create Environment `env_finsight`, upload `finsight-0.1.0-py3-none-any.whl`
  as a custom library, and **publish** it (publishing takes a few minutes).
- Confirm the runtime is 1.3 (Spark 3.5, Python 3.11), which is what CI tests against.
  - *Learn:* why executors need the package (we hit `ModuleNotFoundError: finsight`
    locally for exactly this reason); Environments as versioned, shareable dependency sets.

## 4. Notebook
- Import `notebooks/nb_finqa_bronze_to_silver.ipynb`.
- Attach `lh_finsight` as the default lakehouse and `env_finsight` as the environment.
- Make sure the first code cell is marked as the **parameter cell**.
  - *Learn:* default lakehouse and relative paths (`Files/...`, `schema.table` names);
    parameter cells; `notebookutils.notebook.exit()` for returning values to a pipeline.

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
- **Confirm the tables landed in the schemas**, not in `dbo`: in the lakehouse explorer you
  should see `bronze.finqa_records` and the three `silver.finqa_*` tables. On the first run,
  the notebook's `results` cell should show `"created"` for all three silver tables, and
  `"merged"` on every run after that. This is how `merge_into` shows it handles
  schema-qualified names (verified in Fabric, D14). If a silver table shows `"created"`
  twice, or one appears under `dbo`, stop and report it.
- In the SQL analytics endpoint:
  ```sql
  SELECT split, COUNT(*) AS n FROM silver.finqa_questions GROUP BY split;
  -- expect train 6251, dev 883, test 1147
  ```
- Run the pipeline a **second time**. Silver counts must not change (MERGE is idempotent);
  `bronze.finqa_records` will hold two runs, told apart by `_run_id`:
  ```sql
  SELECT _run_id, COUNT(*) AS n FROM bronze.finqa_records GROUP BY _run_id;
  ```
  - *Learn:* idempotency; append-only bronze vs. upserted silver.

## 7. Break it on purpose
- On your Mac, make the bad file: `cp data/external/FinQA/dataset/test.json ~/Desktop/finqa_break/dev.json`
  (it must be named `dev.json`).
- Replace `dev.json` in `Files/bronze/finqa/<commit>/`. **Drag and drop** onto the folder in
  the lakehouse Explorer worked; the **Upload** menu did not replace the file in our run.
  Deleting the real `dev.json` first and then dropping the new one in is the most reliable.
- **Check the swap before running anything**, in a temporary notebook cell:
  ```python
  for f in notebookutils.fs.ls(f"Files/bronze/finqa/{source_commit}/"):
      print(f.name, f.size)
  ```
  `dev.json` must show 14395143 bytes (the size of `test.json`); the real one is 10954658.
  Our first attempt skipped this check and silently ran on the real files.
- Set a distinct `run_id` in the parameter cell (e.g. `break_test`), then **Run all**. The
  quality-check cell should fail with
  `FinQA silver quality checks failed: ['1147 duplicate question_ids', '380 pages appear in more than one split']`
  and nothing after it runs. Bronze gains 8,545 rows for this run (6,251 + 1,147 + 1,147).
- Restore the real `dev.json` (`data/external/FinQA/dataset/dev.json`, same pinned commit),
  check the listing shows 10954658 again, and set `run_id` back.
- Expect `bronze.finqa_records` to gain this bad run anyway: bronze is append-only and is
  written before the quality check. That's by design (bronze records what arrived); its
  `_run_id` identifies it.
  - *Learn:* failure handling, and what a failed run looks like in Monitor, before it matters at work.

## Gotchas we hit
- **Files tree looks empty.** The Explorer caches the Files tree; refresh it and expand the
  folders. `notebookutils.fs.ls("Files/...")` shows the truth.
- **Every hand-started run is `run_id = "manual"`**, so bronze can't tell those runs apart.
  Give each manual run its own `run_id` in the parameter cell.

## What to report back
- The notebook's exit value from the Monitor hub (step 5).
- Row counts per silver table and the per-split question counts (step 6), first and second run.
- Whether step 7 failed the way it should, and the error text.
- Whether the notebook created the schemas itself or you used the fallback.
- The `results` cell output from the first and second runs (`created` / `merged`).
- Any error, verbatim, at the step where it happened (Environment publishing included).

## Expected results (from the local run)
| Table | Rows |
|---|---|
| silver.finqa_documents | 2,789 |
| silver.finqa_evidence_units | 86,421 |
| silver.finqa_questions | 8,281 |

Executor agreement: 1.0 on every split.
