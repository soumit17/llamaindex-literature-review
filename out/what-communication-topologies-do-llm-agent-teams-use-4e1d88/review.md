# Communication Topologies in LLM Agent Teams: Structure, Cost, and Performance Trade-offs

> **Question:** What communication topologies do LLM agent teams use, and how does topology affect task performance?  
> Generated 2026-11-01 from 2 papers, 4 cited passages.

## Introduction



## Topology Taxonomy and Routing Design



## Cost Versus Accuracy Trade-offs

Accuracy alone does not capture the differences between collaboration configurations. Varying collaboration dimensions produces an accuracy gap of up to 37.6% across strategies [1], but some strategies with similar accuracy differ substantially in token cost [1]. In the EBFC task, G1-P2-I4-C2 reaches accuracy comparable to G2-P3-I1-C3 while producing 11.5 times more output tokens [1]. A similar pattern appears in the SES scenario, where context strategy C2 incurs much higher token costs than C1 and C3, and C3 shows more stable performance [2].

Latent-space communication shifts this trade-off. LatentMAS reduces token usage by 59.4% to 87.9% relative to TextMAS [3] and achieves a 2.6x to 7x speedup over vLLM-optimized TextMAS [3]. Within LatentMAS, accuracy rises with latent step depth and peaks around 40 to 80 steps, which the authors describe as the best accuracy-efficiency trade-off [4]. These savings are reported against TextMAS and the optimal depth is the authors' characterization, so engineers should treat both as task-dependent until validated on their own workloads.

The cheaper option is not uniformly the weaker one [2]. Because cost varies independently of accuracy in some cases [1], token cost alone is an unreliable proxy for strategy quality, and in the SES scenario the lower-cost context strategy C3 was more stable than the costlier C2 [2].

## When Hierarchy Beats Peer-to-Peer



## Error Propagation and Redundancy



## Evaluation Gaps and Generalization

Accuracy alone is a weak basis for comparing multi-agent frameworks. Six candidate fr

## Conclusion



## Coverage notes

- How do the papers' agent communication topologies (e.g., star, chain, tree, fully connected, dynamic graphs) differ in how they route messages between agents, and what determines which topology a given system chooses?: The excerpts do not describe star, chain, or fully connected routing in detail for most papers, nor explicitly state what criteria determine which topology a given system selects beyond orchestration flexibility and task demands.
- What trade-off between communication cost (tokens, latency, number of calls) and task accuracy do the papers report when moving from sparse to dense agent connectivity?: The excerpts do not compare sparse versus dense agent connectivity. The reported trade-offs concern collaboration strategy configurations, latent versus text communication medium, and latent step depth, not connectivity density. No excerpt reports how communication calls or number of agent links change with connectivity, so the sub-question is not directly answered.
- Under what task properties (e.g., decomposability, need for debate or verification, error propagation risk) do the papers find hierarchical or centralized topologies outperform peer-to-peer ones, and why?: The excerpts do not directly compare hierarchical or centralized topologies against peer-to-peer ones on specific task properties such as decomposability, debate or verification need, or error propagation risk, and do not report empirical outperformance results for these topologies.
- How do the papers' mechanisms for handling error propagation and message redundancy across topologies, such as voting, critic agents, or pruned edges, change the performance gap between topologies?: The excerpts do not report any measured performance gap between topologies with or without voting, critic agents, or pruned edges, and do not compare error-propagation outcomes across topologies directly. They give no quantitative results for AgentsNet topology performance or for how redundancy mechanisms change that gap.
- Which evaluation setups and benchmarks do the papers use to compare topologies, and where do their findings conflict or fail to generalize across models and task domains?: The excerpts do not report results across different backbone LLMs for the topology comparison beyond the stated backbone-capability note, do not name the specific benchmark datasets' task domains beyond SWE-bench-Verified, and do not give per-model comparisons of topologies from other papers in the set.

## References

[1] Wang et al. (2025). Beyond Frameworks: Unpacking Collaboration Strategies in Multi-Agent Systems. arXiv:2505.12467, p. 6  
[2] Wang et al. (2025). Beyond Frameworks: Unpacking Collaboration Strategies in Multi-Agent Systems. arXiv:2505.12467, p. 8  
[3] Zou et al. (2025). Latent Collaboration in Multi-Agent Systems. arXiv:2511.20639, p. 7  
[4] Zou et al. (2025). Latent Collaboration in Multi-Agent Systems. arXiv:2511.20639, p. 9  
