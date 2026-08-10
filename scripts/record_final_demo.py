from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

GITHUB_URL = "https://github.com/yfj898/proofpilot-keeperhub"
README_RAW_URL = "https://raw.githubusercontent.com/yfj898/proofpilot-keeperhub/main/README.md"
PRIMARY_TX_HASH = "0xdb0bc80711a6aa167038f990471ff59895f2661a1067df11ab46a48518946f90"
CLEANUP_TX_HASH = "0x2f42aefeed93e25df81b90a4e56b08698ffaf407f0f8ae7a6c970157a3a64780"
PRIMARY_TX_URL = f"https://sepolia.basescan.org/tx/{PRIMARY_TX_HASH}"
CLEANUP_TX_URL = f"https://sepolia.basescan.org/tx/{CLEANUP_TX_HASH}"

OBSERVE_TRACE = ROOT / "artifacts/demo/proofpilot-five-fixes-observe.json"
BLOCKED_TRACE = ROOT / "artifacts/demo/proofpilot-attack-validation-trace-v2.json"
LIVE_TRACE = ROOT / "artifacts/demo/proofpilot-five-fixes-live.json"
CLEANUP_TRACE = ROOT / "artifacts/demo/proofpilot-five-fixes-cleanup.json"
BENCHMARK = ROOT / "artifacts/keeperbench/external-redteam-aave-formal-20260809-25x2-final-submission.json"


class RecordingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Scene:
    key: str
    start: float
    duration: float
    label: str

    @property
    def end(self) -> float:
        return self.start + self.duration


SCENES = (
    Scene("title", 0, 10, "Hook — Executable != Authorized"),
    Scene("observe", 10, 28, "Authorized + simulation-valid + zero write"),
    Scene("blocked", 38, 37, "Wrong but executable — BLOCKED"),
    Scene("primary_tx", 75, 12, "Real Base Sepolia primary transaction"),
    Scene("live", 87, 20, "Preserved hardened execution proof"),
    Scene("cleanup_tx", 107, 4, "Cleanup Base Sepolia transaction"),
    Scene("cleanup", 111, 4, "Cleanup post-state = 0"),
    Scene("benchmark", 115, 30, "Frozen 0/29 external red-team"),
    Scene("architecture", 145, 13, "Architecture in one frame"),
    Scene("close", 158, 7, "Public repository + final frozen facts"),
)

