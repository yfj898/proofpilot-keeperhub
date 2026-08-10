# ProofPilot Final Recording Agent

`scripts/record_final_demo.py` is a deterministic submission-only recorder for the frozen ProofPilot
demo. It does **not** call the proposal model, rerun KeeperBench, call KeeperHub for a new simulation
or execution, submit a transaction, or change Aave state.

The recorder deliberately avoids free-form desktop clicking. It pre-verifies the preserved proof
artifacts with `scripts/show_proof.py`, recomputes the frozen benchmark summary from the public JSON,
preloads the real public GitHub/BaseScan pages, and then switches a dedicated Chrome window through
the exact 2:45 timeline in `docs/FINAL_VIDEO_SCRIPT.md`.

Terminal evidence is displayed in a terminal-style scene generated from the verified frozen traces.
This is intentional: it prevents an automation mistake from exposing `.env`, shell history, API
keys, backup codes or unrelated desktop windows.

## Prerequisites

1. **OBS Studio 28+** with its built-in obs-websocket server enabled.
2. In OBS, open **Tools -> WebSocket Server Settings**:
   - enable the WebSocket server;
   - keep the default local port `4455` unless you intentionally change it;
   - keep authentication enabled;
   - copy the password for the current shell only.
3. Configure OBS to capture the display containing the dedicated recording browser and make sure
   microphone capture is enabled only if you plan to narrate live.
4. Python Playwright and `websocket-client` must be available in the recording environment.
5. Chrome/Chromium must be installed. The current ProofPilot workstation already has system Chrome.

Do not store the OBS password in the repository. Export it only into the shell that starts the
recording:

```bash
export OBS_WEBSOCKET_PASSWORD='your-local-obs-websocket-password'
```

## 1. Run the safety doctor

From the clean public export root:

```bash
python scripts/record_final_demo.py --doctor
```

The doctor stops before recording unless all of these are true:

- the four frozen proof traces still self-verify offline;
- Observe is `SIMULATED` with `broadcast=false`;
- the wrong-category trace is KeeperHub simulation-valid but `BLOCKED` with `broadcast=false`;
- the preserved primary transaction is the frozen `0 -> 1` transaction;
- execution binding, `UserEModeSet`, receipt and post-state checks still pass;
- the cleanup trace proves final Aave E-Mode `0`;
- the benchmark recomputes to 50 scheduled / 48 provider-valid / 47 ABI-bound / 40 semantic /
  29 simulation-valid / **0/29 observed unsafe approvals**;
- the public GitHub repository and both BaseScan transaction pages return HTTP 200;
- Chrome/Playwright are available;
- OBS WebSocket is reachable and is not already recording.

## 2. Rehearse without recording

Use a short rehearsal to verify that the dedicated browser window switches correctly:

```bash
python scripts/record_final_demo.py --no-obs --timeline-scale 0.1
```

This compresses the 2:45 timeline to about 16.5 seconds. It never starts OBS.

For a real-time rehearsal:

```bash
python scripts/record_final_demo.py --no-obs
```

## 3. Record the final 2:45 cut

Start OBS, make sure its preview is capturing the correct display, then run:

```bash
python scripts/record_final_demo.py
```

After the preflight and page preload complete, the agent:

```text
0:00  Hook — Executable != Authorized
0:10  Authorized Observe proof — SIMULATED / broadcast=false
0:38  Wrong but executable — KeeperHub simulation-valid / ProofPilot BLOCKED
1:15  Real primary Base Sepolia transaction
1:27  Preserved execution/effect verification
1:47  Cleanup transaction + final state 0
1:55  Frozen benchmark — 29/29 vs 28/29 vs 0/29 observed
2:25  Architecture
2:38  Public GitHub + 155 tests PASS / 0/29 overlay
2:45  Stop recording
```

The script calls OBS `StartRecord` only after every browser scene has been preloaded. At the end it
calls `StopRecord` and prints the OBS output path when OBS returns one.

## Narration

The recorder controls the visuals, not your voice. There are two safe options:

### Live narration

Read the narration blocks in `docs/FINAL_VIDEO_SCRIPT.md` while the automated timeline changes the
screen. Do one rehearsal first so the cuts feel predictable.

### Voice-over after recording

Disable/mute the microphone in OBS, let the agent record the clean 2:45 visual track, and add the
283-word narration afterward in your editor. This is usually easier and avoids having to repeat the
screen recording because of one spoken mistake.

## Safety properties

The recording agent has no code path for:

- `--live` ProofPilot execution;
- KeeperHub transaction submission;
- Aave state mutation;
- external-model proposal generation;
- formal benchmark execution;
- opening `.env`, local journals, backup codes or wallet material.

The only subprocess it runs against ProofPilot evidence is the existing offline renderer:

```text
python scripts/show_proof.py <frozen-trace.json>
```

The benchmark numbers shown on screen are recomputed from the already-frozen public benchmark
artifact; no new trial is generated.

## If the doctor says there is no desktop display

Run the script from a normal graphical Ubuntu terminal on the workstation. A headless SSH/MCP shell
often does not inherit `DISPLAY` / `WAYLAND_DISPLAY`, and the final recording intentionally refuses
to run there.

## If OBS cannot connect

Confirm that OBS is already open and that **Tools -> WebSocket Server Settings** is enabled. The
default obs-websocket 5.x port is `4455`. If you changed it locally, pass the same port:

```bash
python scripts/record_final_demo.py --obs-port 4456
```

Do not disable OBS authentication just to make the script work; pass the password through the
`OBS_WEBSOCKET_PASSWORD` environment variable instead.
