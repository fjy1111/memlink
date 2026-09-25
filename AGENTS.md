# MemLink Agent Instructions

## 1. Project Mission

MemLink is a low-overhead multi-agent communication, shared-state, and cross-task memory runtime.

Chinese project positioning:

> MemLink：面向多智能体协作的低开销通信、共享状态与跨任务记忆运行时。

English positioning:

> A Low-Overhead Multi-Agent Communication & Shared-State Runtime.

MemLink is not primarily a multi-agent chat demo. The runtime itself is the project.

The project has three core goals:

1. **Speak less**
   - Structured inter-agent communication
   - UDS + MessagePack
   - ResultRef instead of repeatedly transmitting large results

2. **Move less**
   - StateRef
   - Shared-memory-backed non-text state transfer
   - Large semantic state should not be repeatedly serialized as text

3. **Repeat less work**
   - Shared memory across related tasks
   - Memory validation
   - Verified Memory Fast Path
   - Measure actual avoided work instead of only memory hits

Do not introduce additional architectural pillars without explicit maintainer approval.

---

## 2. Required Reading

Before making architecture, runtime, communication, state, memory, or benchmark changes, read:

- `docs/PROJECT_VISION.md`
- `docs/ARCHITECTURE_V2.md`
- `docs/DEVELOPMENT_PLAN.md`
- `docs/CLAIMS_AND_GATES.md`
- `docs/RELATED_WORK.md`

Treat these documents as the project-level source of truth.

Existing implementation documents may describe the preliminary version of MemLink. When they conflict with the V2 documents above, do not silently choose one. Report the conflict and follow the current task specification.

---

## 3. Current Development Status

The project already has a working preliminary implementation containing:

- Planner
- Retriever
- Executor
- Reviewer
- text / structured modes
- AgentMessage
- MessagePack serialization
- result references
- NumPy semantic state
- SQLite shared memory
- benchmark and metrics
- FastAPI
- Streamlit
- Windows/openEuler support

However, the preliminary runtime is still mainly single-process and contains direct Python-object data paths.

The national-finals V2 goal is to remove these weaknesses without unnecessarily rewriting working parts of the project.

The unified public benchmark Dataset Layer has already been added for:

- TopiOCQA
- QReCC
- HotpotQA
- MBPP
- HumanEval

Do not rebuild the Dataset Layer unless the current task explicitly requires it.

---

## 4. Architecture Invariants

### 4.1 Independent Agent processes

Planner, Retriever, Executor, and Reviewer must ultimately run as independent processes.

A process boundary must be observable by PID.

### 4.2 Protocol-only cross-Agent business path

Cross-Agent business data must pass through MemLink communication mechanisms.

Do not introduce or preserve hidden business-data bypasses such as:

```text
Planner Python object
        ↓
Retriever direct method call
```

A structured protocol is not considered the real data path if equivalent business objects are still passed directly between Agent implementations.

### 4.3 Control plane and data plane are separate

Control-plane communication carries small structured messages.

Large results and non-text states should use references.

```text
small payload  -> inline MessagePack
large result   -> ResultRef
semantic state -> StateRef
```

### 4.4 Shared-state claims require actual consumption

Creating a `state_id` or shared-memory object is not enough.

The receiving Agent process must receive a StateRef, attach/read the state, validate it, and actually consume it in its computation.

### 4.5 Memory reuse claims require real reuse

A retrieval hit is not equal to successful reuse.

Keep the following concepts separate:

```text
Retrieved
Used / Consumed
Validated
Work Avoided
```

Do not use `memory_hit_count` alone as evidence that memory reduced repeated work.

### 4.6 Fair baseline requirement

Text and structured modes must use, as far as practical:

- the same task
- the same model
- the same Agent roles
- the same tools
- the same process topology
- the same memory policy
- the same benchmark sample
- the same random seed

---

## 5. Scope Discipline

The three core project mechanisms are:

```text
Structured IPC
Shared State
Verified Memory Fast Path
```

Do not migrate the project to:

- LangGraph
- Ray runtime
- Redis
- Milvus
- Kubernetes

Do not make the following competitor-specific ideas the MemLink core:

- hypergraph memory
- learned communication topology
- residual/VLC communication
- Theory-of-Mind prediction
- hidden-state training
- latent communication requiring model-internal modification