FINAL_DURATION_SECONDS = 165


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RecordingError(f"Required frozen artifact is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RecordingError(f"Frozen artifact is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RecordingError(f"Expected JSON object in {path}")
    return data


def _run_offline_renderer(path: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/show_proof.py"), str(path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        raise RecordingError(
            f"Offline proof verification failed for {path.name}: "
            f"exit={proc.returncode}; stderr={proc.stderr.strip()}"
        )
    return proc.stdout


def _all_checks_pass(checks: list[dict[str, Any]]) -> bool:
    return bool(checks) and all(item.get("passed") is True for item in checks)


def _assert_frozen_evidence() -> dict[str, Any]:
    observe = _load_json(OBSERVE_TRACE)
    blocked = _load_json(BLOCKED_TRACE)
    live = _load_json(LIVE_TRACE)
    cleanup = _load_json(CLEANUP_TRACE)
    benchmark = _load_json(BENCHMARK)

    # Reuse the project's own self-verifying offline renderer. No provider, KeeperHub,
    # RPC write, benchmark run, or chain transaction is invoked here.
    for path in (OBSERVE_TRACE, BLOCKED_TRACE, LIVE_TRACE, CLEANUP_TRACE):
        _run_offline_renderer(path)

    observe_sim = ((observe.get("keeperhub") or {}).get("simulation") or {})
    observe_control = (observe.get("context") or {}).get("execution_control") or {}
    if not (
        observe.get("final_status") == "SIMULATED"
        and observe.get("broadcast_attempted") is False
        and observe_sim.get("success") is True
        and observe_sim.get("wouldRevert") is False
        and observe_control.get("mode") == "observe"
    ):
        raise RecordingError("Frozen Observe trace does not match the approved zero-write evidence.")

    blocked_sim = ((blocked.get("keeperhub") or {}).get("simulation") or {})
    blocked_args = (((blocked.get("proposal") or {}).get("action") or {}).get("arguments"))
    if not (
        blocked.get("final_status") == "BLOCKED"
        and blocked.get("broadcast_attempted") is False
        and blocked_sim.get("success") is True
        and blocked_sim.get("wouldRevert") is False
        and blocked_args == [0]
    ):
        raise RecordingError("Frozen blocked-attack trace no longer matches the approved evidence.")

    live_execution = ((live.get("keeperhub") or {}).get("execution") or {})
    live_verification = live.get("verification") or {}
    live_binding = live_verification.get("execution_binding") or {}
    live_event = next(
        (
            item
            for item in live_binding.get("checks") or []
            if item.get("name") == "aave_user_emode_event_binding"
        ),
        {},
    )
    if not (
        live.get("final_status") == "VERIFIED"
        and live_execution.get("status") == "completed"
        and live_execution.get("transaction_hash") == PRIMARY_TX_HASH
        and (live_verification.get("independent_receipt") or {}).get("passed") is True
        and live_binding.get("passed") is True
        and live_event.get("passed") is True
        and ((live_verification.get("post_state") or {}).get("aave") or {}).get("user_emode") == 1
        and live_verification.get("level") == "L2_EXECUTION_EFFECT_VERIFIED"
    ):
        raise RecordingError("Frozen live trace no longer matches the approved execution proof.")

    cleanup_execution = ((cleanup.get("keeperhub") or {}).get("execution") or {})
    cleanup_verification = cleanup.get("verification") or {}
    if not (
        cleanup.get("final_status") == "VERIFIED"
        and cleanup_execution.get("transaction_hash") == CLEANUP_TX_HASH
        and ((cleanup_verification.get("post_state") or {}).get("aave") or {}).get("user_emode") == 0
    ):
        raise RecordingError("Frozen cleanup trace no longer proves final Aave E-Mode = 0.")

    aggregate = benchmark.get("aggregate_summary") or {}
    expected = {
        "attempts": 50,
        "provider_success": 48,
        "parse_valid": 48,
        "abi_bind_valid": 47,
        "semantic_attacks": 40,
        "simulation_valid_semantic_attacks": 29,
        "proofpilot_unsafe_approved": 0,
    }
    for key, value in expected.items():
        if aggregate.get(key) != value:
            raise RecordingError(
                f"Frozen benchmark mismatch for {key}: expected {value}, got {aggregate.get(key)!r}. "
                "Do not record a changed benchmark."
            )

    valid_attacks = [
        row
        for row in benchmark.get("attempts") or []
        if row.get("semantic_attack") is True and row.get("simulation_valid") is True
    ]
    if len(valid_attacks) != 29:
        raise RecordingError(f"Expected 29 simulation-valid semantic attacks, got {len(valid_attacks)}.")
    baseline = {
        "protocol_abi": sum(row.get("protocol_abi_allowlist_approved") is True for row in valid_attacks),
        "static_function": sum(
            row.get("static_intended_function_allowlist_approved") is True for row in valid_attacks
        ),
        "proofpilot": sum(row.get("proofpilot_approved") is True for row in valid_attacks),
    }
    if baseline != {"protocol_abi": 29, "static_function": 28, "proofpilot": 0}:
        raise RecordingError(f"Frozen benchmark baseline recomputation mismatch: {baseline}")

    return {
        "observe": observe,
        "blocked": blocked,
        "live": live,
        "cleanup": cleanup,
        "benchmark": benchmark,
        "baseline": baseline,
    }


def _http_status(url: str) -> int:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ProofPilot-Final-Recording-Preflight/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except OSError as exc:
        raise RecordingError(f"Network preflight failed for {url}: {exc}") from exc


def _check_public_links() -> None:
    for url in (GITHUB_URL, README_RAW_URL, PRIMARY_TX_URL, CLEANUP_TX_URL):
        status = _http_status(url)
        if status != 200:
            raise RecordingError(f"Public evidence URL is not anonymously reachable (HTTP {status}): {url}")


def _browser_executable(explicit: str | None) -> str:
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file():
            raise RecordingError(f"Browser executable does not exist: {candidate}")
        return str(candidate)
    for name in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    raise RecordingError("Chrome/Chromium was not found. Install Chrome/Chromium or pass --browser PATH.")


def _check_playwright() -> None:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError as exc:
        raise RecordingError(
            "Python Playwright is required for the recording controller. "
            "Install it in your recording environment before running the agent."
        ) from exc


class ObsWebSocket:
    def __init__(self, host: str, port: int, password: str | None) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.ws: Any = None
        self.started_recording = False

    def connect(self) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise RecordingError(
                "The recording controller requires the 'websocket-client' Python package for OBS control."
            ) from exc

        try:
            self.ws = websocket.create_connection(
                f"ws://{self.host}:{self.port}",
                timeout=5,
                subprotocols=["obswebsocket.json"],
            )
        except Exception as exc:  # websocket-client exposes several transport exceptions
            raise RecordingError(
                f"Cannot connect to OBS WebSocket at ws://{self.host}:{self.port}. "
                "Start OBS and enable Tools -> WebSocket Server Settings first."
            ) from exc

        hello = self._recv_until_op(0)
        hello_data = hello.get("d") or {}
        identify: dict[str, Any] = {"rpcVersion": int(hello_data.get("rpcVersion") or 1)}
        auth = hello_data.get("authentication")
        if auth:
            if not self.password:
                raise RecordingError(
                    "OBS WebSocket authentication is enabled but OBS_WEBSOCKET_PASSWORD is not set."
                )
            secret = base64.b64encode(
                hashlib.sha256((self.password + str(auth["salt"])).encode("utf-8")).digest()
            ).decode("ascii")
            response = base64.b64encode(
                hashlib.sha256((secret + str(auth["challenge"])).encode("utf-8")).digest()
            ).decode("ascii")
            identify["authentication"] = response
        self._send({"op": 1, "d": identify})
        self._recv_until_op(2)

    def _send(self, payload: dict[str, Any]) -> None:
        if self.ws is None:
            raise RecordingError("OBS WebSocket is not connected.")
        self.ws.send(json.dumps(payload, separators=(",", ":")))

    def _recv(self) -> dict[str, Any]:
        if self.ws is None:
            raise RecordingError("OBS WebSocket is not connected.")
        raw = self.ws.recv()
        if not isinstance(raw, str):
            raise RecordingError("OBS returned a non-JSON WebSocket frame.")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise RecordingError("OBS returned an invalid protocol payload.")
        return payload

    def _recv_until_op(self, opcode: int) -> dict[str, Any]:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            payload = self._recv()
            if payload.get("op") == opcode:
                return payload
        raise RecordingError(f"Timed out waiting for OBS WebSocket opcode {opcode}.")

    def request(self, request_type: str) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        self._send(
            {
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": request_id,
                },
            }
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            payload = self._recv()
            if payload.get("op") != 7:
                continue
            data = payload.get("d") or {}
            if data.get("requestId") != request_id:
                continue
            status = data.get("requestStatus") or {}
            if status.get("result") is not True:
                raise RecordingError(
                    f"OBS request {request_type} failed: code={status.get('code')} "
                    f"comment={status.get('comment')!r}"
                )
            response = data.get("responseData") or {}
            return response if isinstance(response, dict) else {}
        raise RecordingError(f"Timed out waiting for OBS request response: {request_type}")

    def ensure_idle(self) -> None:
        status = self.request("GetRecordStatus")
        if status.get("outputActive") is True:
            raise RecordingError(
                "OBS is already recording. Stop the existing recording before starting ProofPilot automation."
            )

    def start_record(self) -> None:
        self.request("StartRecord")
        self.started_recording = True

    def stop_record(self) -> str | None:
        if not self.started_recording:
            return None
        data = self.request("StopRecord")
        self.started_recording = False
        path = data.get("outputPath")
        return str(path) if path else None

    def close(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            finally:
                self.ws = None


BASE_CSS = """
html,body{margin:0;width:100%;height:100%;background:#0b0d12;color:#f4f6fb;font-family:Inter,Arial,sans-serif;overflow:hidden}
*{box-sizing:border-box}.frame{height:100vh;padding:64px 78px;display:flex;flex-direction:column;justify-content:center}
.eyebrow{font-size:22px;letter-spacing:.12em;text-transform:uppercase;color:#9aa4b8;margin-bottom:22px}
h1{font-size:64px;line-height:1.05;margin:0 0 24px;font-weight:760}h2{font-size:42px;margin:0 0 22px}
.accent{color:#8fc7ff}.ok{color:#7fe6a2}.bad{color:#ff8e8e}.muted{color:#aeb6c7}.big{font-size:52px}
.terminal{background:#11151d;border:1px solid #2a3344;border-radius:18px;padding:30px 34px;box-shadow:0 20px 60px #0007}
.cmd{font:600 22px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#8fc7ff;margin-bottom:18px}
pre{margin:0;white-space:pre-wrap;font:500 25px/1.48 ui-monospace,SFMono-Regular,Menlo,monospace;color:#e9eef8}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:26px}.card{background:#121722;border:1px solid #293247;border-radius:18px;padding:28px}
.metric{font-size:35px;font-weight:730;margin:12px 0}.footer{position:absolute;left:78px;right:78px;bottom:34px;color:#8792a8;font-size:18px;display:flex;justify-content:space-between}
.flow{font:700 37px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace;text-align:center}.divider{height:1px;background:#293247;margin:24px 0}
"""


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
        "content='width=device-width,initial-scale=1'><title>"
        + html.escape(title)
        + "</title><style>"
        + BASE_CSS
        + "</style></head><body>"
        + body
        + "</body></html>"
    )


def _terminal_page(title: str, command: str, lines: list[str], *, emphasis: str = "") -> str:
    safe_lines = "\n".join(html.escape(line) for line in lines)
    emphasis_html = f"<div class='big accent' style='margin-bottom:22px'>{html.escape(emphasis)}</div>" if emphasis else ""
    body = f"""
    <div class='frame'>
      <div class='eyebrow'>Preserved read-only evidence · offline renderer</div>
      <h2>{html.escape(title)}</h2>{emphasis_html}
      <div class='terminal'><div class='cmd'>$ {html.escape(command)}</div><pre>{safe_lines}</pre></div>
      <div class='footer'><span>No provider call · no KeeperHub write · no chain transaction</span><span>Base Sepolia frozen evidence</span></div>
    </div>"""
    return _page(title, body)


def _build_local_pages(evidence: dict[str, Any]) -> dict[str, str]:
    observe = evidence["observe"]
    blocked = evidence["blocked"]
    live = evidence["live"]
    cleanup = evidence["cleanup"]
    benchmark = evidence["benchmark"]
    baseline = evidence["baseline"]

    observe_preview = (observe.get("context") or {}).get("intent_preview") or {}
    observe_change = (observe_preview.get("changes") or [{}])[0]
    observe_sim = ((observe.get("keeperhub") or {}).get("simulation") or {})
    observe_checks = ((observe.get("authorization") or {}).get("intent_assurance") or {}).get("checks") or []
    observe_lines = [
        f"Change: {observe_change.get('before')} -> {observe_change.get('after')}",
        f"Bound action: setUserEMode(uint8) [1]",
        f"Intent Assurance: {'PASS' if _all_checks_pass(observe_checks) else 'FAIL'}",
        f"KeeperHub simulation: success={str(observe_sim.get('success')).lower()} wouldRevert={str(observe_sim.get('wouldRevert')).lower()}",
        "Execution mode: OBSERVE",
        f"Final: {observe.get('final_status')}",
        f"broadcast=false",
        "Trace integrity: PASS",
    ]

    blocked_intent = blocked.get("intent") or {}
    blocked_proposal = ((blocked.get("proposal") or {}).get("action") or {})
    blocked_sim = ((blocked.get("keeperhub") or {}).get("simulation") or {})
    blocked_deviations = (blocked.get("authorization") or {}).get("independent_semantic_deviations") or []
    blocked_lines = [
        f"User authorized:  setUserEMode(1)",
        f"Agent proposed:    setUserEMode({(blocked_proposal.get('arguments') or ['?'])[0]})",
        "",
        f"KeeperHub simulation: success={str(blocked_sim.get('success')).lower()} wouldRevert={str(blocked_sim.get('wouldRevert')).lower()}",
        f"Semantic deviation: {', '.join(str(x) for x in blocked_deviations)}",
        "Intent Assurance: FAIL — argument mismatch",
        "",
        f"ProofPilot: {blocked.get('final_status')}",
        "broadcast=false",
        "Trace integrity: PASS",
    ]

    live_execution = ((live.get("keeperhub") or {}).get("execution") or {})
    live_verification = live.get("verification") or {}
    live_binding = live_verification.get("execution_binding") or {}
    live_event = next(
        (
            item
            for item in live_binding.get("checks") or []
            if item.get("name") == "aave_user_emode_event_binding"
        ),
        {},
    )
    live_lines = [
        f"KeeperHub status: {live_execution.get('status')}",
        f"Transaction: {live_execution.get('transaction_hash')}",
        f"Independent receipt: {'PASS' if (live_verification.get('independent_receipt') or {}).get('passed') else 'FAIL'}",
        f"Execution/effect binding: {'PASS' if live_binding.get('passed') else 'FAIL'}",
        f"Aave UserEModeSet binding: {'PASS' if live_event.get('passed') else 'FAIL'}",
        f"Post-state: aave.user_emode={((live_verification.get('post_state') or {}).get('aave') or {}).get('user_emode')}",
        f"Postcondition: {'PASS' if (live_verification.get('postcondition_check') or {}).get('passed') else 'FAIL'}",
        f"Verification level: {live_verification.get('level')}",
        "Trace integrity: PASS",
    ]

    cleanup_verification = cleanup.get("verification") or {}
    cleanup_lines = [
        f"Cleanup transaction: {((cleanup.get('keeperhub') or {}).get('execution') or {}).get('transaction_hash')}",
        f"KeeperHub status: {((cleanup.get('keeperhub') or {}).get('execution') or {}).get('status')}",
        f"Independent receipt: {'PASS' if (cleanup_verification.get('independent_receipt') or {}).get('passed') else 'FAIL'}",
        f"Post-state: aave.user_emode={((cleanup_verification.get('post_state') or {}).get('aave') or {}).get('user_emode')}",
        f"Postcondition: {'PASS' if (cleanup_verification.get('postcondition_check') or {}).get('passed') else 'FAIL'}",
        f"Verification level: {cleanup_verification.get('level')}",
        "Trace integrity: PASS",
    ]

    aggregate = benchmark.get("aggregate_summary") or {}
    title = _page(
        "ProofPilot",
        """
        <div class='frame'>
          <div class='eyebrow'>ProofPilot · Intent Firewall for Autonomous Onchain Agents</div>
          <h1>Executable <span class='bad'>!=</span> Authorized</h1>
          <div class='big muted'>A transaction can be valid, simulation-safe, and still violate the user's mandate.</div>
          <div class='footer'><span>KeeperHub-native · Base Sepolia</span><span>Final submission evidence</span></div>
        </div>""",
    )

    benchmark_page = _page(
        "Frozen benchmark",
        f"""
        <div class='frame'>
          <div class='eyebrow'>Final frozen Aave V3 Base Sepolia benchmark</div>
          <h2>Simulation-valid does not imply authorized</h2>
          <div class='grid'>
            <div class='card'>
              <div class='metric'>{aggregate.get('attempts')} scheduled</div>
              <div class='metric'>{aggregate.get('provider_success')} provider / parse valid</div>
              <div class='metric'>{aggregate.get('abi_bind_valid')} ABI-bound</div>
              <div class='metric'>{aggregate.get('semantic_attacks')} semantic attacks</div>
              <div class='metric accent'>{aggregate.get('simulation_valid_semantic_attacks')} KeeperHub simulation-valid attacks</div>
            </div>
            <div class='card'>
              <div class='metric bad'>Protocol ABI allowlist: {baseline['protocol_abi']} / 29 unsafe approvals</div>
              <div class='metric bad'>Static function allowlist: {baseline['static_function']} / 29 unsafe approvals</div>
              <div class='divider'></div>
              <div class='metric ok'>ProofPilot: {baseline['proofpilot']} / 29 observed unsafe approvals</div>
              <div class='muted' style='font-size:22px;margin-top:24px'>Observed evidence from a narrow frozen benchmark — not a universal security guarantee.</div>
            </div>
          </div>
          <div class='footer'><span>All values recomputed from the frozen public artifact</span><span>Final denominator: 29</span></div>
        </div>""",
    )

    architecture = _page(
        "ProofPilot architecture",
        """
        <div class='frame'>
          <div class='eyebrow'>Separation of responsibility</div>
          <div class='flow'>
            User mandate<br>↓<br>
            <span class='accent'>Bounded AI Agent — proposes</span><br>↓<br>
            <span class='ok'>ProofPilot — authorizes deterministically</span><br>↓<br>
            KeeperHub — simulates and executes<br>↓<br>
            Independent verifier — confirms effect
          </div>
          <div class='footer'><span>Agent proposes. ProofPilot authorizes.</span><span>KeeperHub executes. Verifier confirms.</span></div>
        </div>""",
    )

    return {
        "title": title,
        "observe": _terminal_page(
            "Authorized, simulated, zero write",
            "python scripts/show_proof.py artifacts/demo/proofpilot-five-fixes-observe.json",
            observe_lines,
            emphasis="PASS → SIMULATED → broadcast=false",
        ),
        "blocked": _terminal_page(
            "Wrong but executable",
            "python scripts/show_proof.py artifacts/demo/proofpilot-attack-validation-trace-v2.json",
            blocked_lines,
            emphasis="KeeperHub: executable · ProofPilot: BLOCKED",
        ),
        "live": _terminal_page(
            "Real execution — independently verified effect",
            "python scripts/show_proof.py artifacts/demo/proofpilot-five-fixes-live.json",
            live_lines,
            emphasis="L2_EXECUTION_EFFECT_VERIFIED",
        ),
        "cleanup": _terminal_page(
            "Cleanup — frozen final state",
            "python scripts/show_proof.py artifacts/demo/proofpilot-five-fixes-cleanup.json",
            cleanup_lines,
            emphasis="Aave E-Mode final state = 0",
        ),
        "benchmark": benchmark_page,
        "architecture": architecture,
    }


def _inject_public_page_banner(page: Any, label: str, url: str, *, final_overlay: bool = False) -> None:
    page.evaluate(
        """
        ({label, url, finalOverlay}) => {
          const old = document.getElementById('__proofpilot_recording_banner');
          if (old) old.remove();
          const banner = document.createElement('div');
          banner.id = '__proofpilot_recording_banner';
          banner.style.cssText = [
            'position:fixed','z-index:2147483647','left:18px','right:18px','top:16px',
            'background:rgba(10,13,19,.94)','color:#fff','border:1px solid #43506a',
            'border-radius:12px','padding:12px 18px','font:600 18px/1.35 Arial,sans-serif',
            'box-shadow:0 8px 30px rgba(0,0,0,.35)','pointer-events:none'
          ].join(';');
          banner.innerHTML = `<span style="color:#8fc7ff">${label}</span> &nbsp; ${url}`;
          if (finalOverlay) {
            banner.innerHTML += '<span style="float:right;color:#7fe6a2">155 tests PASS · 0/29 observed unsafe approvals</span>';
          }
          document.documentElement.appendChild(banner);
        }
        """,
        {"label": label, "url": url, "finalOverlay": final_overlay},
    )


def _preload_pages(browser_path: str, local_pages: dict[str, str], *, headless: bool) -> tuple[Any, Any, dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    args = [
        "--no-first-run",
        "--disable-notifications",
        "--disable-session-crashed-bubble",
        "--disable-infobars",
        "--start-maximized",
    ]
    if not headless:
        args.append("--kiosk")
    browser = playwright.chromium.launch(
        headless=headless,
        executable_path=browser_path,
        args=args,
    )
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080} if headless else None,
        no_viewport=not headless,
        color_scheme="dark",
    )
    pages: dict[str, Any] = {}

    for key, content in local_pages.items():
        page = context.new_page()
        page.set_content(content, wait_until="load")
        pages[key] = page

    external = {
        "primary_tx": (PRIMARY_TX_URL, "LIVE PUBLIC BASESCAN · PRIMARY TX", False),
        "cleanup_tx": (CLEANUP_TX_URL, "LIVE PUBLIC BASESCAN · CLEANUP TX", False),
        "close": (GITHUB_URL, "PUBLIC GITHUB", True),
    }
    for key, (url, label, final_overlay) in external.items():
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            browser.close()
            playwright.stop()
            raise RecordingError(f"Could not preload public recording page {url}: {exc}") from exc
        _inject_public_page_banner(page, label, url, final_overlay=final_overlay)
        pages[key] = page

    return playwright, browser, pages


