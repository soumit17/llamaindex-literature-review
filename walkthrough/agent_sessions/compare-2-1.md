# Agent session `compare-2-1`

compare_workflows Q3 repeat 1: stopped early (truncation)

Exported from runs/agent_memory.db (the agents' shared Memory). Tool results are cut to 300 characters (search hits are paper text). Thinking blocks are shown only as a marker.

### 1. user

Write the literature review for the research question in the current state.

### 2. assistant

_(thinking block)_

**→ record_subquestions**(`{"sub_questions": ["What taxonomy of communication topologies (e.g., chain/pipeline, star/hierarchical, fully connected/debate, tree, graph, dynamic or learned topologies) do multi-agent LLM papers use, and how are they formally defined?", "Which topologies are used in which task families (e.g., code generation, math reasoning, QA, simulation), and what performance differences do the papers report…`)

**→ handoff**(`{"to_agent": "Researcher", "reason": "Five non-overlapping sub-questions recorded covering taxonomy, task-dependent performance comparisons, mechanisms, cost trade-offs, and adaptive/learned topologies. Please search the corpus and record grounded claims per sub-question, noting benchmarks, backbone models, and team sizes for each reported result, for the ML-engineer audience."}`)

### 3. tool

Recorded:
1. What taxonomy of communication topologies (e.g., chain/pipeline, star/hierarchical, fully connected/debate, tree, graph, dynamic or learned topologies) do multi-agent LLM papers use, and how are they formally defined?
2. Which topologies are used in which task families (e.g., code gener …

### 4. tool

Agent Researcher is now handling the request due to the following reason: Five non-overlapping sub-questions recorded covering taxonomy, task-dependent performance comparisons, mechanisms, cost trade-offs, and adaptive/learned topologies. Please search the corpus and record grounded claims per sub-q …

### 5. assistant

_(thinking block)_

I'm the Researcher, so I'll search the corpus for each sub-question before recording findings and handing off to the Writer.

**→ search_corpus**(`{"query": "multi-agent LLM communication topology taxonomy chain star tree graph"}`)

**→ search_corpus**(`{"query": "topology of LLM agent collaboration performance comparison benchmark"}`)

**→ search_corpus**(`{"query": "error propagation in multi-agent LLM systems communication structure"}`)

**→ search_corpus**(`{"query": "token cost latency multi-agent debate number of LLM calls"}`)

**→ search_corpus**(`{"query": "automatically optimize agent communication graph per task"}`)

### 6. tool

node_id: 2507.08616#015/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 7)
For benchmarking, we generate a set of 27 network topologies, consisting of 9 small-world, scale-free, and Delaunay graphs, respectively, ranging in size from 4 to 16 nodes. Concretely, for each …

### 7. tool

node_id: 2507.08616#003/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 2)
LLM-based agents can outperform single agents [9, 38, 53, 29], mirroring aspects of human teamwork. For example, GPTSwarm [53] introduce a graph-based approach inspired by language-based societi …

### 8. tool

node_id: 2507.08616#001/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 1)
Large-language models (LLMs) have demonstrated powerful problem-solving capabilities, in particular when organized in multi-agent systems. However, the advent of such systems also raises several …

### 9. tool

node_id: 2410.21784#014/0
(MARCO: Multi-Agent Real-time Chat Orchestration, p. 6)
In this section we detail the various experiments to evaluate our proposed solution, MARCO, on task specific performance, operational performance (latency, run-time cost), scalability and ablations. (a) Cost of MARS. ( …

### 10. tool

node_id: 2505.11765#007/1
(OMAC: A Holistic Optimization Framework for LLM-Based Multi-Agent Collaboration, p. 3)
• Optimizing agent communication flows (Str-3). This dimension addresses the optimization of communication flows among agents. Specifically, the goal is to optimize an LLM-based controll …

### 11. assistant

_(thinking block)_

**→ search_corpus**(`{"query": "G-Designer task-adaptive multi-agent topology MMLU HumanEval"}`)

**→ search_corpus**(`{"query": "AgentsNet results accuracy decreases with larger networks and LLM coordination"}`)

**→ search_corpus**(`{"query": "structure-guided orchestration adaptive multi-agent coordination redundancy communication cost"}`)

**→ search_corpus**(`{"query": "OMAC optimization framework multi-agent collaboration results across benchmarks"}`)

### 12. tool

node_id: 2605.25746#002/1
(Multi-Agent Coordination Adaptation via Structure-Guided Orchestration, p. 1)
Zhang et al. (2024a) and Talebirad and Nadiri (2023) have formalized multi-agent systems as computational graphs, enabling structural and communication optimization. Methods such as GPTSwarm (Zhu …

### 13. tool

node_id: 2507.08616#019/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 9)
the network increases. For 100-agent networks, performance drops to near zero across the board. As a consequence, the difficulty of AGENTSNET can be gradually increased by considering larger net …

### 14. tool

node_id: 2605.25746#002/1
(Multi-Agent Coordination Adaptation via Structure-Guided Orchestration, p. 1)
Zhang et al. (2024a) and Talebirad and Nadiri (2023) have formalized multi-agent systems as computational graphs, enabling structural and communication optimization. Methods such as GPTSwarm (Zhu …

### 15. tool

node_id: 2505.11765#003/1
(OMAC: A Holistic Optimization Framework for LLM-Based Multi-Agent Collaboration, p. 2)
Furthermore, joint optimization across multiple dimensions is shown to further significantly enhance MAS’s performance. Our key contributions can be summarized as follows: • We introduce …

### 16. assistant

_(thinking block)_

**→ search_corpus**(`{"query": "different topologies perform best for specific tasks multi-agent LLM"}`)

**→ search_corpus**(`{"query": "Difficulty-aware orchestration cost-performance trade-off multi-agent workflow token"}`)

**→ search_corpus**(`{"query": "multi-agent debate fully connected communication redundancy diversity of reasoning"}`)

### 17. tool

node_id: 2505.19591#016/0
(Multi-Agent Collaboration via Evolving Orchestration, p. 9)
paction and cyclicality. The evolving interplay between densely clustered agents and frequent communication cycles marks a significant transformation in multi-agent systems, shifting from loosely organized, explor …

### 18. tool

node_id: 2507.08616#003/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 2)
LLM-based agents can outperform single agents [9, 38, 53, 29], mirroring aspects of human teamwork. For example, GPTSwarm [53] introduce a graph-based approach inspired by language-based societi …

### 19. tool

node_id: 2509.11079#007/2
(Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows, p. 3)
𝜆≥0, (5) where P(𝐺|Q) is a distribution over query-specific workflows, 𝑈(·) and 𝐶(·) denote the utility (e.g., accuracy) and cost (e.g., token usage, latency) of executing workflow 𝐺on q …

### 20. assistant

_(thinking block)_
