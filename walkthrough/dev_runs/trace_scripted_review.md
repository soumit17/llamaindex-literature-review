# Trace: a review with a scripted LLM on the 3-paper test corpus ($0)

Rendered from `trace_scripted_review.jsonl` (one JSON span per line). Times are offsets from the run start.

```
ReviewWorkflow.run  +0.00s  370 ms  events: workflow.output
  ReviewWorkflow.scope  +0.00s  4 ms  events: step.output
    ScriptedLLM.astructured_predict  +0.00s  3 ms  events: LLMStructuredPredictStartEvent, LLMStructuredPredictEndEvent
      ScriptedLLM.acomplete  +0.00s  1 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
        ScriptedLLM.complete  +0.00s  0 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
      PydanticOutputParser.parse  +0.01s  0 ms
  ReviewWorkflow.plan  +0.01s  4 ms
    ScriptedLLM.astructured_predict  +0.01s  3 ms  events: LLMStructuredPredictStartEvent, LLMStructuredPredictEndEvent
      ScriptedLLM.acomplete  +0.01s  1 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
        ScriptedLLM.complete  +0.01s  0 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
      PydanticOutputParser.parse  +0.01s  0 ms
  ReviewWorkflow.log_progress  +0.01s  0 ms
  ReviewWorkflow.research  +0.21s  48 ms  events: step.output
    VectorIndexRetriever.retrieve  +0.21s  25 ms  events: RetrievalStartEvent, RetrievalEndEvent
      VectorIndexRetriever._retrieve  +0.22s  19 ms
        _Counting.get_query_embedding  +0.22s  5 ms  events: EmbeddingStartEvent, EmbeddingEndEvent
          _Counting._get_query_embedding  +0.22s  0 ms
    FastEmbedRerank._postprocess_nodes  +0.25s  0 ms
    ScriptedLLM.astructured_predict  +0.25s  5 ms  events: LLMStructuredPredictStartEvent, LLMStructuredPredictEndEvent
      ScriptedLLM.acomplete  +0.26s  2 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
        ScriptedLLM.complete  +0.26s  1 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
      PydanticOutputParser.parse  +0.26s  0 ms
    quote_in_chunk  +0.26s  0 ms  events: CitationChecked
  ReviewWorkflow.research  +0.22s  49 ms  events: step.output
    VectorIndexRetriever.retrieve  +0.22s  23 ms  events: RetrievalStartEvent, RetrievalEndEvent
      VectorIndexRetriever._retrieve  +0.22s  16 ms
        _Counting.get_query_embedding  +0.22s  8 ms  events: EmbeddingStartEvent, EmbeddingEndEvent
          _Counting._get_query_embedding  +0.22s  0 ms
    FastEmbedRerank._postprocess_nodes  +0.25s  0 ms
    ScriptedLLM.astructured_predict  +0.26s  3 ms  events: LLMStructuredPredictStartEvent, LLMStructuredPredictEndEvent
      ScriptedLLM.acomplete  +0.26s  1 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
        ScriptedLLM.complete  +0.26s  0 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
      PydanticOutputParser.parse  +0.26s  0 ms
    quote_in_chunk  +0.27s  0 ms  events: CitationChecked
  ReviewWorkflow.research  +0.22s  49 ms  events: step.output
    VectorIndexRetriever.retrieve  +0.22s  25 ms  events: RetrievalStartEvent, RetrievalEndEvent
      VectorIndexRetriever._retrieve  +0.22s  17 ms
        _Counting.get_query_embedding  +0.22s  10 ms  events: EmbeddingStartEvent, EmbeddingEndEvent
          _Counting._get_query_embedding  +0.22s  0 ms
    FastEmbedRerank._postprocess_nodes  +0.25s  0 ms
    ScriptedLLM.astructured_predict  +0.27s  3 ms  events: LLMStructuredPredictStartEvent, LLMStructuredPredictEndEvent
      ScriptedLLM.acomplete  +0.27s  1 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
        ScriptedLLM.complete  +0.27s  0 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
      PydanticOutputParser.parse  +0.27s  0 ms
    quote_in_chunk  +0.27s  0 ms  events: CitationChecked
  ReviewWorkflow.research  +0.23s  48 ms  events: step.output
    VectorIndexRetriever.retrieve  +0.23s  22 ms  events: RetrievalStartEvent, RetrievalEndEvent
      VectorIndexRetriever._retrieve  +0.23s  15 ms
        _Counting.get_query_embedding  +0.23s  7 ms  events: EmbeddingStartEvent, EmbeddingEndEvent
          _Counting._get_query_embedding  +0.23s  0 ms
    FastEmbedRerank._postprocess_nodes  +0.25s  0 ms
    ScriptedLLM.astructured_predict  +0.27s  2 ms  events: LLMStructuredPredictStartEvent, LLMStructuredPredictEndEvent
      ScriptedLLM.acomplete  +0.27s  1 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
        ScriptedLLM.complete  +0.27s  0 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
      PydanticOutputParser.parse  +0.27s  0 ms
    quote_in_chunk  +0.27s  0 ms  events: CitationChecked
  ReviewWorkflow.log_progress  +0.23s  0 ms
  ReviewWorkflow.log_progress  +0.24s  0 ms
  ReviewWorkflow.log_progress  +0.25s  0 ms
  ReviewWorkflow.log_progress  +0.25s  0 ms
  ReviewWorkflow.research  +0.28s  22 ms  events: step.output
    VectorIndexRetriever.retrieve  +0.28s  12 ms  events: RetrievalStartEvent, RetrievalEndEvent
      VectorIndexRetriever._retrieve  +0.28s  8 ms
        _Counting.get_query_embedding  +0.28s  5 ms  events: EmbeddingStartEvent, EmbeddingEndEvent
          _Counting._get_query_embedding  +0.28s  0 ms
    FastEmbedRerank._postprocess_nodes  +0.29s  0 ms
    ScriptedLLM.astructured_predict  +0.29s  3 ms  events: LLMStructuredPredictStartEvent, LLMStructuredPredictEndEvent
      ScriptedLLM.acomplete  +0.30s  1 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
        ScriptedLLM.complete  +0.30s  0 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
      PydanticOutputParser.parse  +0.30s  0 ms
    quote_in_chunk  +0.30s  0 ms  events: CitationChecked
  ReviewWorkflow.gather_findings  +0.28s  0 ms
  ReviewWorkflow.log_progress  +0.28s  0 ms
  ReviewWorkflow.gather_findings  +0.28s  0 ms
  ReviewWorkflow.gather_findings  +0.29s  0 ms
  ReviewWorkflow.log_progress  +0.29s  0 ms
  ReviewWorkflow.gather_findings  +0.29s  0 ms
  ReviewWorkflow.gather_findings  +0.30s  0 ms  events: step.output
  ReviewWorkflow.log_progress  +0.30s  0 ms
  ReviewWorkflow.draft_outline  +0.30s  4 ms  events: step.output
    ScriptedLLM.astructured_predict  +0.30s  3 ms  events: LLMStructuredPredictStartEvent, LLMStructuredPredictEndEvent
      ScriptedLLM.acomplete  +0.30s  1 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
        ScriptedLLM.complete  +0.31s  0 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
      PydanticOutputParser.parse  +0.31s  0 ms
  ReviewWorkflow.log_progress  +0.31s  1 ms
  ReviewWorkflow.log_progress  +0.31s  0 ms
  ReviewWorkflow.log_progress  +0.31s  0 ms
  ReviewWorkflow.log_progress  +0.31s  1 ms
  ReviewWorkflow.on_outline_decision  +0.32s  1 ms
  ReviewWorkflow.write_section  +0.32s  3 ms  events: step.output
    ScriptedLLM.astream_chat  +0.32s  0 ms  events: LLMChatStartEvent
    ScriptedLLM.stream_chat  +0.32s  1 ms  events: LLMChatStartEvent
      ScriptedLLM.stream_complete  +0.32s  0 ms  events: LLMCompletionStartEvent
  ReviewWorkflow.write_section  +0.32s  4 ms  events: step.output
    ScriptedLLM.astream_chat  +0.32s  0 ms  events: LLMChatStartEvent
    ScriptedLLM.stream_chat  +0.32s  1 ms  events: LLMChatStartEvent
      ScriptedLLM.stream_complete  +0.32s  0 ms  events: LLMCompletionStartEvent
  ReviewWorkflow.write_section  +0.33s  3 ms  events: step.output
    ScriptedLLM.astream_chat  +0.33s  0 ms  events: LLMChatStartEvent
    ScriptedLLM.stream_chat  +0.33s  1 ms  events: LLMChatStartEvent
      ScriptedLLM.stream_complete  +0.33s  0 ms  events: LLMCompletionStartEvent
  ReviewWorkflow.log_progress  +0.33s  1 ms
  ReviewWorkflow.write_section  +0.34s  3 ms  events: step.output
    ScriptedLLM.astream_chat  +0.34s  0 ms  events: LLMChatStartEvent
    ScriptedLLM.stream_chat  +0.34s  1 ms  events: LLMChatStartEvent
      ScriptedLLM.stream_complete  +0.34s  0 ms  events: LLMCompletionStartEvent
  ReviewWorkflow.assemble  +0.34s  1 ms  events: step.output
  ReviewWorkflow.log_progress  +0.34s  1 ms
  ReviewWorkflow.check_citations  +0.34s  18 ms  events: step.output
    CitationCheckWorkflow.run  +0.35s  15 ms  events: workflow.output
      CitationCheckWorkflow.split_and_check  +0.35s  4 ms
        quote_in_chunk  +0.35s  0 ms  events: CitationChecked
        quote_in_chunk  +0.35s  0 ms  events: CitationChecked
        quote_in_chunk  +0.35s  0 ms  events: CitationChecked
        quote_in_chunk  +0.35s  0 ms  events: CitationChecked
        quote_in_chunk  +0.35s  0 ms  events: CitationChecked
        quote_in_chunk  +0.35s  0 ms  events: CitationChecked
        quote_in_chunk  +0.35s  0 ms  events: CitationChecked
        quote_in_chunk  +0.35s  0 ms  events: CitationChecked
        quote_in_chunk  +0.35s  0 ms  events: CitationChecked
      CitationCheckWorkflow.judge  +0.35s  3 ms  events: step.output
        ScriptedLLM.astructured_predict  +0.35s  3 ms  events: LLMStructuredPredictStartEvent, LLMStructuredPredictEndEvent
          ScriptedLLM.acomplete  +0.36s  1 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
            ScriptedLLM.complete  +0.36s  0 ms  events: LLMCompletionStartEvent, LLMCompletionEndEvent
          PydanticOutputParser.parse  +0.36s  0 ms
      CitationCheckWorkflow.finish  +0.36s  0 ms  events: step.output
  ReviewWorkflow.log_progress  +0.35s  0 ms
  ReviewWorkflow.log_progress  +0.36s  1 ms
  ReviewWorkflow.log_progress  +0.36s  1 ms
  ReviewWorkflow.log_progress  +0.37s  1 ms
  ReviewWorkflow.finalize  +0.37s  2 ms  events: step.output
```

Peak number of spans of the same step running at once: research 4, run 2
