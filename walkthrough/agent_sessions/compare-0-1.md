# Agent session `compare-0-1`

compare_workflows Q1 repeat 1: stopped early (truncation)

Exported from runs/agent_memory.db (the agents' shared Memory). Tool results are cut to 300 characters (search hits are paper text). Thinking blocks are shown only as a marker.

### 1. user

Write the literature review for the research question in the current state.

### 2. assistant

**→ record_subquestions**(`{"sub_questions": ["What orchestration patterns (e.g., centralized/manager, decentralized/peer-to-peer, hierarchical, sequential pipelines, debate/voting, role-based teams) are used in LLM-based multi-agent systems, and how does each define agent communication and control flow?", "How do different orchestration patterns compare in terms of control and controllability (predictability of execution, …`)

**→ handoff**(`{"to_agent": "Researcher", "reason": "Five sub-questions recorded covering patterns, control, cost, robustness, and design trade-offs. Please search the corpus and record grounded claims for each sub-question, noting where evidence is thin or conflicting."}`)

### 3. tool

Recorded:
1. What orchestration patterns (e.g., centralized/manager, decentralized/peer-to-peer, hierarchical, sequential pipelines, debate/voting, role-based teams) are used in LLM-based multi-agent systems, and how does each define agent communication and control flow?
2. How do different orchestr …

### 4. tool

Agent Researcher is now handling the request due to the following reason: Five sub-questions recorded covering patterns, control, cost, robustness, and design trade-offs. Please search the corpus and record grounded claims for each sub-question, noting where evidence is thin or conflicting..
Please  …

### 5. assistant

_(thinking block)_

I need to correct my last step: I called a `record_subquestions` tool that isn't in my toolset, and I handed off to "Researcher," which is my own role. The sub-questions came from me, not the Planner. Nothing has been recorded from the corpus yet, so I'll run the searches now before any review can be written.

**→ search_corpus**(`{"query": "LLM multi-agent orchestration patterns centralized decentralized hierarchical communication"}`)

**→ search_corpus**(`{"query": "multi-agent debate voting role-based agent teams LLM"}`)

**→ search_corpus**(`{"query": "multi-agent LLM token cost latency compared to single agent"}`)

**→ search_corpus**(`{"query": "error propagation hallucination cascade multi-agent LLM robustness topology"}`)

**→ search_corpus**(`{"query": "controllability predictability debuggability multi-agent LLM workflow design"}`)

### 6. tool

node_id: 2507.08616#003/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 2)
LLM-based agents can outperform single agents [9, 38, 53, 29], mirroring aspects of human teamwork. For example, GPTSwarm [53] introduce a graph-based approach inspired by language-based societi …

### 7. tool

node_id: 2501.06322#020/0
(Multi-Agent Collaboration Mechanisms: A Survey of LLMs, p. 16)
Overall, the communication structure of multi-agent collaboration can be categorized into four main classes, referred to as 1) Centralized topology, 2) Decentralized and distributed topology, and 3) Hierarchica …

### 8. tool

node_id: 2410.21784#015/0
(MARCO: Multi-Agent Real-time Chat Orchestration, p. 6)
(claude-3-sonnet) 94.48 ± 0.59 5.61 66.34 ± 0.82 4.07 Retail-Conv dataset With All Reflection Guardrails (retries=2) No Guardrails (retries=0) Model Name Accuracy (%) ± Std dev Latency (secs) Accuracy (%) ± Std dev Lat …

### 9. tool

node_id: 2507.08616#003/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 2)
LLM-based agents can outperform single agents [9, 38, 53, 29], mirroring aspects of human teamwork. For example, GPTSwarm [53] introduce a graph-based approach inspired by language-based societi …

### 10. tool

node_id: 2509.11079#003/1
(Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows, p. 2)
To enhance efficiency and adaptability, we incorporate a cost- and performance-aware LLM router that dynamically assigns heterogeneous models to different operators according to query di …

### 11. assistant

_(thinking block)_

### 12. user

Write the literature review for the research question in the current state.

### 13. assistant

_(thinking block)_
