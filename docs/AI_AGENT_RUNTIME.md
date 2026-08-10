# ProofPilot AI Agent Runtime

Status: **live Base Sepolia path verified on 2026-08-09**

## Purpose

The competition runtime now contains a real LLM proposal layer instead of having ProofPilot
construct the same transaction that it later verifies.

The authority split is deliberate:

```text
User intent
   ↓
Typed Intent IR / delegation boundary
   ↓
KeeperHub Official MCP tools/list
   ↓
External LLM proposal agent
   ↓ candidate only; no KeeperHub credentials or direct tool access
ProposedAction
   ↓
ProofPilot deterministic Intent Assurance
   ├── mismatch / malformed / abstain -> BLOCKED, no write
   └── exact match
          ↓
       KeeperHub Official MCP simulation
          ↓
       freshness re-read
          ↓
       explicit --execute only
          ↓
       KeeperHub Official MCP execution + status
          ↓
       independent receipt + post-state verification
```

The model decides what action to propose. It does **not** decide whether that action is authorized.

## Live KeeperHub discovery

The canonical demo calls the hosted KeeperHub MCP endpoint and performs `tools/list` before asking
the LLM to propose an action. The model-visible inventory is derived from that live response rather
than from a hard-coded fake tool list.

The verified run discovered 35 KeeperHub tools in total and exposed this bounded subset to the
proposal model:

- `execute_contract_call`
- `execute_protocol_action`
- `get_direct_execution_status`
- `list_action_schemas`
- `search_protocol_actions`

The LLM selected `execute_contract_call` for the Aave E-Mode action.

## Model boundary

Default model for the current competition demo:

```text
deepseek-ai/deepseek-v4-flash-0731
```

The provider uses NVIDIA's OpenAI-compatible chat-completions surface already configured for the
project. The model receives the declared user intent, current Base Sepolia Aave state, the bounded
Aave action ABI, live-discovered KeeperHub tool names/descriptions, and a strict JSON proposal
schema.

It does **not** receive the KeeperHub credential, wallet private keys/seed material, direct
KeeperHub MCP tool access, authority to bypass ProofPilot, or authority to broadcast.

The model may `abstain`. Invalid JSON, an undiscovered execution tool, a function outside the
supplied ABI, malformed ABI arguments, or an Intent Assurance mismatch all fail closed before a
KeeperHub write.

## Commands

Simulation-only AI Agent path:

```bash
python scripts/demo_proofpilot.py --agent
```

Explicit testnet execution after all gates pass:

```bash
python scripts/demo_proofpilot.py --agent --execute
```

The existing deterministic reference mode remains available for reproducibility and cleanup:

```bash
python scripts/demo_proofpilot.py
```

The adversarial demonstration remains separately hard-locked to simulation-only:

```bash
python scripts/demo_proofpilot.py --attack
```

## Verified AI Agent simulation

Artifact:

`artifacts/demo/proofpilot-agent-simulation-20260809.json`

Observed path:

```text
pre-state E-Mode: 0
LLM decision: propose
selected KeeperHub tool: execute_contract_call
candidate: setUserEMode(1)
ProofPilot Intent Assurance: PASS
KeeperHub simulation: success=true, wouldRevert=false
broadcast_attempted: false
final status: SIMULATED
```

## Verified AI Agent real execution

Artifact:

`artifacts/demo/proofpilot-agent-live-20260809.json`

Observed path:

```text
pre-state E-Mode: 0
LLM: DeepSeek V4 Flash
LLM decision: propose
selected KeeperHub tool: execute_contract_call
candidate: setUserEMode(1)
ProofPilot Intent Assurance: PASS
KeeperHub simulation: PASS
pre-broadcast freshness: PASS
KeeperHub terminal status: completed
independent receipt: PASS
independent post-state: E-Mode 1
final status: VERIFIED
```

Transaction:

`0x59b215cd9148228b6f97b587a1197a563c55150fa2739f4758c12fe921c43683`

## Cleanup / repeatability

After the live AI Agent run, the same guarded ProofPilot/KeeperHub runtime restored the testnet
account from E-Mode `1` to `0` using the deterministic reference path.

Cleanup transaction:

`0x848ca78e8bbde0f24563582a67b6c94bb53616de79218c5b29542d97bcf8860b`

Artifact:

`artifacts/demo/proofpilot-agent-live-cleanup-20260809.json`

Independent post-state verification confirmed E-Mode `0`.

## Competition differentiation

This runtime is not a second-model critic pattern. A model does not vote on another model's
safety. The authorization result comes from deterministic comparison with the typed user mandate:

```text
LLM Agent: proposes what to do
ProofPilot: determines whether the proposal is semantically authorized
KeeperHub: reliably simulates and executes authorized actions
Independent read layer: verifies what actually happened
```
