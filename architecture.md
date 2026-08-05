# Architecture — K4 Multi-Agent E-commerce Dispute Resolution (A2A + MCP)

Cohort **K4**, policy **EC_POLICY_V2**. 7 agents, 1 shared MCP data server, all local (Ollama).

## 1. Design principle: deterministic engine behind MCP tools, LLM on top

`EC_POLICY_V2` (README.md §4) is a fully specified table + formulas, not a judgment call, and
grading hard-gates schema/evidence violations to zero. A 4B quantized local model is not reliable
at exact date-diff-in-hours arithmetic, 2-decimal BRL sums, or self-formatted evidence-ID strings.
So:

- **All arithmetic, joins, policy-table application and evidence-ID formatting** live in tested,
  pure-Python code (`src/mcp_server/policy_engine.py`), unit-tested against real order_ids from
  `data/` for every one of the 6 primary-issue branches (`tests/test_policy_engine.py`).
- That code is exposed as **MCP tools** — the single source of truth every agent grounds itself
  against. No agent is allowed to invent a fact, an ID, or a number that didn't come back from a
  tool call.
- **The LLM's job** (local Qwen3.5-4B via Ollama) is narration and judgment, not arithmetic: the
  Policy Agent asks it for a short Vietnamese rationale explaining *why* the deterministic decision
  follows from the evidence — the decision itself is never touched by the LLM. Every other agent is
  pure retrieval (nothing to judge), which also keeps a 50-ticket batch fast (~10s/case, dominated
  by one LLM call).

## 2. Components

```
                         ┌─────────────────────────┐
                         │   MCP data server        │  streamable-http :8765
                         │  (src/mcp_server/server.py)│
                         │  tools: get_order,        │
                         │  get_customer_context,     │
                         │  get_affected_entities,    │
                         │  get_product_context,      │
                         │  get_delivery_analysis,    │
                         │  get_payment_reconciliation,│
                         │  apply_policy,              │
                         │  validate_case_output       │
                         └─────────────▲───────────────┘
                                       │ MCP tool calls (every agent below)
      ┌────────────┬────────────┬─────┴──────┬────────────┬─────────────┐
      │            │            │            │            │             │
 ┌────▼───┐  ┌─────▼─────┐ ┌────▼────┐ ┌─────▼────┐ ┌─────▼────┐  ┌─────▼─────┐
 │Customer│  │Order&Product│ │ Payment │ │ Delivery │ │  Policy  │  │ Verifier  │
 │ :9101  │  │   :9102     │ │  :9103  │ │  :9104   │ │  :9105   │  │  :9106    │
 └────┬───┘  └──────┬──────┘ └────┬────┘ └────┬─────┘ └────┬─────┘  └─────┬─────┘
      │             │             │           │            │              │
      └─────────────┴──────┬──────┴───────────┘            │              │
                            │ A2A handoff (JSON-RPC message/send)         │
                     ┌──────▼───────┐                                    │
                     │ Coordinator   │───────────────────────────────────┘
                     │    :9100      │  sequences: 4 evidence agents (parallel)
                     └──────┬────────┘  → policy → verifier (bounded 1 retry)
                            │
                     output/EC_xxx.json + logging/trace.jsonl
```

Every box is a **real, independently-addressable HTTP service**: a GET
`/.well-known/agent-card.json` (Agent Card: name, description, url, skills) and a POST `/a2a`
implementing the A2A `message/send` JSON-RPC method (`src/a2a_common/protocol.py`,
`src/agents/base.py`). `scripts/run_agents.py` boots the MCP server and all 7 agent services
concurrently (one Python process, 8 asyncio-concurrent servers, distinct ports — simpler process
management on Windows than 8 OS processes, while each remains a separately addressable service).

