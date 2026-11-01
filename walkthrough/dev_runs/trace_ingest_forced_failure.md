# Trace: `litreview ingest --fail 2308.00352` on a copy of the real corpus ($0)

Rendered from `trace_ingest_forced_failure.jsonl` (one JSON span per line). Times are offsets from the run start.

```
IngestionWorkflow.run  +0.00s  30125 ms  events: workflow.output
  IngestionWorkflow.load_lock  +0.00s  1 ms
  IngestionWorkflow.fetch_pdf  +0.01s  13 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +0.02s  3 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +0.03s  2 ms  events: step.output
  IngestionWorkflow.parse_pdf  +0.03s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +0.03s  2 ms  events: step.output
  IngestionWorkflow.parse_pdf  +0.04s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +5.98s  6 ms  events: step.output
    IngestionPipeline.run  +5.98s  3 ms
      SentenceSplitter.__call__  +5.98s  1 ms
      FastEmbedEmbedding.__call__  +5.98s  0 ms
  IngestionWorkflow.fetch_pdf  +5.99s  2 ms  ERROR  events: SpanDropEvent, exception
  IngestionWorkflow.parse_pdf  +5.99s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.01s  37 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.05s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.05s  5 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.06s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.06s  4 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.07s  4 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.07s  2 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.08s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.08s  6 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.09s  2 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.09s  1 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.10s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.10s  1 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.10s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.10s  15 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.11s  7 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.12s  2 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.12s  5 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.13s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.13s  5 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.14s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.14s  3 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.15s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.15s  4 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.15s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.16s  6 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.16s  2 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.17s  5 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.17s  2 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.18s  2 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.18s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.19s  3 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.19s  2 ms  events: step.output
  IngestionWorkflow.index_paper  +6.20s  17 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.20s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.21s  4 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.21s  2 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.22s  3 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.22s  2 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.23s  5 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.24s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.24s  7 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.24s  2 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.25s  7 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.26s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.26s  8 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.26s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.27s  6 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.28s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.28s  3 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.29s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.29s  5 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.30s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.30s  5 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.30s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.31s  2 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.31s  2 ms  events: step.output
  IngestionWorkflow.index_paper  +6.32s  6 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.32s  3 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.32s  2 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.33s  2 ms  events: step.output
  IngestionWorkflow.index_paper  +6.33s  6 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.34s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.34s  6 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.35s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +6.35s  4 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.36s  2 ms  events: step.output
  IngestionWorkflow.index_paper  +6.36s  5 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.37s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.37s  7 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.37s  2 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.38s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.38s  5 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.39s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.39s  7 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.39s  3 ms  events: step.output
  IngestionWorkflow.index_paper  +6.40s  6 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.40s  1 ms  events: step.output
  IngestionWorkflow.parse_pdf  +6.41s  2 ms  events: step.output
  IngestionWorkflow.index_paper  +6.41s  6 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.41s  3 ms  events: step.output
  IngestionWorkflow.index_paper  +6.42s  7 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.42s  1 ms  events: step.output
  IngestionWorkflow.index_paper  +6.43s  4 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.43s  2 ms  events: step.output
  IngestionWorkflow.index_paper  +6.44s  4 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.44s  2 ms  events: step.output
  IngestionWorkflow.summarize_paper  +6.44s  1 ms  events: step.output
  IngestionWorkflow.fetch_pdf  +9.19s  1 ms  ERROR  events: SpanDropEvent, exception
  IngestionWorkflow.fetch_pdf  +15.96s  1 ms  ERROR  events: SpanDropEvent, exception
  IngestionWorkflow.fetch_pdf  +28.09s  1 ms  ERROR  events: SpanDropEvent, exception
  IngestionWorkflow.on_fetch_failure  +28.10s  1 ms
  IngestionWorkflow.persist  +28.10s  2022 ms  events: step.output
```

Peak number of spans of the same step running at once: run 2
