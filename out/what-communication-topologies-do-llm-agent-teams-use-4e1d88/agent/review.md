# Communication Topology in LLM Multi-Agent Systems: What the Evidence Shows

> **Question:** What communication topologies do LLM agent teams use, and how does topology affect task performance?  
> Generated 2026-11-01 from 4 papers, 13 cited passages.

## Introduction

Multi-agent LLM systems divide work among several model instances that exchange messages, and the way those instances are connected is a central design decision. For an ML engineer, the choice of connection pattern, whether a hub, a chain, a hierarchy, or a sparse graph, determines how information moves, how many model calls are made, and how much of the budget is spent on coordination rather than on the task. This review asks what the current literature shows about communication topology in LLM multi-agent systems: how topologies are defined, how they affect task performance, what mechanisms explain those effects, what they cost, and when they matter most.

The evidence base is uneven. Several papers propose structured or adaptive topologies and report gains, but few run controlled comparisons in which only the topology changes and the agent count, model, and token budget are held fixed. Where direct evidence is missing, this review says so and treats the mechanisms that follow as inferences. The sections below move from taxonomy, to performance, to cost and mechanisms, to conditions and automated design, and close with the practical implications and the gaps that future work should address.

## A Taxonomy of Communication Topologies

A survey of LLM-based multi-agent collaboration reports four main classes of communication structure, three of which are centralized, decentralized or distributed, and hierarchical topologies [1]. In centralized designs, collaboration decisions are concentrated in one node. These are simple to design and implement and allow efficient resource allocation, but they fail if the central node fails [1]. Decentralized systems take the opposite approach by distributing control across agents. Each agent acts on local information and limited communication with its peers [2]. Hierarchical designs sit between these extremes.

Beyond these families, the literature divides into two broad approaches. Some studies examine pre-determined graph structures, while others propose automatically adapting the network topology [3]. GPTSwarm is a prominent example of the graph-based approach: it organizes LLM-based agents in structured topologies and reports better results on MMLU, HumanEval, and GAIA [4]. Later work extends this line by learning adaptive communication structures or interaction patterns, with the explicit aim of reducing redundant messages [5].

The taxonomy matters because the same label can hide very different implementations. A "debate" topology, a "hub" topology, and a "graph" topology differ in who sends to whom and how often, and these differences drive the cost and failure modes discussed later. Engineers comparing published systems should therefore check the actual message-passing pattern rather than relying on the topology name alone.

## Performance Effects and Their Limits

Structured topologies have been reported to improve benchmark performance. GPTSwarm, which organizes agents as a graph, reports gains on MMLU, HumanEval, and GAIA [4]. However, these results come from separate systems and task suites, so they do not isolate the effect of topology alone. The corpus contains no controlled comparison of fixed topologies such as chain, star, and fully connected at matched agent counts, so the size of the topology effect on accuracy is not established.

What the literature does support is that no single topology dominates. Prior experiments, as summarized in AgentsNet, find that different topologies perform best for specific tasks [3]. This suggests that the right structure depends on the task rather than being a general upgrade.

Debate-style interaction is a common topology for reasoning tasks, and it carries trade-offs. A survey summarizing multi-agent debate notes that a judge can reduce bias, but that long debates are computationally expensive [6]. The same survey notes that LLMs struggle to maintain coherence and relevance over long exchanges [6]. Debate therefore improves reasoning only up to the point where added rounds stop adding coherent content.

Transfer across domains also varies. In the DAAO framework, workflows trained on MATH reached 95.44% on GSM8K, which suggests transfer between related mathematical domains [7]. By contrast, workflows trained only on HumanEval reached 94.65% on code generation but only 54.46% on MATH, a sign of domain-specific overfitting [7]. For practitioners, a topology tuned on one task family should be re-validated before use on another.

## Mechanisms, Cost, and Scalability

The mechanisms behind topology effects are less directly measured than the outcomes. AgentsNet models communication on the LOCAL model from distributed computing, in which agents exchange messages only with immediate neighbors over synchronous rounds and must decide from information aggregated over several rounds [8]. This framing makes the bottleneck explicit: in sparse graphs, information takes multiple rounds to reach distant agents, and the benchmark's global tasks require a round count tied to graph diameter. Its failure analysis points to coordination as the weak point. Strategy coordination poses an essential challenge, with multiple failure cases in the transcripts of LLM agents [9]. Error propagation and information bottlenecks are plausible explanations for these failures, but the corpus does not measure them directly, so they should be read as hypotheses.

