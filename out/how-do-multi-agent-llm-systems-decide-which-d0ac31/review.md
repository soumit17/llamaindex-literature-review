# Who Speaks Next: Turn-Taking Mechanisms and Their Costs in Multi-Agent LLM Systems

> **Question:** How do multi-agent LLM systems decide which agent acts next, and what does each approach cost?  
> Generated 2026-11-01 from 6 papers, 10 cited passages.

## Introduction: The Next-Agent Selection Problem



## Centralized Orchestrators and Routing Signals

Centralized orchestrators separate *who acts* from *how agents work internally*. In the Evolving Orchestration work, a central orchestrator selects a single agent at each time step, conditioned on the current global system state and task specification [1]. It does not need to inspect agent internals, since it dynamically chooses which agents to activate as the task state changes [1]. The selection policy maps observable context to a distribution over candidates, realized through neural scoring, embedding-based models, or Bradley-Terry style approaches [1]. At each step, the orchestrator re-selects the next agent using a policy conditioned only on the updated state and task [1].

Structure-Guided Orchestration adds a different kind of signal. Actions are chosen by a state-conditioned policy that is guided by a directed interaction graph G [2], so the topology constrains which interactions are plausible rather than leaving selection entirely to learned scores. Routing signals may also be mixed. The Difficulty-Aware approach activates operators sequentially in descending score order until cumulative evidence exceeds a threshold, while a separate LLM router pairs each chosen operator with an LLM via a temperature-scaled softmax over candidates [3]. This suggests that rule-based gating and learned LLM routing can coexist in one pipeline.

Scoring orchestration quality is handled differently again. The Reward Modeling work uses an LLM-based controller that plans workflow structure and agent interactions, and trains a Bradley-Terry reward model on win-lose orchestration trajectory pairs [4]. The Bradley-Terry family thus appears both as a selection policy [1] and as a training objective for evaluating trajectories [4], a shared pairwise-preference view that may matter for practitioners.

## Decentralized Turn-Taking and Coordination Failures



## Cost and Latency Profiles of Orchestration

Reported costs are difficult to compare across systems. AFlow is reported with a training cost of $22.50 and an inference cost of $1.66, while the difficulty-aware method reports $2.34 for training and $0.27 for inference [3]. MARCO's figures are relative rather than absolute: Claude-3-sonnet is described as 30% faster and 60% cheaper than claude-v2.1 under a 5000-request MARS assumption [5], and its intent classifier has a reported latency of 1.98 seconds [5]. Because these numbers mix training and inference, single components and end-to-end systems, and different workloads, any cross-paper ranking should be treated as tentative.

Learned orchestrators offer a different cost lever. Puppeteer-Mono's token consumption on MMLU-Pro consistently decreases over training across almost all settings [6]. This is a

## Accuracy-Efficiency Trade-offs

Accuracy-efficiency trade-offs are often handled by folding cost directly into the training objective. The Evolving Orchestration work defines a terminal reward that subtracts a cost term scaled by a coefficient λ, which governs how strongly accuracy is traded against consumption [7]. Raising λ shifts emphasis toward minimizing cost, which lets practitioners select operating points suited to different application requirements [6]. The same work, however, suggests the trade-off is not always zero-sum: token consumption fell over training in nearly all settings while performance rose, which the authors describe as simultaneous gains in effectiveness and efficiency [6]. Whether this pattern generalizes beyond the reported settings remains unclear.

Structural choices interact with these costs. In the Structure-Guided Orchestration paper, removing the GraphSpec prior produced distinct accuracy degradation and increased overhead, suggesting that agent composition and interaction patterns should be designed jointly rather than independently [8]. Orchestration-level reward modeling offers a complementary route, as the Orch-RM paper reports consistent improvements in the performance-efficiency trade-off for test-time scaling and orchestrator training [9]. Taken together, these results point toward treating t

## Evaluation Gaps and Conflicting Evidence

Evaluation practice for turn-selection strategies is fragmented, and the gaps matter when choosing one. Fixed-dialogue benchmarks are a particular concern. The Collaborate, Deliberate, Evaluate paper argues that offline multi-turn benchmarks such as MT-Bench make fair comparison of interventions impossible, because the dialogue diverges after each intervention [10]. Simulation-based protocols can sidestep this divergence, but results then depend on the chosen simulator and backbone, and the excerpts do not report controls for either [10].

Comparability is a second obstacle. A survey notes that multi-agent evaluations are often run in narrow scenarios with differing configurations, producing inconsistent and incomparable

## Conclusion: Implications for Practitioners



## Coverage notes

- How do centralized orchestrator agents select the next acting agent, and what routing signals (LLM planner output, learned router, rule-based dispatch) do the papers use to make that choice?: The excerpts do not describe a rule-based dispatch mechanism, do not specify the exact LLM planner prompt or output format, and do not detail how the Bradley-Terry reward model is used at routing time rather than for training evaluation.
- How do decentralized or peer-to-peer multi-agent systems decide turn-taking, such as through broadcast, bidding, or self-selection by agents, and what coordination failures do they exhibit?: The excerpts do not describe bidding or self-selection mechanisms for turn-taking, nor detail specific coordination failures beyond redundancy, conflicting output, and fragmented context.
- What token, latency, and monetary costs do the reported orchestration patterns incur per decision step, and how do these costs scale with the number of agents and conversation rounds?: The excerpts give no systematic analysis of how token, latency, or monetary costs scale with number of agents or conversation rounds; costs are reported as aggregate totals or per-setting figures, not per decision step. Excerpt 5 is only partially relevant and does not state numeric costs.
- What trade-offs between task success rate and orchestration overhead do the papers report when comparing next-agent selection strategies on shared benchmarks?: The excerpts do not give a direct head-to-head comparison of next-agent selection strategies on shared benchmarks with numeric success rates and overhead values; the Structure-Guided paper's figure data is garbled and no specific numbers are stated.
- Which evaluation setups, models, and benchmarks do the papers use to compare selection strategies, and where do their results conflict or lack controls?: The excerpts do not give concrete selection-strategy results, a unified list of models and benchmarks across papers, or the outcomes of the rubric-sensitivity and cost analyses; claims about conflicts rest on limited quotes.

## References

[1] Dang et al. (2025). Multi-Agent Collaboration via Evolving Orchestration. arXiv:2505.19591, p. 3  
[2] Li et al. (2026). Multi-Agent Coordination Adaptation via Structure-Guided Orchestration. arXiv:2605.25746, p. 3  
[3] Su et al. (2025). Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows. arXiv:2509.11079, p. 5  
[4] Tsang et al. (2026). Reward Modeling for Multi-Agent Orchestration. arXiv:2606.13598, p. 2  
[5] Shrimal et al. (2024). MARCO: Multi-Agent Real-time Chat Orchestration. arXiv:2410.21784, p. 6  
[6] Dang et al. (2025). Multi-Agent Collaboration via Evolving Orchestration. arXiv:2505.19591, p. 7  
[7] Dang et al. (2025). Multi-Agent Collaboration via Evolving Orchestration. arXiv:2505.19591, p. 4  
[8] Li et al. (2026). Multi-Agent Coordination Adaptation via Structure-Guided Orchestration. arXiv:2605.25746, p. 7  
[9] Tsang et al. (2026). Reward Modeling for Multi-Agent Orchestration. arXiv:2606.13598, p. 9  
[10] Nath et al. (2025). Collaborate, Deliberate, Evaluate: How LLM Alignment Affects Coordinated Multi-Agent Outcomes. arXiv:2509.05882, p. 5  
