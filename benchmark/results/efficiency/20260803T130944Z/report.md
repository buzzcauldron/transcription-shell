# Pipeline efficiency report

_Generated 20260803T130944Z UTC_

## Microbenches (CPU)

| Stage | mean s | notes |
|---|---:|---|
| `registry_load_all` | 0.00811480000265874 | {"n": 10} |
| `registry_by_name_x10` | 0.07694500859943218 | "[ModelSpec(name='computus-caroline-c1', kind='htr', path=PosixPath('/Users/halx |
| `doc_types_load_all` | 0.20990856932864213 | {"n": 13, "errors": []} |
| `prompt_build_full` | — | No module named 'prompt_builder' |
| `prompt_build_correct` | 1.0167015716433525e-06 | {"chars": 3066} |
| `yaml_validate` | 0.030340991605771705 | {"ok": true} |
| `yaml_extract` | 0.01788695850118529 | {"chars": 6220} |
| `genre_signal_internal` | 7.166992872953415e-06 | TypeError: compute_genre_signal() missing 1 required positional argument: 'doc_id' |
| `stylo_analyze_text` | 3.5589067499968223 | {"primary": "legal-writing", "secondary": "computus", "n_words": 2024, "fw_windo |
| `xml_validate_lines` | 0.0002927916124463081 | {"ok": true} |

## Page pipeline


## Batch parallelism (HTR-only)


## Bottleneck callouts

- Registry `by_name`×10 takes 0.0769s vs load_all 0.0081s — by_name rescans YAMLs each call.

## Recommendations

- Cache `model_registry.load_all()` results; make `by_name` O(1).
