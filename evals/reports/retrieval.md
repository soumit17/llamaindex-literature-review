# Retrieval eval

40 labeled questions (data/qa/labeled.jsonl). Paper-level metrics over the top-5 chunks: hit-rate@5 and MRR (LlamaIndex `HitRate` / `MRR`).

| splitter | rerank | retriever | hit@5 | MRR | seconds |
|---|---|---|---|---|---|
| sentence-512 **(chosen)** | on | vector | 0.90 | 0.86 | 79 |
| sentence-512 | on | router | 0.85 | 0.81 | 333 |
| sentence-512 | off | vector | 0.82 | 0.74 | 2 |
| sentence-512 | off | router | 0.75 | 0.72 | 68 |

Chosen: **sentence-512 | rerank on | vector** (highest hit@5, then MRR; ties prefer the cheaper: no router, no rerank).
Acceptance (spec M3): hit@5 >= 0.8 -> **met**.
Eval cost: $0.0100.

## Notes (yours)

- Which change moved hit-rate most: splitter, rerank or router?
- Where did misses come from (look at the questions)?
