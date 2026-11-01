# Agent session `compare-1-2`

compare_workflows Q2 repeat 2: stopped early (truncation)

Exported from runs/agent_memory.db (the agents' shared Memory). Tool results are cut to 300 characters (search hits are paper text). Thinking blocks are shown only as a marker.

### 1. user

Write the literature review for the research question in the current state.

### 2. assistant

**→ record_subquestions**(`{"sub_questions": ["What are the main mechanisms by which multi-agent LLM systems select the next acting agent (e.g., fixed/scripted routing, LLM-based orchestrator or manager, role-based speaker selection, auction/bidding, graph or state-machine transitions, decentralized self-selection), and how do the papers categorize them?", "How do different next-speaker/routing approaches compare on task pe…`)

**→ handoff**(`{"to_agent": "Researcher", "reason": "Five sub-questions recorded covering mechanism taxonomy, performance comparison, cost scaling, selection-step failure modes, and design trade-offs. Please research each and record grounded claims with citations, noting where cost data is missing."}`)

### 3. tool

Recorded:
1. What are the main mechanisms by which multi-agent LLM systems select the next acting agent (e.g., fixed/scripted routing, LLM-based orchestrator or manager, role-based speaker selection, auction/bidding, graph or state-machine transitions, decentralized self-selection), and how do the p …

### 4. tool

Agent Researcher is now handling the request due to the following reason: Five sub-questions recorded covering mechanism taxonomy, performance comparison, cost scaling, selection-step failure modes, and design trade-offs. Please research each and record grounded claims with citations, noting where c …

### 5. assistant

_(thinking block)_

I'll start by searching the corpus for the five sub-questions, since no findings are recorded yet.

**→ search_corpus**(`{"query": "multi-agent LLM speaker selection orchestrator next agent routing"}`)

**→ search_corpus**(`{"query": "LLM multi-agent conversation speaker selection performance comparison"}`)

**→ search_corpus**(`{"query": "multi-agent system token cost latency number of agents scaling"}`)

**→ search_corpus**(`{"query": "multi-agent LLM failure modes orchestrator errors deadlock redundant turns"}`)

**→ search_corpus**(`{"query": "centralized orchestrator versus decentralized agent coordination trade-offs controllability"}`)

### 6. tool

node_id: 2410.21784#001/0
(MARCO: Multi-Agent Real-time Chat Orchestration, p. 1)
Large language model advancements have enabled the development of multi-agent frameworks to tackle complex, real-world problems such as to automate tasks that require interactions with diverse tools, reasoning, and hum …

### 7. tool

node_id: 2410.21784#017/0
(MARCO: Multi-Agent Real-time Chat Orchestration, p. 7)
We presented MARCO, a multi-agent real-time chat orchestration framework for automating tasks using large language models (LLMs) addressing key challenges in utilizing LLMs for complex, multi-step task execution with h …

### 8. tool

node_id: 2509.11079#011/0
(Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows, p. 5)
where 𝑟is the prefix length (the number of top-ranked operators considered). Operators are activated in descending score order (𝑆(1) ≥𝑆(2) ≥· · · ) and the activation proceeds sequential …

### 9. tool

node_id: 2511.20639#013/1
(Latent Collaboration in Multi-Agent Systems, p. 6)
47.7 65.3 66.3 ↑1.0 53.0 75.0 75.3 ↑0.3 64.7 80.3 80.7 ↑0.4 MedQA Token ↓57.5% ↓63.5% ↓46.5% Speed ×2.9 ×2.1 ×2.9 Acc. 63.5 69.8 73.5 ↑3.7 64.8 69.5 74.6 ↑5.1 68.5 72.8 75.7 ↑2.9 MBPP+ Token ↓69.7% ↓68.5% ↓67.4% Speed ×3.7 …

### 10. tool

node_id: 2505.19591#005/0
(Multi-Agent Collaboration via Evolving Orchestration, p. 3)
Centralized Puppeteer A challenge in multi-agent reasoning is achieving efficient orchestration as task complexity and agent diversity increase. In previous approaches, each agent autonomously selects collaborator …

### 11. assistant

_(thinking block)_

The first batch covered orchestration, costs, and coordination trade-offs. I still need targeted evidence on selection-step failures and on speaker-selection baselines.

**→ search_corpus**(`{"query": "speaker selection bias group chat agents round-robin LLM selector"}`)

**→ search_corpus**(`{"query": "multi-agent systems single agent versus multi-agent cost tokens efficiency comparison"}`)

**→ search_corpus**(`{"query": "why multi-agent LLM systems fail taxonomy specification coordination errors"}`)

### 12. tool

node_id: 2507.08616#003/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 2)
LLM-based agents can outperform single agents [9, 38, 53, 29], mirroring aspects of human teamwork. For example, GPTSwarm [53] introduce a graph-based approach inspired by language-based societi …

### 13. tool

node_id: 2505.12467#017/3
(Beyond Frameworks: Unpacking Collaboration Strategies in Multi-Agent Systems, p. 7)
Token costs also follow a similar pattern to the PDDP task, with G2 demonstrating greater efficiency in terms of output token usage. Participation For the PDDP task, Table 3 reveals that P1 …

### 14. tool

node_id: 2508.00032#011/0
(Strategic Communication and Language Bias in Multi-Agent LLM Coordination, p. 7)
10 Round Number Option B (-1) -0.5 0.5 Option A (1) Average Strategy Value Llama 4 Maverick 10 Round Number Option B (-1) -0.5 0.5 Option A (1) Average Strategy Value GPT-4o conventional (comm …

### 15. assistant

_(thinking block)_
