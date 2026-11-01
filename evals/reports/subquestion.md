# SubQuestionQueryEngine on 3 questions

## How do centralized orchestrators and decentralized peer-to-peer designs differ for LLM agent teams?

The main difference is where control sits. In a centralized design, one hub directs the team. In a decentralized peer-to-peer design, control is spread across the agents.

**Control and structure**
- **Centralized:** A central orchestrator connects to every agent in a star structure and manages all interactions. It decides which agent acts at each step, plans and re-plans the work, and delegates subtasks to specialists such as web browsing, file navigation, or code execution. Systems like Magentic-One follow this pattern.
- **Decentralized:** Agents work from local information and limited exchanges with their neighbors, so the overall strategy emerges from repeated local interactions. No single agent directs the team.

**Task assignment**
- **Centralized:** The orchestrator makes the assignments. Some designs use a learned policy, trained with reinforcement learning, to sequence agent activations as the task changes. Others use a management agent to assign roles, or an orchestrator that builds a task graph and decides which steps run in parallel or in sequence.
- **Decentralized:** Work is usually divided by expertise, such as medical specialties or software roles like product manager, designer, and programmer. Roles and channels can also be assigned dynamically based on each agent's strengths. In self-organized systems, the team grows by adding agents rather than by having one agent understand the whole task.

**Communication**
- **Centralized:** Communication runs through channels that the orchestrator defines, often as edges in a graph that set both task dependencies and collaboration paths. The resulting structures tend to be compact and cyclic.
- **Decentralized:** Agents message their immediate neighbors directly, often in synchronous rounds. Common patterns include multi-agent debate over a fixed number of rounds and dynamic directed acyclic graphs for certain reasoning tasks. The best structure depends on the task and the mix of agents.

**Conflict resolution**
- **Centralized:** The material does not describe a dedicated mechanism for resolving disagreements. The closest equivalent is a final consolidation step, where a delegating agent gathers the completed results and forms the answer.
- **Decentralized:** The material does not describe a specific mechanism either. It notes that competition between agents can cause conflicts, and it suggests rule-based, role-based, or model-based protocols to keep interactions constructive. It also warns that poorly designed competitive channels can perform worse than a single agent with strong prompts.

**Evidence on performance and cost**
Centralized orchestrator teams have reported results, including accuracy and cost comparisons on benchmarks such as MMLU-Pro, HumanEval, and GSM-Hard. The material does not report latency or cost figures specifically for decentralized peer-to-peer teams, so the two designs cann

Sources: 2406.08979, 2501.06322, 2505.19591, 2507.08616, 2605.25746, 2606.13598, ?

## What mechanisms do multi-agent systems use to reduce hallucinations passed between agents?

Multi-agent systems use several mechanisms to keep hallucinations from spreading between agents:

**Dedicated verification and review.** A checker or verifier agent reviews a solver agent's output, catches hallucinations, and sends the work back for correction before it propagates. Review-and-revise loops, such as the Actor-Evaluator-Self-Reflection pattern, follow the same logic: one agent produces output, another rates it and gives feedback. In GameGPT, a task reviewer checks task types and arguments, and a code reviewer inspects generated code.

**Multi-round debate.** Several LLM instances debate over a fixed number of rounds, which can improve factuality and reasoning.

**Majority voting.** Outputs from several agents are combined by vote, similar to ensemble methods. However, one study found that voting can underperform the best single agent when misleading information from other agents interferes, so aggregation does not always help.

**Adaptive verification.** Some systems learn when to verify, invoking checks more often on complex reasoning steps and skipping them on simpler ones to balance accuracy against cost.

**Structured communication.** Rather than free-form dialogue, which can distort information over several rounds, agents exchange standardized documents and diagrams. This leaves less room for drift or irrelevant content.

**Controlled message channels.** A shared message pool with a subscription mechanism lets each agent receive only task-relevant information, which limits how far errors can travel.

**Testing and candidate selection.** GameGPT generates several candidate code snippets, tests them in a virtual environment, and removes failing ones, so only viable code is executed. This relies on external checks rather than trusting any single generation.

**Decomposition and constrained inputs and outputs.** Breaking work into smaller units gives the model less room to drift. GameGPT also restricts task classification to a predefined list and uses templates for each task type.

**Human input.** When required information cannot be inferred reliably, the system can ask the user for it, and user feedback can help filter candidate outputs.

Overall, these mechanisms work best in combination. Detection and correction of individual agents' mistakes, together with control over how agents communicate, are both needed to stop errors from cascading. Evidence for how well these mechanisms reduce hallucinations is limited: some are proposed without testing, and GameGPT reports its safeguards without measured results.

Sources: 2306.03314, 2308.00352, 2310.08067, 2406.08979, 2501.06322, 2502.14743, 2505.12467, 2605.25746, ?

## How is the communication topology between agents chosen or learned?

Communication topology between agents can be set in several ways, from fixed design to learned adaptation.

**Chosen by design:**
- **Physical deployment:** The topology may simply follow how the agents are physically arranged.
- **Heuristic design:** Designers can specify the structure by hand using rules of thumb.
- **Network-inspired patterns:** Communication paradigms such as memory, report, relay, and debate can be matched to network shapes such as bus, star, ring, and tree.
- **Organizational arrangement:** The structure can be centralized, decentralized, or hierarchical, depending on the desired balance of resilience, efficiency, and complexity.

**Learned or adapted:**
- **Learned orchestration:** A learnable orchestrator, trained with REINFORCE, selects which agent to activate at each reasoning step based on the current state. The topology emerges during reasoning, and it becomes more compact and cyclical as training progresses.
- **Learned structures:** GPTSwarm and G-Designer learn adaptive communication structures or interaction patterns, and graph neural networks can automate role-specific communication structures.
- **Topology optimization and adaptive control:** Methods can optimize the network structure to reduce redundancy, or let the topology change over time in response to conditions.
- **Query-specific adaptation:** For a given query, the system can infer a task-specific multi-agent structure.
- **Inference-time selection:** Agents can be chosen dynamically during inference, with an early-stopping mechanism to improve efficiency.
- **Learned communication:** Protocols such as DIAL, BiCNet, and SchedNet are learned and retained after training, and CommNet learns sparse communication. When to communicate can also be learned.

**Weighting rather than rewiring:** Attention can weight incoming messages without changing which connections exist, typically combined with broadcasting. This does not reduce communication overhead.

The available information does not establish which learning method, such as gradient-based optimization, reinforcement learning, or structure search, is used in each case, nor does it show whether learned topologies outperform fixed ones.

Sources: 2405.14314, 2501.06322, 2502.14743, 2505.12467, 2505.19591, 2605.25746, ?

Cost: $0.0162

## Notes (yours)

- Were the generated sub-questions the ones you'd have asked? (The console log shows them.)
- What can't you control here that Workflow 2's explicit plan -> research steps will let you?
