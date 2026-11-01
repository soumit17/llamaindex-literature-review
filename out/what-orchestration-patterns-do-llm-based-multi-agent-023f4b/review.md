# Orchestration Patterns in LLM-Based Multi-Agent Systems: Control, Cost, and Robustness Trade-offs

> **Question:** What orchestration patterns do LLM-based multi-agent systems use, and how do they trade off control, cost and robustness?  
> Generated 2026-11-01 from 5 papers, 9 cited passages.

## Introduction

Coordinating several LLM agents raises a question that single-model pipelines avoid: who decides which agent acts next, and at what price? Centralized designs place one orchestrator in charge. In one formulation, it selects a single agent at each step based on the current global state and task specification [1]. Because this policy depends only on that state and task, it satisfies the Markov property [1], and its separation of agent selection from agent internals is presented as improving adaptability and scalability [1].

## Control Structures: Centralized Versus Decentralized Orchestration

Centralized orchestration concentrates control in one component. A single orchestrator selects which one agent to activate at each step, conditioned on the current global system state and task specification [1]. Its policy depends only on that current state and task, so it satisfies the Markov property [1]. Because agent selection is decoupled from internal agent behavior, the design is presented as improving adaptability and scalability [1]. The sequential routing can also be learned, with the orchestrator's policy updated by reinforcement learning from task feedback [2].

Decentralized peer-to-peer designs distribute these decisions: agents autonomously decide whom to address, limiting communication to peers they deem relevant [3].

## Cost and Accuracy Trade-offs

Several systems suggest that accuracy in multi-agent orchestration can be bought with budget, and that this trade-off can be made explicit. MACA reports that higher cost consistently yields higher accuracy under a tunable budget [4], and it is reported to reach a more favorable frontier than existing multi-agent baselines, which the authors attribute to structured and selective coordination [4]. Evolving orchestration offers a complementary lever: a tunable reward weight λ sets how strongly accuracy is traded against efficiency, with larger values emphasizing cost reduction [5]. Cost savings may also come from shrinking the active team. In the Titan setting, token consumption and active agent count fell over training [5].

Configuration choices can matter as much as budget. In the Beyond Frameworks study, collaboration configurations produced an accuracy gap of up to 37.6% and substantial variation in token cost [6]. Similar accuracy can hide large efficiency differences: in the EBFC task, G1-P2-I4-C2 reached 86.4% accuracy, comparable to G2-P3-I1-C3, yet used 11.5 times more output tokens [6].

## Robustness, Failure Recovery, and Verification

Simple retries are a common recovery strategy in multi-agent pipelines, but MARCO suggests that how a retry is framed matters more than how many are attempted [7][7]. Reflection prompts, which feed the failed attempt back to the model, substantially reduce guardrail error recurrence and typically resolve issues within the first retry [7]. The first reflective retry reportedly clears all but two errors, while error rates without reflection remain high even after four retries [7]. Retrying with the original prompt reduces errors only gradually and does not eliminate them within that budget [7]

## State Sharing, Handoffs, and Scalability

Message passing over graph neighbors is how agents communicate in the AgentsNet setting, through a protocol implemented with LangChain [8]. This locality makes coordination possible, but it also shapes how information moves. Agents sometimes agree on a common strategy late in the exchange, leaving too few rounds to implement it [9]. They often do not tell neighbors which strategy they assume, and then follow it throughout message-passing [9]. Because agents generally accept neighbor information, the same trust that enables effective coordination can carry incorrect assumptions into incorrect solutions [9]. Handoffs therefore appear vulnerable, since unstated assumptions go unchallenged and can propagate into incorrect solutions [9].

Round requirements depend on task structure. Global tasks need rounds that scale with graph diameter (2D+1), whereas local tasks use a fixed number of rounds set by graph size, namely 4, 5, or 6 rounds for 4, 8, or 16 nodes [8]. Context is a related constraint: on 8- and 16-node problems, communication histories grow long enough to require an effective context window larger than 16K tokens, and this partly informed the choice of models [

## Conclusion



## Coverage notes

- How do centralized orchestrator-worker designs and decentralized peer-to-peer agent designs differ in how they decide which agent acts next, and what does each do to controllability and debuggability?: The excerpts do not directly assess controllability or debuggability for either design, and do not compare debuggability of the two designs; the evidence is largely about design mechanics and performance claims.
- How do the reviewed systems trade off token and API cost against task accuracy, for example through the number of agent calls, debate rounds, or parallel fan-out?: The excerpts do not report monetary API cost, explicit debate-round counts, or systematic parallel fan-out comparisons; cost is mostly reported as tokens or abstract budgets, and most systems (e.g., AgentVerse, MaAS) lack specific cost figures.
- How do different orchestration patterns behave under agent failures, hallucinated outputs, or malformed messages, and which recovery mechanisms (retries, verifiers, supervisors, fallbacks) are used and how effective are they?: The excerpts do not report how orchestration patterns behave under agent failures, hallucinated outputs, or malformed messages in general; they do not evaluate supervisors or fallbacks, and they do not compare verifiers or retries across orchestration patterns with quantified effectiveness beyond MARCO's guardrail retries and MACA's transition statistics.
- What mechanisms do the papers use to coordinate shared state and handoffs between agents (e.g., shared memory, message passing, blackboards), and how do these choices affect error propagation and scalability as agent count grows?: The excerpts do not describe shared memory or blackboard designs, do not compare mechanisms, and provide no systematic measurement of error propagation or scalability as agent count grows; the scalability evidence is limited to graph sizes of 4 to 16 nodes.
- Under what task conditions (e.g., decomposability, need for verification, latency budget) do the reviewed papers recommend one orchestration pattern over another, and what evidence supports those recommendations?: The excerpts do not state explicit recommendations for choosing one orchestration pattern over another under specific conditions such as decomposability or latency budget; no latency-budget evidence is provided, and the MACA claims describe observed behavior rather than prescriptive guidance.

## References

[1] Dang et al. (2025). Multi-Agent Collaboration via Evolving Orchestration. arXiv:2505.19591, p. 3  
[2] Dang et al. (2025). Multi-Agent Collaboration via Evolving Orchestration. arXiv:2505.19591, p. 2  
[3] Wang et al. (2025). Beyond Frameworks: Unpacking Collaboration Strategies in Multi-Agent Systems. arXiv:2505.12467, p. 4  
[4] Li et al. (2026). Multi-Agent Coordination Adaptation via Structure-Guided Orchestration. arXiv:2605.25746, p. 7  
[5] Dang et al. (2025). Multi-Agent Collaboration via Evolving Orchestration. arXiv:2505.19591, p. 7  
[6] Wang et al. (2025). Beyond Frameworks: Unpacking Collaboration Strategies in Multi-Agent Systems. arXiv:2505.12467, p. 6  
[7] Shrimal et al. (2024). MARCO: Multi-Agent Real-time Chat Orchestration. arXiv:2410.21784, p. 7  
[8] Grötschla et al. (2025). AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs. arXiv:2507.08616, p. 7  
[9] Grötschla et al. (2025). AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs. arXiv:2507.08616, p. 9  