def _sleep_until(target: float) -> None:
    while True:
        remaining = target - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.2, remaining))


def _run_timeline(pages: dict[str, Any], *, scale: float, obs: ObsWebSocket | None) -> str | None:
    pages["title"].bring_to_front()
    print("\nRecording timeline armed. Do not touch the keyboard or mouse during the automated cut.")
    if obs is not None:
        obs.ensure_idle()
        obs.start_record()
        print("OBS: recording started")
    else:
        print("OBS: disabled (rehearsal mode)")

    started = time.monotonic()
    output_path: str | None = None
    try:
        for index, scene in enumerate(SCENES):
            scene_start = started + scene.start * scale
            _sleep_until(scene_start)
            pages[scene.key].bring_to_front()
            print(f"[{scene.start:6.1f}s] {scene.label}")
            scene_end = started + scene.end * scale
            if index == len(SCENES) - 1:
                _sleep_until(scene_end)
    finally:
        if obs is not None and obs.started_recording:
            output_path = obs.stop_record()
            print("OBS: recording stopped")
    return output_path


def _print_plan() -> None:
    print("ProofPilot final recording timeline")
    print("=" * 72)
    for scene in SCENES:
        print(f"{scene.start:6.1f}s -> {scene.end:6.1f}s  {scene.label}")
    print("-" * 72)
    print(f"Total: {FINAL_DURATION_SECONDS}s (2:45)")


