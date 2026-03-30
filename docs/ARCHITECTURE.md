# Architecture

```mermaid
flowchart LR
  subgraph in1 [Input]
    IMG[Pre-cropped image]
  end
  subgraph gm [Glyph Machina]
    B[Playwright browser]
    UP[Upload and crop confirm]
    IL[Identify Lines]
    DL[Download Lines File]
  end
  subgraph xml [XML]
    V1[lines_validate]
    V2[Optional XSD]
  end
  subgraph llm [LLM]
    PB[prompt_builder zones]
    API[Anthropic or OpenAI or Gemini]
  end
  subgraph out [Output]
    PXML[lines.xml]
    YML[transcription.yaml]
  end
  IMG --> B
  B --> UP --> IL --> DL --> PXML
  PXML --> V1 --> V2
  IMG --> PB
  V1 --> PB
  PB --> API --> YML
```

- **transcriber_shell.glyph_machina** — Playwright-only; no public Glyph Machina HTTP API is used.
- **transcriber_shell.xml_tools** — stdlib XML parse + optional `lxml` XSD.
- **transcriber_shell.llm** — Imports `prompt_builder` and `validate_schema` from `vendor/transcription-protocol/benchmark/` at runtime (`protocol_paths.ensure_protocol_benchmark_on_path`).
- **transcriber_shell.pipeline.run** — Sequences steps and writes `artifacts/<job_id>/`.
