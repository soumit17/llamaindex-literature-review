# Retrieval eval

40 labeled questions (data/qa/labeled.jsonl). Paper-level metrics over the top-5 chunks: hit-rate@5 and MRR (LlamaIndex `HitRate` / `MRR`), and papers@5 = distinct papers among the top-5 chunks (what a review can draw on).

| splitter | rerank | retriever | <=2/paper | hit@5 | MRR | papers@5 | seconds |
|---|---|---|---|---|---|---|---|
| sentence-512 | on | vector | no | 0.90 | 0.86 | 1.7 | 111 |
| sentence-512 **(chosen)** | on | vector | yes | 0.90 | 0.86 | 2.5 | 105 |
| sentence-512 | off | vector | yes | 0.85 | 0.75 | 2.5 | 3 |
| sentence-512 | off | vector | no | 0.82 | 0.74 | 1.9 | 3 |

Chosen: **sentence-512 | rerank on | vector | <=2/paper** (highest hit@5, then MRR, then papers@5; then the cheaper config).
Acceptance (spec M3): hit@5 >= 0.8 -> **met**.
Eval cost: $0.0000.

## Notes (yours)

- Which change moved hit-rate most: splitter, rerank or router?
- Where did misses come from (look at the questions)?
