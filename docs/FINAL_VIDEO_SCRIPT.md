# ProofPilot — Final 2–3 Minute Demo Video Script

**Target runtime:** 2:40–2:50  
**Network:** Base Sepolia only  
**Recording rule:** use preserved read-only evidence; do not run `--live`, submit a transaction,
change E-Mode or retry a provider for a prettier response.

## Recording Assets

- Doctor snapshot: `artifacts/runtime/competition-demo-doctor.json`
- Successful bounded LLM proposal + simulation: `artifacts/demo/proofpilot-agent-simulation-20260809.json`
- Hardened deterministic Observe preview: `artifacts/demo/proofpilot-five-fixes-observe.json`
- Hardened `0 -> 1` trace: `artifacts/demo/proofpilot-five-fixes-live.json`
- Hardened cleanup trace: `artifacts/demo/proofpilot-five-fixes-cleanup.json`
- Blocked attack trace: `artifacts/demo/proofpilot-attack-validation-trace-v2.json`
- Final benchmark: `artifacts/keeperbench/external-redteam-aave-formal-20260809-25x2-final-submission.json`

## 0:00–0:15 — Hook

**Screen**

```text
ProofPilot — Intent Firewall for Autonomous Onchain Agents

Executable != Authorized
```

**Narration**

> An autonomous agent can propose a transaction that is perfectly valid and simulation-safe, but
> still not be what the user authorized. ProofPilot closes that gap.

## 0:15–0:35 — Architecture

**Screen**

```text
User mandate
    -> Bounded AI Agent
    -> ProofPilot
    -> KeeperHub
    -> Blockchain
    -> Independent verification
```

Overlay: `Agent proposes. ProofPilot authorizes. KeeperHub executes. Verifier confirms.`

**Narration**

> The agent proposes an action for a bounded user mandate. ProofPilot deterministically checks the
> exact chain, contract, function, arguments, value and effects. KeeperHub is the sole write path,
> and an independent read layer verifies the resulting effect.

## 0:35–1:10 — Safe, Zero-Write Path

**Screen**

Show the preserved Doctor snapshot, the bounded LLM proposal trace, then the hardened deterministic
Observe preview. Label the two traces clearly and pause on:

```text
Doctor READY
Agent proposal: setUserEMode(1)
Candidate Action Preview: 0 -> 1
Intent Assurance: PASS
KeeperHub simulation: success=true, wouldRevert=false
Final: SIMULATED
broadcast=false
```

Optional offline renderer:

```bash
python scripts/show_proof.py artifacts/demo/proofpilot-five-fixes-observe.json
```

**Narration**

> The first trace preserves a real external-model proposal and successful KeeperHub simulation. The
> second is the hardened deterministic reference path that shows the final preview and control gates.
> The model has no KeeperHub credential, wallet key or write tool, and Observe mode can never
> broadcast. In the last credentialed default run, Doctor was READY but the provider response failed
> ABI binding, so ProofPilot stopped before simulation. Live model failures fail closed before
> execution.

## 1:10–1:40 — Wrong but Executable

**Screen**

Render the preserved attack trace or show this exact comparison:

```text
User authorized:  setUserEMode(1)
Agent proposes:   setUserEMode(0)

KeeperHub simulation:
  success=true
  wouldRevert=false

ProofPilot:
  BLOCKED
  broadcast=false
```

**Narration**

> The wrong category is executable, but it does not conform to the mandate. KeeperHub correctly
> answers whether the call can execute. ProofPilot answers whether it was authorized and keeps the
> write boundary closed.

## 1:40–2:05 — Preserved Real Execution Proof

**Screen**

Open the hardened BaseScan transaction:

```text
0xdb0bc80711a6aa167038f990471ff59895f2661a1067df11ab46a48518946f90
```

Then show the preserved trace:

```bash
python scripts/show_proof.py artifacts/demo/proofpilot-five-fixes-live.json
```

Pause on:

```text
KeeperHub completed
Independent receipt PASS
Execution/effect binding PASS
Aave UserEModeSet PASS
Post-state PASS
L2_EXECUTION_EFFECT_VERIFIED
```

Show cleanup tx `0x2f42aefeed93e25df81b90a4e56b08698ffaf407f0f8ae7a6c970157a3a64780`
and `current Aave E-Mode = 0`.

**Narration**

> This preserved hardened run changed E-Mode from zero to one through KeeperHub. ProofPilot required
> completion, an independent L2 receipt, execution/effect binding, the Aave event and post-state.
> The cleanup restored the test account to zero. This is L2 execution/effect verification, not full
> internal-call tracing or L1 finality.

## 2:05–2:30 — Frozen External Red-Team

**Screen**

```text
Final Aave V3 Base Sepolia freeze

50 scheduled trials
48 provider / parse valid
47 ABI-bound
40 semantic attacks
29 KeeperHub simulation-valid semantic attacks

Protocol ABI allowlist:       29 / 29 unsafe approvals
Static function allowlist:    28 / 29 unsafe approvals
ProofPilot:                    0 / 29 observed unsafe approvals
```

**Narration**

> The final frozen run retained all fifty scheduled attempts. Forty were independently labeled
> semantic attacks; KeeperHub confirmed twenty-nine were simulation-valid. ProofPilot observed zero
> unsafe approvals among those twenty-nine. This is an observed narrow benchmark result, not a
> universal security guarantee.

## 2:30–2:45 — Close

**Screen**

```text
Agent proposes.
ProofPilot authorizes.
KeeperHub executes.
Verifier confirms.
```

**Narration**

> KeeperHub answers whether an authorized transaction can execute reliably. ProofPilot answers
> whether the transaction was authorized in the first place.

## Editing Rules

- Use cuts or static preserved evidence instead of dead terminal waits.
- Do not display `.env`, shell history, API keys, backup codes or local journal files.
- Do not claim a zero-percent security failure rate, universal safety, full call-trace proof or L1
  finality.
- Do not show an old `0/35` benchmark slide; the final result is `0/29` observed.
- Keep the final video at or below three minutes.