Cost is the mechanism with the clearest evidence. Uniform task-level workflows rely on heavy pipelines with many LLM calls and tool uses. They over-process simple queries, which wastes resources and ignores token cost and latency [10]. Debate adds cost in a similar way, because long debates are computationally expensive [6]. The cost effect is therefore driven by how many calls a topology makes per query, not only by how many agents it contains.

## Conditions, Automated Design, and Open Questions

Topology appears to matter most when a task requires global coordination among agents. AgentsNet's global tasks, leader election and consensus, require each agent to exchange information with the whole network, and the benchmark finds its tasks challenging even for the best frontier models [11]. Topology should matter less for simple queries, since overly elaborate structures waste calls on easy inputs [10].

Automated design is one response. Some methods adapt the network topology automatically, rather than fixing it in advance [3]. DAAO takes this route by predicting query difficulty and generating a workflow for each query, so simple queries can use less structure [12]. Its reported cost savings and cross-domain transfer suggest that query-level adaptation is a promising way to balance accuracy and cost [7, 13]. The claim rests on a small set of systems, however, and the corpus does not show how well learned topologies generalize across model families.

Several questions remain open. Matched-budget ablations that vary only the topology are needed, along with direct measurements of error propagation and per-topology token and latency costs. Until these exist, the choice of topology will be made largely by experiment on the target task.

## Conclusion

Communication topology is a real design lever in LLM multi-agent systems, but the size of its effect on accuracy relative to cost is not yet settled. The taxonomy is well established, with centralized, decentralized, hierarchical, and graph-based structures each carrying trade-offs in simplicity, robustness, and coordination [1, 3]. Gains from structured topologies are reported [3, 4], but the corpus contains no controlled comparison that varies only the topology, so the size of the topology effect is not isolated.

For practitioners, the evidence points to a few working rules. Start with the simplest structure that meets the task's coordination needs, since global tasks justify richer connectivity and simple queries do not [10, 11]. Treat debate and other multi-round topologies as costly, because their call count grows with each round [6]. Validate any topology on the target task rather than transferring it from a different domain, given the uneven cross-domain results [7]. Finally, measure tokens, calls, and latency per topology, not only accuracy.

Future work should run matched-budget ablations that vary only the topology across tasks and model sizes, and it should measure error propagation directly rather than infer it from failure cases. Those studies would show whether the gains reported for structured and learned topologies survive when cost is held constant.

## Coverage notes

- How do topologies compare on task performance (accuracy, reasoning, code generation) across benchmarks, and what magnitudes of gains or losses are reported?: The corpus gives few direct head-to-head accuracy numbers across fixed topologies (chain vs star vs fully connected); the retrieved evidence is mostly qualitative.
- What mechanisms explain topology effects, such as error propagation, redundancy/self-correction, information bottlenecks, and context length or token cost?: The corpus has little direct evidence on error propagation or information bottlenecks specifically; mechanisms are mostly inferred from benchmark failure analyses.
- How do topology choices affect cost, latency, and scalability (number of agents, message count, tokens), and what trade-offs do papers report?: Few papers compare cost across fixed topologies at matched agent counts; cost evidence comes from different systems, not controlled topology ablations.

## References

[1] Tran et al. (2025). Multi-Agent Collaboration Mechanisms: A Survey of LLMs. arXiv:2501.06322, p. 16  
[2] Tran et al. (2025). Multi-Agent Collaboration Mechanisms: A Survey of LLMs. arXiv:2501.06322, p. 18  
[3] Grötschla et al. (2025). AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs. arXiv:2507.08616, p. 3  
[4] Grötschla et al. (2025). AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs. arXiv:2507.08616, p. 2  
[5] Li et al. (2026). Multi-Agent Coordination Adaptation via Structure-Guided Orchestration. arXiv:2605.25746, p. 1  
[6] Tran et al. (2025). Multi-Agent Collaboration Mechanisms: A Survey of LLMs. arXiv:2501.06322, p. 22  
[7] Su et al. (2025). Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows. arXiv:2509.11079, p. 7  
[8] Grötschla et al. (2025). AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs. arXiv:2507.08616, p. 5  
[9] Grötschla et al. (2025). AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs. arXiv:2507.08616, p. 9  
[10] Su et al. (2025). Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows. arXiv:2509.11079, p. 2  
[11] Grötschla et al. (2025). AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs. arXiv:2507.08616, p. 10  
[12] Su et al. (2025). Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows. arXiv:2509.11079, p. 1  
[13] Su et al. (2025). Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows. arXiv:2509.11079, p. 8  