**Note on the A2A layer**: the installed `a2a-sdk` (1.1.2) turned out to be a full production
SDK — gRPC/REST/JSON-RPC transports, DB-backed task stores with Alembic migrations, push
notifications, auth flows — built for long-running, resumable agent tasks, not a synchronous
single-shot batch classifier. Rather than spend the competition window wiring its task-lifecycle
machinery for zero rubric benefit, the actual **wire contract** it exposes — Agent Card discovery +
JSON-RPC `message/send` carrying a structured handoff message — was hand-implemented directly on
Starlette/httpx. Every agent is still a genuine separate HTTP service with a card and a JSON-RPC
endpoint; what's skipped is the SDK's task-persistence runtime, which this use case doesn't need.

## 3. Agent roles, data access and handoff contract

Every handoff (`src/a2a_common/protocol.py: HandoffPayload`) carries the lab's minimum contract:
`ticket_id`, `question`, `facts` (with source evidence IDs), `evidence_ids`, `missing`, `next_action`,
and an optional `note` (LLM rationale, Policy Agent only).

| Agent | Port | MCP tools called | Produces | Uses LLM |
|---|---|---|---|---|
| Customer | 9101 | `get_customer_context` | `customer_context` (unique_id, related_order_ids) | No |
| Order & Product | 9102 | `get_affected_entities`, `get_product_context` | `affected_entities`, `product_context` | No |
| Payment | 9103 | `get_payment_reconciliation`, `get_affected_entities` | `payment_reconciliation` | No |
| Delivery | 9104 | `get_delivery_analysis` | `delivery_analysis` | No |
| Policy | 9105 | `apply_policy` | full case body (`case_assessment`, `root_cause_analysis`, `financial_resolution`, `resolution_actions`, `evidence_ids`) + rationale `note` | **Yes** — narration only |
| Verifier | 9106 | `validate_case_output` | `{valid, violations}` — schema, array limits (README §6), evidence-ID grounding against source CSVs | No |
| Coordinator | 9100 | (A2A client only) | sequences the above, assembles final JSON, writes `output/` + `trace.jsonl` | No |

**Flow per ticket**: Coordinator fans out to Customer / Order&Product / Payment / Delivery in
parallel (`asyncio.gather`, independent evidence — no ordering dependency) → merges their facts and
hands off to Policy → hands the resulting case to Verifier → if Verifier reports violations, one
bounded retry back to Policy (the engine is deterministic, so a retry only helps if it was a
transient MCP hiccup; a still-failing case is written anyway with the violation logged in
`trace.jsonl` rather than silently dropped — the submission must always contain exactly 50 files).

**Access control**: every agent only calls the MCP tools listed above — e.g. the Delivery Agent has
no path to payment data, the Payment Agent has no path to delivery dates. The Verifier is the only
agent with schema/evidence authority; it is the last gate before a case is ever written to `output/`.

## 4. Confidence heuristic

README §6 doesn't define a formula for `case_assessment.confidence`. `policy_engine.compute_confidence`
starts at 0.95 for a clean single-branch match and steps down for thin/ambiguous data (order with no
item rows, unreconciled payment, or a case that fell through to the defensive fallback branch instead
of matching one of the 6 primary-issue conditions cleanly). Documented here rather than left to the
LLM to invent, so it's reproducible.

## 5. Model / runtime

- **Model**: `qwen3.5-4b-ec` — Qwen3.5-4B-Q4_K_M, imported into Ollama from an existing LM Studio GGUF
  (`ollama/Modelfile.qwen35`) rather than re-downloaded. 4B params, well under the 10B/agent limit;
  fits the laptop's 6GB VRAM.
- **Used by**: Policy Agent only, one call per case, for the natural-language rationale — never for
  classification, arithmetic, or evidence IDs.
- Declared in code (`src/config.py`), mirrored into `logging/metadata.json` per submission rules
  (not `.env`).

## 6. How to run

```bash
python scripts/run_agents.py   # boots MCP server (:8765) + all 7 agent services (:9100-9106)
python scripts/run_batch.py    # in a second terminal: runs all 50 input/EC_*.json, writes output/, trace.jsonl, metadata.json
pytest                          # policy engine + MCP tool unit tests
```
