# ProofPilot — Final 2:45 Demo Video Script

**Target runtime:** 2:45  
**Hard limit:** under 3:00  
**Network:** Base Sepolia only  
**Style:** working-product proof first; architecture second  
**Recording rule:** use preserved read-only evidence only. Do **not** run `--live`, submit a
transaction, change Aave E-Mode, rerun the formal benchmark, or retry a provider for a prettier
response.

This cut is intentionally closer to a strong hackathon demo than a presentation: show that the
system works immediately, show the failure mode it prevents, show real chain evidence, show the
frozen benchmark, then explain the architecture in one compact closing frame.

## Recording Assets

- Doctor snapshot: `artifacts/runtime/competition-demo-doctor.json`
- Successful bounded LLM proposal + simulation: `artifacts/demo/proofpilot-agent-simulation-20260809.json`
- Hardened deterministic Observe preview: `artifacts/demo/proofpilot-five-fixes-observe.json`
- Hardened `0 -> 1` trace: `artifacts/demo/proofpilot-five-fixes-live.json`
- Hardened cleanup trace: `artifacts/demo/proofpilot-five-fixes-cleanup.json`
- Blocked attack trace: `artifacts/demo/proofpilot-attack-validation-trace-v2.json`
- Final benchmark: `artifacts/keeperbench/external-redteam-aave-formal-20260809-25x2-final-submission.json`

## Recording Setup

Before pressing record:

**Automated option:** `scripts/record_final_demo.py` implements this exact 2:45 evidence-first cut
with deterministic browser scene switching and OBS WebSocket start/stop control. Run
`python scripts/record_final_demo.py --doctor` first, then follow `docs/RECORDING_AGENT.md`.

1. Open the public GitHub repository: `https://github.com/yfj898/proofpilot-keeperhub`.
2. Open a terminal at the clean submission export root with a large readable font.
3. Pre-open the primary BaseScan transaction:
   `https://sepolia.basescan.org/tx/0xdb0bc80711a6aa167038f990471ff59895f2661a1067df11ab46a48518946f90`.
4. Pre-open the cleanup BaseScan transaction:
   `https://sepolia.basescan.org/tx/0x2f42aefeed93e25df81b90a4e56b08698ffaf407f0f8ae7a6c970157a3a64780`.
5. Open `docs/EXTERNAL_REDTEAM_AAVE.md` near the final benchmark table.
6. Hide desktop notifications and close email, chat, password managers and unrelated tabs.

Prefer 1920x1080 recording if practical. Do not display `.env`, shell history, API keys,
KeeperHub credentials, backup codes, local journal files or unrelated personal information.

## 0:00–0:10 — Hook: Show the Problem, Not the Architecture

**Screen**

```text
ProofPilot
Intent Firewall for Autonomous Onchain Agents

Executable != Authorized
```

Hold for about two seconds, then cut directly to the terminal. Do not open with a team biography or
long architecture explanation.

**Narration**

> An autonomous agent can propose a transaction that is perfectly valid and simulation-safe, but
> still not be what the user authorized. ProofPilot closes that gap before the write boundary.

## 0:10–0:38 — Working Safe Path: Authorized, Simulated, Zero Write

**Screen**

Run only the offline proof viewer:

```bash
python scripts/show_proof.py artifacts/demo/proofpilot-five-fixes-observe.json
```

Scroll only enough to center these fields and pause on them:

```text
Candidate Action Preview: 0 -> 1
Intent Assurance: PASS
KeeperHub simulation: success=true
wouldRevert=false
Final: SIMULATED
broadcast=false
```

**Narration**

> Here the user authorizes Aave E-Mode category one. ProofPilot checks the exact chain, target,
> function, arguments, value and allowed effects. KeeperHub simulation succeeds, but Observe mode
> ends at SIMULATED with broadcast false. The model can propose; it cannot authorize its own write.

**Edit note:** use the preserved trace exactly as recorded. Do not call the model or KeeperHub again
during video recording.

## 0:38–1:15 — Core Demo: Wrong but Executable

**Screen**

Render the preserved blocked-attack proof or show this exact comparison:

```text
User authorized:  setUserEMode(1)
Agent proposed:    setUserEMode(0)

KeeperHub simulation:
  success=true
  wouldRevert=false

ProofPilot:
  BLOCKED
  broadcast=false
```

**Narration**

> Now the agent proposes category zero instead. The call is ABI-valid and KeeperHub confirms it is
> simulation-valid: success true, wouldRevert false. But it violates the user's typed mandate, so
> ProofPilot blocks it and never broadcasts. Simulation answers whether a call can execute.
> ProofPilot answers whether this exact call was authorized.

**Edit note:** keep `success=true`, `wouldRevert=false`, `BLOCKED` and `broadcast=false` visible
together if possible. This is the most important shot in the video.

## 1:15–1:55 — Real Base Sepolia Execution and Independent Effect Proof

**Screen action A — BaseScan**

Cut to the already-open hardened BaseScan transaction:

```text
0xdb0bc80711a6aa167038f990471ff59895f2661a1067df11ab46a48518946f90
```

Hold long enough for the reviewer to see that it is a real Base Sepolia transaction. Do not hunt
through tabs or wait for pages to load during the recording.

