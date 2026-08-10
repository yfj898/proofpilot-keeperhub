# Official KeeperHub MCP Runtime

**Date verified:** 2026-08-09  
**Runtime endpoint:** `https://app.keeperhub.com/mcp`  
**Role:** ProofPilot's onchain execution surface  
**Development-only MCP:** `coding-tools-mcp` is not part of the product runtime

## Why this distinction matters

ProofPilot uses two unrelated tool paths during development:

```text
Development only
GPT / coding agent
    ↓
coding-tools-mcp
    ↓
repository files + test commands

Competition runtime
User intent
    ↓
ProofPilot
    ↓
KeeperHub official hosted MCP
    ↓
Base Sepolia / Aave / ERC-20
```

The custom Coding MCP exists only so a remote coding agent can inspect and modify the repository.
It is not in the transaction path, is not required to run ProofPilot, and is not presented as a
KeeperHub replacement.

## Official hosted MCP live preflight

ProofPilot includes a read-only check:

```bash
python scripts/keeperhub_mcp_check.py
```

The check performs only:

1. MCP `initialize`;
2. MCP `tools/list`;
3. KeeperHub `list_integrations`.

It does **not** simulate, sign, submit, or broadcast a transaction.

Observed live result on 2026-08-09:

```text
endpoint                         https://app.keeperhub.com/mcp
initialize HTTP                  200
negotiated MCP protocol          2025-11-25
tools discovered                 35
required tools present           true
wallet integration present       true
write performed                  false
```

Machine-readable artifact:

```text
artifacts/runtime/keeperhub-mcp-check.json
```

The artifact contains no bearer token or integration credential.

## Required agent-native tools verified live

The live `tools/list` inventory contained all ProofPilot runtime requirements:

- `execute_contract_call`
- `get_direct_execution_status`
- `list_integrations`
- `get_wallet_integration`
- `tools_documentation`
- `list_action_schemas`
- `search_protocol_actions`
- `execute_protocol_action`

The same inventory also exposed `execute_transfer`, `execute_check_and_execute`, and
`execute_workflow`.

This means the runtime integration is MCP-native tool discovery/invocation rather than a custom
HTTP wrapper that redefines KeeperHub's tool schema.

## Aave read-only runtime check

After the final Aave External Red-Team run, ProofPilot used the same official hosted MCP to perform
an Aave V3 Pool `getUserEMode(address)` read on Base Sepolia.

Observed result:

```text
chain_id       84532
function       getUserEMode(address)
result         0
broadcast      false
```

This confirms the red-team benchmark remained simulation-only and left the Aave E-Mode state at
the pre-run value.

## Runtime write rule

For a state-changing action, ProofPilot's intended sequence remains:

```text
typed Intent IR
    ↓
ProofPilot semantic admission
    ↓
KeeperHub execute_contract_call(simulate=true)
    ↓
require success=true AND wouldRevert=false
    ↓
freshness / precondition re-check
    ↓
KeeperHub execute_contract_call(..., idempotency_key=...)
    ↓
get_direct_execution_status
    ↓
independent receipt + post-state verification
    ↓
ExecutionTrace v2
```

The independent Base RPC is read-only and is used only as a second evidence source after KeeperHub
execution.

## Official references

- KeeperHub MCP Server docs: `https://docs.keeperhub.com/ai-tools/mcp-server`
- KeeperHub Hackathon Quickstart: `https://docs.keeperhub.com/quickstart`
- KeeperHub Direct Execution API / simulation semantics:
  `https://docs.keeperhub.com/api/direct-execution`

KeeperHub's current documentation recommends the hosted remote MCP endpoint and documents direct
execution, protocol actions, execution monitoring, OAuth / organization API-key authentication,
and dry-run simulation on the same execution layer.
