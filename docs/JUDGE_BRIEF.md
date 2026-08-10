# ProofPilot Judge Brief

**审查日期：2026-08-10**  
**结论：技术面 Strong contender；public repository 与 demo video URL 未提供前仍是 submission-blocked。**

## Problem

ProofPilot 解决的不是“交易能否执行”，而是：

> **一笔由 Agent 生成、ABI-valid、simulation-valid 的交易，是否精确符合用户给出的 machine-checkable mandate？**

`setUserEMode(0)` 可以在 Aave Base Sepolia 成功模拟，但不满足“设为 category 1”。这就是 `Executable ≠ Authorized`。

## Why KeeperHub Alone Does Not Solve It

KeeperHub 正确提供 agent-native MCP discovery、simulation、execution、status、idempotency 和 transaction link。它回答执行与可靠性问题；它不负责定义用户是否授权了某个 target/function/argument/value。ProofPilot 不替代 KeeperHub，而是在其 write boundary 前增加 deterministic conformance check。

官方资料：[KeeperHub competition announcement](https://www.linkedin.com/posts/keeperhub_two-months-ago-we-backed-a-prize-track-at-activity-7475112177595551744-FUhD)、[MCP Server](https://docs.keeperhub.com/ai-tools/mcp-server)、[Direct Execution](https://docs.keeperhub.com/api/direct-execution)。

## Mechanism

```text
Bounded user mandate
  -> typed Intent IR
  -> external LLM candidate ProposedAction
  -> exact chain / target / function / args / value / effect checks
  -> KeeperHub execute_contract_call simulation
  -> Observe / Confirm / Autonomous
  -> KeeperHub execution + status
  -> independent receipt / Aave event / post-state
  -> L2_EXECUTION_EFFECT_VERIFIED
```

LLM 没有 KeeperHub credential、wallet key 或 write tool。它只能提出候选，授权结果来自 deterministic code。Base Sepolia Aave 走 official hosted MCP 的 generic `execute_contract_call`，不是 Aave protocol plugin。

## Real Agent and Real Execution

最准确的分类是 **STRUCTURED PROPOSAL MODEL**：外部模型真实生成候选，但 desired action 已由 bounded mandate 确定。正确说法是“The agent proposes an action for a bounded user mandate.”

两笔 hardened Aave 交易经只读复核：`0xdb0…f90` 完成 E-Mode `0→1`，`0x2f42…780` cleanup `1→0`；receipt、Aave event、当前 state=0 均为 live evidence。KeeperHub `completed`、execution ID 和 journal linkage 为 preserved artifact evidence；最终包装阶段没有重新提交或产生新交易。

## 0/29 Evidence

对 frozen artifact 独立重算：

| Metric | Result |
| --- | ---: |
| Scheduled / provider-success / parse-valid / ABI-bound | 50 / 48 / 48 / 47 |
| Independently labeled semantic attacks | 40 |
| KeeperHub simulation-valid semantic attacks | 29 |
| ProofPilot observed unsafe approvals | **0 / 29** |
| Protocol ABI allowlist unsafe approvals | **29 / 29** |
| Static intended-function allowlist unsafe approvals | **28 / 29** |

Artifact `c88901d6…46ef`、defender `68fda657…527e`、harness `d742351c…d436` 均重算匹配。两次 provider failure、三次 ABI failure 和十一项 simulation-invalid semantic attacks 均保留，无 replacement。Benchmark **不是 circular**，但仍 narrow/tailored：28/29 是 wrong category，只有一个 wrong-function/args case。只能说“0/29 observed in this frozen Aave E-Mode benchmark”。

## Why It Is Different

- 不是 KeeperHub wrapper 或 second-agent critic；KeeperHub 仍是唯一 execution layer，authorization 不由 LLM 投票。
- 比 function allowlist 多 exact args/value/state/effects、payload commitment 和 postcondition，但仍属于 policy-engine 家族。
- 与上一届 [Tradewise](https://ethglobal.com/showcase/tradewise-agentlab-hpg3y)、[Keeper-Gate](https://ethglobal.com/showcase/keeper-gate-hr2jk)、[ZW.ARM](https://ethglobal.com/showcase/zw-arm-enbkh) 机制不重复；与 transaction validator/policy engine 概念重叠为 HIGH。

## Fixed Security Blockers and Remaining Limits

1. **Duplicate recovery fixed**：semantic identity 与 payload commitment 已分离；changed payload + unresolved operation 强制 reconciliation，stale PREPARED 不重发。
2. **Secret hygiene fixed**：backup codes 已移出项目树；`.env`/journal 权限收紧；source checker 与 strict public export 均 PASS。
3. **Compiler fixed**：显式 wrong chain、deadline、conditional、conflict、from/to ambiguity 和 negation均 consume-or-reject。
4. **Claims narrowed**：项目是 multi-protocol prototype；trace 是 self-verifying；证据等级是 `L2_EXECUTION_EFFECT_VERIFIED`，不是 full trace/L1 finality。
5. **Reproducibility**：155 tests、compileall PASS。最近一次 credentialed Observe demo 的 Doctor READY，但 provider proposal 在 simulation 前 fail-closed，broadcast=false。
6. **SUBMISSION BLOCKER**：`<ADD_GITHUB_URL_BEFORE_SUBMISSION>` 与
   `<ADD_DEMO_VIDEO_URL_BEFORE_SUBMISSION>` 尚未替换；不得伪造。

## Judge Decision

ProofPilot 是真实的 KeeperHub-native working concept：simulation-valid 调用仍可能不符合授权，而 deterministic mandate boundary 能在 write 前阻断。真实 execution、live effect 和冻结 provenance 是强项。

P0 与关键 P1 已修，当前技术面可列入 **Strong contender**。但 submission links 未完成前，形式状态仍是 **NOT READY**；不得继续扩功能，只需补真实 URL 后提交为：

> **A bounded, deterministic intent-to-transaction authorization prototype for KeeperHub agents, validated by real Base Sepolia execution and a narrow, frozen 0/29 Aave E-Mode benchmark.**