Related projects are design references, not implementation templates.

Avoid copying another project's source code, schemas, documentation wording, or architecture wholesale.

---

## 6. Development Environment

The repository uses a project-local Python virtual environment.

### Windows

Use:

```text
.venv\Scripts\python.exe
```

Targeted test:

```powershell
.\.venv\Scripts\python.exe -m pytest <target> -q
```

Full test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

### Linux / openEuler

Use:

```text
.venv/bin/python
```

Do not depend on Conda activation or a global Python interpreter.

---

## 7. Development Workflow

Work in small, reviewable increments.

One development task should:

1. have a narrow scope;
2. state what it must not modify;
3. define explicit acceptance gates;
4. inspect existing code before editing;
5. make the smallest compatible change;
6. add or update focused tests;
7. run targeted tests;
8. run the full regression suite;
9. report modified files and test results;
10. stop when the requested scope is complete.

Do not automatically continue into the next planned task.

Prefer incremental replacement over a full rewrite.

---

## 8. Testing Rules

Do not weaken, delete, skip, or rewrite an existing test merely to make new code pass.

New mechanisms should have positive and negative tests where practical.

Examples:

- worker starts successfully;
- worker stops successfully;
- invalid frame is rejected;
- missing shared-memory state fails explicitly;
- wrong checksum is rejected;
- unavailable receiver is reported;
- irrelevant memory does not trigger a Fast Path.

---

## 9. Developer Role

When acting as the implementation Agent:

- read the required V2 documents first;
- inspect existing implementation before designing new code;
- preserve working interfaces where reasonable;
- avoid unrelated cleanup;
- do not silently expand task scope;
- do not claim completion before all task gates pass;
- report conflicts between requested design and current code.

At the end, report:

- modified files;
- added tests;
- targeted test result;
- full test result;
- acceptance-gate result;
- known limitations.

---

## 10. Reviewer Role

When acting as the review Agent:

Do not assume the implementation report is correct.

Review against:

- `docs/ARCHITECTURE_V2.md`
- `docs/CLAIMS_AND_GATES.md`
- the task-specific acceptance criteria

Specifically look for:

- direct Python-object bypasses;
- fake IPC;
- metrics that measure serialization instead of transport;
- StateRef objects that are created but never consumed;
- memory hits that are reported as work avoidance;
- data leakage from benchmark evaluation fields;
- unfair Text vs Structured comparisons;
- tests that only test mocks instead of the claimed real path;
- resources that are not released;
- process leaks;
- platform-specific hard-coded paths;
- silent fallback that invalidates the experiment;
- claims stronger than the available evidence.

Report findings by severity:

```text
Critical
High
Medium
Low
```

Provide concrete file/function/test references.

---

## 11. Claims Discipline

Never claim a mechanism is implemented only because an interface or class exists.

Do not use the following claims unless their corresponding Gate is satisfied:

- real IPC;
- protocol-only Agent communication;
- zero-copy;
- shared-memory state transfer;
- lower latency;
- lower token usage;
- actual transport-byte reduction;
- memory work avoidance;
- crash recovery;
- production-grade sandbox;
- distributed runtime.

Negative results are valid results.

---

## 12. Benchmark Discipline

The public benchmark Dataset Layer separates runtime input from evaluation data.

Runtime code must not access benchmark gold fields.

Examples of evaluation-only fields include:

- answers;
- alternative answers;
- Gold_passage;
- Rationale;
- supporting facts;
- reference code;
- hidden tests;
- canonical solutions.

For conversational datasets, sample complete conversations rather than random isolated turns.

Default benchmark seed:

```text
2026
```

---

## 13. Git Discipline

Do not commit:

- `.venv`
- `.env`
- API keys
- Hugging Face model files
- raw external datasets
- Hugging Face cache
- pytest temporary directories
- build artifacts
- large generated runtime files

Do not push unless explicitly requested.

One major development task should normally correspond to one clean commit after review.

---

## 14. Definition of Success

The final system should make three things easy to demonstrate and verify:

```text
Speak less
Move less
Repeat less work
```

A smaller mechanism with a real data path and reproducible evidence is preferred over a larger mechanism that only exists at the interface or documentation level.
