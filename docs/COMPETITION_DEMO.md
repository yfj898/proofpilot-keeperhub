# ProofPilot Competition Demo

This is the shortest competition-facing path through the project. It is intentionally narrower
than the research and benchmark surface.

## One command

Safe default — no broadcast:

```bash
python scripts/run_competition_demo.py
```

Explicit Base Sepolia live execution:

```bash
python scripts/run_competition_demo.py --live
```

`--live` is the only switch on this orchestrator that selects Autonomous mode. Without it, the
runtime is Observe-only.

## Phase 1 — ProofPilot Doctor

Doctor verifies before the AI Agent runtime starts:

- official KeeperHub hosted MCP is reachable;
- required execution/status tools are discovered live;
- Base Sepolia `84532` is present as a stable KeeperHub chain schema;
- Aave V3 protocol actions are discoverable through KeeperHub;
- a KeeperHub EVM wallet integration exists;
- the independent Base Sepolia RPC reports the expected chain;
- the execution wallet has native gas;
- the Aave Pool is readable and current E-Mode is known;
- the external proposal model can be probed without receiving KeeperHub credentials;
- Doctor itself performs zero writes.

## Phase 2 — AI Agent Runtime

```text
User Intent
   ↓
Live LLM ProposedAction
   ↓
Intent Preview
   ↓
ProofPilot deterministic Intent Assurance
   ↓
KeeperHub simulation
   ↓
Observe (default) OR Autonomous (--live)
   ↓
KeeperHub execution/status when live
   ↓
Independent receipt + post-state verification
   ↓
SIMULATED / VERIFIED
```

## Current safe one-command evidence

Observed on 2026-08-09:

- Doctor: `READY`;
- live KeeperHub tool inventory: 35 tools;
- Base Sepolia chain schema: stable;
- live Aave V3 discovery: 7 protocol actions;
- Agent Observe runtime: `SIMULATED`;
- broadcast attempted: `false`;
- consolidated summary: `artifacts/runtime/competition-demo-summary-observe-v3.json`.

The underlying Autonomous path has already been separately exercised and preserved in:

- `artifacts/demo/proofpilot-autonomous-live.json` — `VERIFIED` `0 -> 1`;
- `artifacts/demo/proofpilot-autonomous-cleanup.json` — `VERIFIED` `1 -> 0`.

The one-command orchestrator therefore does not need to emit another transaction during routine
review. `--live` exists for an explicit live competition recording.

## Product roles

```text
AI Agent      decides what action to propose
ProofPilot    determines whether that exact action is authorized
KeeperHub     simulates and reliably executes the authorized action
Verifier      confirms what actually happened onchain
```

KeeperBench and the External Red-Team remain validation evidence and should be shown only after
the working product path is clear.
