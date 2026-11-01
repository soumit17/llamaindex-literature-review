# Debugger UI walkthrough (spec §13.3)

```bash
uv run litreview serve            # then open http://127.0.0.1:8080/
```

Take a screenshot at each step and paste it below.

1. **Visualize all three workflows.** Pick `ingest`, `review` and `agent_review` in turn. The review graph
   is the one in `docs/review_flow.md`, drawn by the server from the same step annotations.
   _(screenshots)_
2. **Start a review from the form.** Pick `review`: the form is generated from `ReviewRequest`'s fields
   (question, max_subquestions, target_words, audience). Use `--max-subquestions 3` worth of questions to
   keep it cheap (~$0.01).
   _(screenshot)_
3. **Watch the events log** as `ResearchProgress` and `Progress` events stream in, while research runs
   four at a time.
   _(screenshot)_
4. **Answer the outline approval.** When `OutlineApprovalRequired` appears, use **Send Event**, choose
   `OutlineDecision` (offered because `server.py` registers it via `additional_events`) and send
   `{"action": "approve"}` (or `{"action": "reject", "feedback": "..."}` to see the re-plan loop).
   _(screenshot)_
5. **Compare two runs side by side**, e.g. two runs of the same question: different sub-questions and
   outlines (the "outline overlap" column in `docs/explicit-vs-agentic.md` measures this).
   _(screenshot)_

## Notes (yours)

- What did the UI show that the CLI didn't (or the other way round)?
