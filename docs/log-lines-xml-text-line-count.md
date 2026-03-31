# What log lines mean: `lines_xml`, `transcription_yaml`, and `text_line_count`

After **`transcriber-shell run`** or **`batch`**, or in the GUI log, you may see lines like:

```text
lines_xml=/path/to/page.xml
transcription_yaml=/path/to/artifacts/<job_id>/<image_stem>_transcription.yaml
text_line_count=76
```

Different jobs or artifact folders can show **different** `text_line_count` values (for example 50 on one run and 76 on another). That is **expected** when the underlying lines XML or page differs.

## What each field is

| Log line | Meaning |
|----------|--------|
| `lines_xml=...` | Path to the **PageXML / lines** file used for that job (line detection regions). |
| `transcription_yaml=...` | Path where the **LLM output** was written (`<image_stem>_transcription.yaml` under the job’s artifact folder). |
| `text_line_count=N` | **Count of XML elements** whose local name is `TextLine` in that lines XML (namespace-agnostic traversal). |

Implementation: [`validate_lines_xml`](../src/transcriber_shell/xml_tools/lines_validate.py) sets `stats["text_line"]` via `_count_by_local_name(root, "TextLine")`. [`run_pipeline`](../src/transcriber_shell/pipeline/run.py) assigns `text_line_count = int(stats.get("text_line", 0))` after validation.

So **`text_line_count` is how many `TextLine` nodes are in the lines file**, not “how many lines of text in the YAML file.”

## Why counts differ across log blocks

Log output may interleave or repeat blocks for **different** runs (different `job_id`, image, or artifact directory). For example:

- One block might reference **`artifacts/hardest/<stem>_transcription.yaml`** with **`text_line_count=50`**.
- Another might be a batch row for a different image with its own **`lines_xml`**, **`transcription_yaml`** under **`artifacts/<that_job_id>/`**, and **`text_line_count=76`**.

Those reflect **different pages** or **different lineation outputs**. **76 vs 50 is expected** if one lines XML has 76 `TextLine` elements and the other has 50.

## What is not being compared

- The **transcription YAML** is validated and normalized separately (segments, structure, etc.). The shell does **not** assert `len(segments) == text_line_count` unless you add such a check elsewhere.
- If you compare counts, compare **XML `TextLine` count** to **your YAML segment structure** (for example one segment per line) on the **same** job.

## Batch with “skip successful”

When **`--skip-successful`** / the GUI checkbox skips a page because a valid `*_transcription.yaml` already exists, the pipeline does **not** re-run lineation or the LLM. **`text_line_count` is not recomputed** (it is not the PageXML `TextLine` count for that skip). The GUI and batch row instead report **`transcription_segment_count`**: the number of **`segments`** in the existing transcription YAML (best-effort parse). That number is **not** the same metric as PageXML `TextLine` count, but it avoids showing a misleading `text_line_count=0`.

## If something looks wrong

- Confirm **`lines_xml`** for the job you care about is the file you expect (wrong file leads to a misleading count).
- Run **`transcriber-shell validate-xml`** on that XML path to see `text_line` / `text_region` / `line` stats (see [`lines_validate.py`](../src/transcriber_shell/xml_tools/lines_validate.py)).