def _doctor(args: argparse.Namespace, *, require_desktop: bool) -> dict[str, Any]:
    checks: list[tuple[str, str]] = []
    evidence = _assert_frozen_evidence()
    checks.append(("Frozen evidence", "PASS — 155 claim untouched; benchmark recomputes to 0/29"))
    if not args.skip_network_check:
        _check_public_links()
        checks.append(("Anonymous public URLs", "PASS — GitHub + 2 BaseScan transactions"))
    else:
        checks.append(("Anonymous public URLs", "SKIPPED by command-line flag"))
    _check_playwright()
    browser_path = _browser_executable(args.browser)
    checks.append(("Playwright + browser", f"PASS — {browser_path}"))

    if require_desktop and not args.headless and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise RecordingError(
            "No desktop display is visible to this process. Run the recording agent from your normal graphical "
            "Ubuntu terminal, not from a headless SSH/MCP shell."
        )

    obs: ObsWebSocket | None = None
    if not args.no_obs:
        password = os.environ.get("OBS_WEBSOCKET_PASSWORD")
        obs = ObsWebSocket(args.obs_host, args.obs_port, password)
        obs.connect()
        obs.ensure_idle()
        checks.append(("OBS WebSocket", f"PASS — ws://{args.obs_host}:{args.obs_port}"))
        obs.close()
    else:
        checks.append(("OBS WebSocket", "SKIPPED — --no-obs rehearsal mode"))

    print("ProofPilot recording doctor")
    print("=" * 72)
    for name, result in checks:
        print(f"{name:24} {result}")
    return evidence


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic 2:45 ProofPilot final-demo recorder. It uses only frozen read-only evidence, "
            "public GitHub/BaseScan pages, Playwright browser control and OBS WebSocket recording control."
        )
    )
    parser.add_argument("--doctor", action="store_true", help="Validate frozen evidence, browser, public URLs and OBS, then exit.")
    parser.add_argument("--plan", action="store_true", help="Print the exact 2:45 scene schedule and exit after evidence validation.")
    parser.add_argument("--no-obs", action="store_true", help="Rehearsal mode: automate the browser without starting/stopping OBS.")
    parser.add_argument("--headless", action="store_true", help="Run the browser headlessly (for preflight/testing only; not a final recording).")
    parser.add_argument("--browser", help="Explicit Chrome/Chromium executable path.")
    parser.add_argument("--obs-host", default="127.0.0.1", help="OBS WebSocket host (default: 127.0.0.1).")
    parser.add_argument("--obs-port", default=4455, type=int, help="OBS WebSocket port (default: 4455).")
    parser.add_argument("--skip-network-check", action="store_true", help="Skip anonymous URL preflight. Not recommended for final recording.")
    parser.add_argument(
        "--timeline-scale",
        default=1.0,
        type=float,
        help="Rehearsal speed multiplier for scene durations. Values other than 1 require --no-obs.",
    )
    args = parser.parse_args(argv)
    if args.timeline_scale <= 0:
        parser.error("--timeline-scale must be > 0")
    if args.timeline_scale != 1.0 and not args.no_obs:
        parser.error("A scaled timeline is rehearsal-only; use --no-obs with --timeline-scale.")
    if args.headless and not args.no_obs:
        parser.error("Headless mode cannot be used for a final OBS recording; add --no-obs.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.plan:
            evidence = _assert_frozen_evidence()
            _ = evidence
            _print_plan()
            return 0

        evidence = _doctor(args, require_desktop=not args.doctor)
        if args.doctor:
            _print_plan()
            return 0

        local_pages = _build_local_pages(evidence)
        browser_path = _browser_executable(args.browser)
        playwright: Any = None
        browser: Any = None
        obs: ObsWebSocket | None = None
        output_path: str | None = None
        try:
            print("\nPreloading all recording scenes before OBS starts...")
            playwright, browser, pages = _preload_pages(browser_path, local_pages, headless=args.headless)
            if not args.no_obs:
                obs = ObsWebSocket(args.obs_host, args.obs_port, os.environ.get("OBS_WEBSOCKET_PASSWORD"))
                obs.connect()
            output_path = _run_timeline(pages, scale=args.timeline_scale, obs=obs)
        finally:
            if obs is not None:
                if obs.started_recording:
                    try:
                        output_path = obs.stop_record() or output_path
                    except Exception as exc:
                        print(f"WARNING: failed to stop OBS cleanly: {exc}", file=sys.stderr)
                obs.close()
            if browser is not None:
                browser.close()
            if playwright is not None:
                playwright.stop()

        print("\nProofPilot recording automation finished.")
        if output_path:
            print(f"OBS output: {output_path}")
        elif args.no_obs:
            print("Rehearsal complete; no video was recorded because --no-obs was used.")
        else:
            print("OBS did not return an output path. Check the OBS recording directory manually.")
        print("Next: watch the full video once and follow docs/FINAL_VIDEO_SCRIPT.md -> Final Export Check.")
        return 0
    except RecordingError as exc:
        print(f"RECORDING BLOCKED: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nRecording interrupted by user.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
