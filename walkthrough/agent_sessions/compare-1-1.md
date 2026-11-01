# Agent session `compare-1-1`

compare_workflows Q2 repeat 1: stopped early (truncation)

Exported from runs/agent_memory.db (the agents' shared Memory). Tool results are cut to 300 characters (search hits are paper text). Thinking blocks are shown only as a marker.

### 1. user

Write the literature review for the research question in the current state.

### 2. assistant

**→ record_subquestions**(`{"sub_questions": ["What are the main mechanisms by which multi-agent LLM systems select the next acting agent (e.g., centralized orchestrator/router, LLM-driven self-selection, role-based fixed pipelines, graph/state-machine transitions, auction or bidding schemes), and how does each mechanism work?", "What token, latency, and API-call costs do the different next-agent selection approaches incur,…`)

**→ handoff**(`{"to_agent": "Researcher", "reason": "Four sub-questions recorded covering mechanisms, costs, performance comparison, and failure modes for next-agent selection in multi-agent LLM systems. Please research each and record grounded claims with citations, noting cost figures explicitly for the ML engineer audience."}`)

### 3. tool

Recorded:
1. What are the main mechanisms by which multi-agent LLM systems select the next acting agent (e.g., centralized orchestrator/router, LLM-driven self-selection, role-based fixed pipelines, graph/state-machine transitions, auction or bidding schemes), and how does each mechanism work?
2. Wh …

### 4. tool

Agent Researcher is now handling the request due to the following reason: Four sub-questions recorded covering mechanisms, costs, performance comparison, and failure modes for next-agent selection in multi-agent LLM systems. Please research each and record grounded claims with citations, noting cost …

### 5. assistant

_(thinking block)_

I'll start by searching the corpus for the four sub-questions, since no findings have been recorded yet.

**→ search_corpus**(`{"query": "multi-agent LLM next speaker selection orchestrator router"}`)

**→ search_corpus**(`{"query": "LLM multi-agent conversation speaker selection self-selection"}`)

**→ search_corpus**(`{"query": "multi-agent LLM token cost latency number of agents rounds"}`)

**→ search_corpus**(`{"query": "multi-agent LLM benchmark performance coding math collaborative problem solving"}`)

**→ search_corpus**(`{"query": "multi-agent LLM failure modes error propagation deadlock redundant turns"}`)

### 6. tool

node_id: 2511.20639#013/2
(Latent Collaboration in Multi-Agent Systems, p. 6)
We perform hyperparameter tuning and report the mean performance over three independent runs. Across both baselines and our method, we set all LLM agents with a temperature of 0.6 and a top-p of 0.95. We adjust the maximum …

### 7. tool

node_id: 2507.08616#001/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 1)
Large-language models (LLMs) have demonstrated powerful problem-solving capabilities, in particular when organized in multi-agent systems. However, the advent of such systems also raises several …

### 8. tool

node_id: 2509.11079#019/0
(Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows, p. 8)
4.4.2 LLM Router Analysis. In this section, we validate that DAAO does not exhibit a preference for any particular LLM and demonstrate its ability to generalize well to unseen LLMs witho …

### 9. tool

node_id: 2404.01663#001/0
(CMAT: A Multi-Agent Collaboration Tuning Framework for Enhancing Small Language Models, p. 1)
In the rapid development of the field of artificial intelligence, large language models (LLMs) such as BERT and GPT-4 [1] have become important cornerstones of natural language pr …

### 10. tool

node_id: 2507.08616#003/0
(AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs, p. 2)
LLM-based agents can outperform single agents [9, 38, 53, 29], mirroring aspects of human teamwork. For example, GPTSwarm [53] introduce a graph-based approach inspired by language-based societi …

### 11. assistant

_(thinking block)_