**Screen action B — Preserved proof**

Cut back to the terminal and run:

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

Then cut briefly to cleanup tx
`0x2f42aefeed93e25df81b90a4e56b08698ffaf407f0f8ae7a6c970157a3a64780` and show
`current Aave E-Mode = 0` from the preserved cleanup evidence.

**Narration**

> This preserved hardened execution changed Aave E-Mode from zero to one through KeeperHub. After
> KeeperHub completed, ProofPilot independently checked the L2 receipt, bound the execution to the
> intended effect, verified the Aave UserEModeSet event and confirmed post-state. The cleanup then
> restored the test account to zero. This is L2 execution-and-effect verification, not a claim of
> full internal-call tracing or L1 finality.

**Edit note:** use cuts between BaseScan and terminal. Never create a new transaction for the
recording.

## 1:55–2:25 — Frozen External Red-Team: Why the Boundary Matters

**Screen**

Show the final table from `docs/EXTERNAL_REDTEAM_AAVE.md` or a clean static crop derived from the
same frozen artifact. Do not scroll through the raw JSON on camera.

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

Keep the three comparison rows visible at the same time.

**Narration**

> In the final frozen Aave benchmark, fifty trials were retained, forty were semantic attacks and
> twenty-nine of those attacks were confirmed simulation-valid by KeeperHub. A protocol ABI
> allowlist approved all twenty-nine. A static intended-function allowlist approved twenty-eight.
> ProofPilot observed zero unsafe approvals among the twenty-nine. This is narrow observed evidence,
> not a universal security guarantee.

Use the exact phrase **`0/29 observed unsafe approvals`**. Do not say “zero-percent failure rate”,
“provably secure” or “all attacks are blocked”.

## 2:25–2:38 — Architecture in One Frame

**Screen**

Return to the GitHub README architecture diagram or show this compact flow:

```text
User mandate
    -> Bounded AI Agent
    -> ProofPilot
    -> KeeperHub
    -> Blockchain
    -> Independent verification

Agent proposes.
ProofPilot authorizes.
KeeperHub executes.
Verifier confirms.
```

**Narration**

> The separation is deliberate: the AI proposes, the typed mandate and deterministic checks
> authorize, KeeperHub remains the sole write path, and an independent verifier confirms the
> resulting effect.

**Edit note:** architecture comes near the end because the reviewer has already seen each component
working.

## 2:38–2:45 — Close on Public Evidence

**Screen**

End on the public GitHub repository header. If readable without clutter, use this small overlay:

```text
155 tests PASS
Final frozen benchmark: 0/29 observed unsafe approvals

Executable != Authorized
```

**Narration**

> KeeperHub tells us whether a transaction can execute. ProofPilot makes sure it was authorized in
> the first place.

Cut immediately after the final sentence.

## Complete Recording Run Sheet

```text
0:00  GitHub/title: ProofPilot — Executable != Authorized
0:10  Terminal: preserved Observe proof
0:38  Terminal: wrong-but-executable blocked attack
1:15  Browser: primary BaseScan transaction
1:27  Terminal: hardened execution proof
1:47  Browser/proof: cleanup transaction and current state 0
1:55  Benchmark table: 29 simulation-valid attacks, ProofPilot 0/29 observed
2:25  README architecture: Agent -> ProofPilot -> KeeperHub -> verifier
2:38  Public GitHub repository + 155 tests / 0/29 overlay
2:45  End
```

## Editing Rules

- Keep the finished video at approximately **2:45** and always below 3:00.
- Prefer cuts and preserved evidence over dead terminal waits.
- Do not run `--live`, submit a transaction, change Aave E-Mode or rerun the formal benchmark.
- Do not call the proposal provider during recording just to obtain a cleaner response.
- Do not display `.env`, API keys, KeeperHub credentials, backup codes, shell history or local
  journal files.
- Do not show the old `0/35` denominator as a final result. The final frozen result is **`0/29
  observed unsafe approvals`**.
- The current competition closeout is **155 tests PASS**.
- Say **bounded AI agent** or **AI proposal agent**, not an autonomous model with transaction
  authority.
- Say **self-verifying** or **integrity-checked trace**, not tamper-proof or cryptographically
  timestamped unless an external anchor is actually shown.
- Say **`L2_EXECUTION_EFFECT_VERIFIED`**, not full trace verification or L1 finality.
- Say **observed evidence from a narrow frozen benchmark**, not a universal security guarantee.
- Never imply KeeperHub is unsafe. KeeperHub answers execution/simulation questions; ProofPilot adds
  the user-intent authorization boundary before the write.

## Final Export Check

Before uploading the video, watch it once from beginning to end and confirm:

- the public GitHub URL is readable;
- no secret or personal notification appears in any frame;
- the primary and cleanup BaseScan transactions are readable;
- the wrong-but-executable contrast is visible for long enough to understand;
- `broadcast=false` is visible on both zero-write and blocked paths where shown;
- the only final benchmark denominator shown is **29**;
- `0/35` appears nowhere in the finished video;
- the final claim is **155 tests PASS / 0/29 observed unsafe approvals**;
- the video finishes below 3:00.
