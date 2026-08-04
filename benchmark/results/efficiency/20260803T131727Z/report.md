# Pipeline efficiency report

_Generated 20260803T131727Z UTC_

## Microbenches (CPU)

| Stage | mean s | notes |
|---|---:|---|
| `registry_load_all` | 0.007860107999294996 | {"n": 10} |
| `registry_by_name_x10` | 0.07436807480407878 | "[ModelSpec(name='computus-caroline-c1', kind='htr', path=PosixPath('/Users/halx |
| `doc_types_load_all` | 0.22461973632258983 | {"n": 13, "errors": []} |
| `prompt_build_full` | — | No module named 'prompt_builder' |
| `prompt_build_correct` | 7.750029908493162e-07 | {"chars": 3066} |
| `yaml_validate` | 0.030189441796392203 | {"ok": true} |
| `yaml_extract` | 0.01755082919844426 | {"chars": 6220} |
| `genre_signal_internal` | 9.625015081837773e-06 | TypeError: compute_genre_signal() missing 1 required positional argument: 'doc_id' |
| `stylo_analyze_text` | 3.5825732500234153 | {"primary": "legal-writing", "secondary": "computus", "n_words": 2024, "fw_windo |
| `xml_validate_lines` | 0.00030167499789968133 | {"ok": true} |

## Page pipeline


## Batch parallelism (HTR-only)


## Bottleneck callouts

- Registry `by_name`×10 takes 0.0744s vs load_all 0.0079s — by_name rescans YAMLs each call.
- Stage routing: interactive HTR→akdeniz; train/batch→bridges GPU-shared; LLM→Gemini; stylo→local; bridges login=submit only.

## Recommendations

- Cache `model_registry.load_all()` results; make `by_name` O(1).

## Recommended stage routing

| Stage | Preferred | Fallback |
|---|---|---|
| lineation + Kraken HTR (interactive) | akdeniz | halxvi (if load low) |
| HTR / training batch | bridges_gpu (GPU-shared v100-32 sbatch) | akdeniz |
| LLM correct/full | any + Gemini API | Ollama if vision model local |
| stylo / YAML extract | local Mac / any CPU | akdeniz |
| bridges_login | submit/monitor only | — |

## Remote HTR

```json
{
  "ssh": "akdeniz",
  "returncode": 1,
  "stdout_tail": "",
  "stderr_tail": "Traceback (most recent call last):\n  File \"<stdin>\", line 5, in <module>\n  File \"/tmp/ts-efficiency-78993/transcriber_shell/runtime/__init__.py\", line 5, in <module>\n    from transcriber_shell.runtime.machine_profile import (\n  File \"/tmp/ts-efficiency-78993/transcriber_shell/runtime/machine_profile.py\", line 21, in <module>\n    from transcriber_shell.config import Settings\n  File \"/tmp/ts-efficiency-78993/transcriber_shell/config.py\", line 9, in <module>\n    from pydantic_settings import BaseSettings, SettingsConfigDict\nModuleNotFoundError: No module named 'pydantic_settings'\n",
  "error": "remote_summary.json missing"
}
```
