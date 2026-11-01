# Agent session `compare-0-2`

compare_workflows Q1 repeat 2: stopped early (truncation)

Exported from runs/agent_memory.db (the agents' shared Memory). Tool results are cut to 300 characters (search hits are paper text). Thinking blocks are shown only as a marker.

### 1. user

Write the literature review for the research question in the current state.

### 2. assistant

_(thinking block)_

**→ record_subquestions**(`{"sub_questions": ["What are the main orchestration topologies used in LLM-based multi-agent systems (e.g., centralized/hierarchical orchestrator, peer-to-peer debate, sequential pipelines, role-based teams, graph-structured workflows), and how does each coordinate agent communication and task allocation?", "How do the orchestration patterns compare on control, meaning how much determinism, observ…`)

**→ handoff**(`{"to_agent": "Researcher", "reason": "Five non-overlapping sub-questions are recorded covering topologies, control, cost, robustness, and benchmark evidence. Please search the corpus and record grounded claims per sub-question, then return the findings so the literature review can be written for ML engineers."}`)

### 3. tool

Recorded:
1. What are the main orchestration topologies used in LLM-based multi-agent systems (e.g., centralized/hierarchical orchestrator, peer-to-peer debate, sequential pipelines, role-based teams, graph-structured workflows), and how does each coordinate agent communication and task allocation?
 …

### 4. tool

Agent Researcher is now handling the request due to the following reason: Five non-overlapping sub-questions are recorded covering topologies, control, cost, robustness, and benchmark evidence. Please search the corpus and record grounded claims per sub-question, then return the findings so the lite …

### 5. assistant

_(thinking block)_

**→ search_corpus**(`{"query": "LLM multi-agent orchestration topologies centralized hierarchical peer-to-peer"}`)

**→ search_corpus**(`{"query": "multi-agent debate communication topology LLM agents"}`)

**→ search_corpus**(`{"query": "multi-agent LLM control determinism observability human oversight"}`)

**→ search_corpus**(`{"query": "multi-agent LLM cost tokens latency scaling number of agents rounds"}`)

**→ search_corpus**(`{"query": "error propagation hallucination cascade multi-agent LLM robustness adversarial agents"}`)

**→ search_corpus**(`{"query": "single agent versus multi-agent LLM benchmark comparison equal compute"}`)

### 6. tool

node_id: 2501.06322#015/1
(Multi-Agent Collaboration Mechanisms: A Survey of LLMs, p. 13)
For example, in LEGO [54], in the first state of the framework, 3 agents cooperate to augment information about the current task, and in the second state, a competitive channel is created between an Explainer L …

### 7. tool

node_id: 2511.20639#013/2
(Latent Collaboration in Multi-Agent Systems, p. 6)
We perform hyperparameter tuning and report the mean performance over three independent runs. Across both baselines and our method, we set all LLM agents with a temperature of 0.6 and a top-p of 0.95. We adjust the maximum …

### 8. tool

node_id: 2501.06322#031/0
(Multi-Agent Collaboration Mechanisms: A Survey of LLMs, p. 24)
that integrates LLMs with reconfigurable intelligent surfaces (RIS) to enable energy-efficient and reliable communication in the Internet of Vehicles. In this RIS system, the LLM is used to deduce optimized str …

### 9. tool

node_id: 2505.19591#020/0
(Multi-Agent Collaboration via Evolving Orchestration, p. 10)
We proposed a novel framework for adaptive multi-agent LLM collaboration inspired by puppet show orchestration, where a centralized, learnable "puppeteer" orchestrator dynamically activated agents within a direct …

### 10. tool

node_id: 2507.08616#003/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 2)
LLM-based agents can outperform single agents [9, 38, 53, 29], mirroring aspects of human teamwork. For example, GPTSwarm [53] introduce a graph-based approach inspired by language-based societi …

### 11. tool

node_id: 2501.06322#040/0
(Multi-Agent Collaboration Mechanisms: A Survey of LLMs, p. 29)
Intrinsicly, LLMs can be harmful with hallucinated information. When deployed in MASs, these issues can propagate and amplify through agent interactions. There are two key factors behind this amplification: LLM …

### 12. assistant

_(thinking block)_

**→ search_corpus**(`{"query": "multi-agent LLM framework workflow graph deterministic reproducible controllable agent execution"}`)

**→ search_corpus**(`{"query": "token consumption multi-agent debate more agents more rounds computational overhead"}`)

**→ search_corpus**(`{"query": "voting verification mitigate faulty agents multi-agent LLM failure"}`)

### 13. tool

node_id: 2505.19591#013/0
(Multi-Agent Collaboration via Evolving Orchestration, p. 7)
tion [77, 45]. To investigate whether our approach exhibits a similar pattern, we visualize the average token consumption and the number of orchestrated agents throughout the training process. Token Count Evolutio …

### 14. tool

node_id: 2507.08616#009/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 5)
respond with either Yes or No. The task is solved if there exists exactly one leader. In AGENTSNET, we refer to this task as LEADERELECTION. Graph Problem Round Complexity (∆+ 1)-Coloring Ω(log∗ …

### 15. tool

node_id: 2509.11079#001/0
(Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows, p. 1)
Large Language Model (LLM)-based agentic systems have shown strong capabilities across various tasks. However, existing multiagent frameworks often rely on static or task-level workflows …

### 16. assistant

_(thinking block)_
