# AGENTS.md — ProofPilot Engineering Rules

## Goal

Build a hackathon-ready, verifiable onchain execution agent for KeeperHub Agents Onchain.

## Product principle

The model may propose actions, but **only deterministic policy checks + successful simulation may authorize an onchain write**.

## Safety / scope

- Default network: Base Sepolia (`84532`).
- Keep the hackathon prototype on testnet.
- Never commit API keys, OAuth tokens, wallet secrets, seed phrases, or private keys.
- Never bypass KeeperHub simulation for state-changing EVM actions in the MVP.
- Treat every MCP/tool error during preflight as a hard stop.
- Use unique idempotency keys for real executions.
- Bound polling/retries; no infinite retry loops.
- Never claim success until both execution status and postcondition verification pass.

## Architecture boundaries

- `mandate_compiler`: natural language/candidate fields -> typed Intent IR. It has no transaction authority.
- `delegation`: deterministic containment; a sub-mandate cannot expand parent permissions/budget.
- `adapters`: protocol-specific state extraction/outcome semantics; core verifier remains protocol-agnostic.
- `planner`: intent -> structured plan. No direct transaction authority.
- `policy`: deterministic checks; model cannot override this layer.
- `reader`: obtains pre/post state through a read surface (KeeperHub/Blockscout-compatible read path).
- `executor`: KeeperHub MCP only for writes in MVP.
- `verifier`: receipt + postcondition verification.
- `recovery`: classifies failures and chooses stop/retry/re-plan within a strict retry budget.
- `proof`: immutable-ish local execution record for demo/audit.
- `keeperbench_attackers`: source-separated held-out mutations; must not import the ProofPilot defender.

## MVP success definition

A run is successful only if:

1. preconditions were recorded;
2. policy passed;
3. KeeperHub simulation passed (`success=true`, `wouldRevert=false` where applicable);
4. a real Base Sepolia transaction was broadcast through KeeperHub;
5. KeeperHub reports terminal success;
6. a postcondition read confirms the intended state change;
7. transaction link/hash is persisted in the proof bundle.

## Avoid premature complexity

Do not add A2A, ERC-8004 reputation, x402/MPP payments, a large frontend, or many DeFi protocols until the core verification loop works end-to-end.

## Sources of truth

Use current official documentation first:

- KeeperHub Hackathon Quickstart
- KeeperHub MCP Server reference
- KeeperHub Agents page
- KeeperHub prior hackathon retrospective
- MCP 2026-07-28 specification release notes
- OpenAI GPT-5.6 official release notes

See `docs/SOURCES.md`.

