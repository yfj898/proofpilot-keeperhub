# DoraHacks Submission Copy — ProofPilot

## Project

**ProofPilot — Intent Firewall for Autonomous Onchain Agents**

**Tagline:** Semantic authorization between bounded AI proposals and KeeperHub execution.

## Problem

> **Executable transactions can still violate a user's semantic authorization.**

An agent can produce a contract-valid action that KeeperHub successfully simulates, yet the action
can still differ from the user's explicit mandate. For example, Aave `setUserEMode(0)` may be
non-reverting while the user authorized category `1`. Execution safety and authorization are
different questions.

## Solution

ProofPilot is a **multi-protocol semantic authorization prototype**. It converts a bounded user
mandate into typed, machine-checkable constraints, previews the candidate effect, and
deterministically compares the AI agent's proposal with the authorized chain, target, function,
arguments, native value, state conditions and forbidden effects.

```text
User mandate
  -> bounded AI proposal agent
  -> ProofPilot deterministic authorization
  -> KeeperHub simulation and execution
  -> independent receipt, event and post-state verification
```

The agent proposes an action for a bounded user mandate. ProofPilot determines whether that
proposal is authorized. KeeperHub executes the authorized action. The model has no wallet key,
KeeperHub credential or direct write tool.

## Why KeeperHub

KeeperHub provides the reliable simulation and execution layer; ProofPilot adds the missing
semantic authorization boundary. The build uses KeeperHub's official hosted MCP for live discovery,
`execute_contract_call` simulation/execution and direct-execution status. KeeperHub is the sole
write path. The independent Base RPC is read-only and verifies what happened after execution.

For Base Sepolia Aave, the runtime uses generic `execute_contract_call`; Aave catalog discovery is
not presented as Base Sepolia Aave-plugin support.

## Working Build

Safe reviewer path (Observe mode, never broadcasts):

```bash
python scripts/run_competition_demo.py
```

The path performs the runtime Doctor, requests a bounded proposal, shows the candidate preview,
runs deterministic authorization and—only if prior gates pass—asks KeeperHub to simulate. External
provider, parse or ABI-binding errors fail closed. The final credentialed validation reached Doctor
`READY`, then safely stopped on an ABI-binding failure with `broadcast=false`; it was not retried to
obtain a prettier result.

Tests and compile checks:

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall src scripts tests
python scripts/check_submission_hygiene.py
```

Current frozen snapshot: **155 tests PASS**, compile PASS and submission hygiene PASS.

## Real Base Sepolia Evidence

- Hardened Aave E-Mode `0 -> 1`: [transaction](https://sepolia.basescan.org/tx/0xdb0bc80711a6aa167038f990471ff59895f2661a1067df11ab46a48518946f90)
- Hardened cleanup `1 -> 0`: [transaction](https://sepolia.basescan.org/tx/0x2f42aefeed93e25df81b90a4e56b08698ffaf407f0f8ae7a6c970157a3a64780)
- Current test-account Aave E-Mode: **0**

Both hardened traces reached `L2_EXECUTION_EFFECT_VERIFIED`: KeeperHub completion, independent L2
receipt, execution/effect binding, the expected Aave `UserEModeSet` event and post-state agreed.
This is not a full internal-call trace, proof of every inner calldata value or L1 finality.

## Final Frozen External Red-Team

Artifact:
`artifacts/keeperbench/external-redteam-aave-formal-20260809-25x2-final-submission.json`

| Metric | Result |
| --- | ---: |
| Scheduled trials | 50 |
| Provider-success / parse-valid | 48 / 48 |
| ABI-bound | 47 |
| Independently labeled semantic attacks | 40 |
| KeeperHub simulation-valid semantic attacks | 29 |
| **ProofPilot observed unsafe approvals** | **0 / 29** |
| Protocol ABI allowlist unsafe approvals | 29 / 29 |
| Static intended-function allowlist unsafe approvals | 28 / 29 |

All scheduled rows were retained: no replacement sampling and no red-team broadcast.

```text
artifact  c88901d6867fbe82a5d0facf776273e879408f31d08ae562830c3f84bd7146ef
defender  68fda657312fa1729ad178d2ef01d6ed5ab72451b72067338f3875ff6145527e
harness   d742351cab579a547077c79ca5aa3a5a842ae9ae9c43dd5bd55dd59f3ee2d436
```

> In the final frozen Aave V3 Base Sepolia external red-team run, ProofPilot observed 0 unsafe
> approvals among 29 independently labeled, KeeperHub simulation-valid semantic attacks.

This is an observed benchmark result, not a universal security guarantee.

## Reliability and Auditability

The runtime supports Observe, Confirm and Autonomous controls; Autonomous still cannot cross the
write boundary unless authorization, strict KeeperHub simulation, identity, freshness and payload
commitment gates pass. Durable operation state prevents unresolved semantic operations from being
silently resubmitted with a changed payload. Each canonical run can create a self-verifying,
integrity-checked `proofpilot.execution-trace.v2` for offline review.

## Limitations

- This is a testnet-only, multi-protocol prototype demonstrated with ERC-20 and Aave profiles.
- The compiler supports bounded consume-or-reject language, not universal intent understanding.
- The final Aave benchmark is narrow and dominated by wrong-category attacks.
- Safe execution identity is intentionally unsupported and fails closed.
- `0/29` is observed evidence, not a universal safety guarantee.
- Trace integrity has no external signature, public timestamp or onchain anchor.

## Submission Links

- **Repository:** <https://github.com/yfj898/proofpilot-keeperhub>
- **Demo video:** `<ADD_DEMO_VIDEO_URL_BEFORE_SUBMISSION>`
- **Primary transaction:** <https://sepolia.basescan.org/tx/0xdb0bc80711a6aa167038f990471ff59895f2661a1067df11ab46a48518946f90>
- **Architecture:** `docs/ARCHITECTURE.md`
- **Judge brief:** `docs/JUDGE_BRIEF.md`
