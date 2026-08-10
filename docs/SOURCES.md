# Research Sources

Snapshot: 2026-08-08. Prefer primary/official sources.

## Competition / organizer

1. **KeeperHub — Agents Onchain announcement (LinkedIn)**  
   https://www.linkedin.com/posts/keeperhub_two-months-ago-we-backed-a-prize-track-at-activity-7475112177595551744-FUhD  
   Used for: build dates, prize breakdown, framework freedom, real-transaction/no-mock requirement, onboarding bounties.

2. **DoraHacks — KeeperHub Agents Onchain detail**  
   https://dorahacks.io/hackathon/agents-onchain/detail  
   Note: automated fetch returned HTTP 405 during this research. Manually verify exact submission cutoff and eligibility here.

## KeeperHub technical docs

3. **KeeperHub Hackathon Quickstart**  
   https://docs.keeperhub.com/quickstart  
   Used for: MCP endpoint, key types, supported testnets, rate limits, safe simulate->execute->poll->transactionLink sequence.

4. **KeeperHub MCP Server reference**  
   https://docs.keeperhub.com/ai-tools/mcp-server  
   Used for: 30+ tool inventory, direct execution tools, simulation rules, idempotency, status polling, per-workflow MCP servers.

5. **KeeperHub — AI Agent Execution Layer**  
   https://keeperhub.com/agents  
   Used for: execution/reliability positioning, simulation, retries, routing, audit, framework-agnostic architecture.

6. **KeeperHub + Blockscout — Why Onchain AI Agents Need a Read Layer and an Execute Layer**  
   https://keeperhub.com/blog/011-detect-decide-execute-blockscout  
   Used for: read/execute separation and two-MCP architecture.

## Prior judging signals

7. **KeeperHub — That's a Wrap on our First Hackathon. Here Is What 180 Builders Taught Us.**  
   https://keeperhub.com/blog/010-openagents-hackathon-wrap  
   Used for: 180-project review, Keeper-Gate architecture, ZW.ARM critic-agent/failure-mode praise, feedback bounty expectations.

## Current agent/model technology

8. **OpenAI — GPT-5.6: Frontier intelligence that scales with your ambition**  
   https://openai.com/index/gpt-5-6/  
   Used for: Programmatic Tool Calling, multi-agent beta, long-context/agentic capability claims.

9. **Model Context Protocol — 2026-07-28 Specification release**  
   https://blog.modelcontextprotocol.io/posts/2026-07-28/  
   Used for: stateless core, Tasks extension, authorization hardening, Tier-1 SDK support.

## Optional stretch research

10. **ERC-8004: Trustless Agents**  
    https://eips.ethereum.org/EIPS/eip-8004  
    Used for: optional identity/reputation/validation extension. Not part of MVP.

## ProofPilot 3.0 intent / protocol sources

11. **EIP-712: Ethereum typed structured data hashing and signing**  
    https://eips.ethereum.org/EIPS/eip-712  
    Used for: the shape of the unsigned typed mandate commitment. ProofPilot does not
    handle the signing key and separately keeps nonce/deadline replay controls.

12. **BGD Labs / Aave Address Book — Aave V3 Base Sepolia**  
    https://github.com/bgd-labs/aave-address-book/blob/main/src/AaveV3BaseSepolia.sol  
    Used for: current Pool, WETH Gateway, aWETH, variable-debt WETH, and test-USDC
    deployment addresses. Runtime code presence is independently checked through Base
    Sepolia RPC before use.

13. **Aave Help — Accessing Aave / testnet deployments**  
    https://aave.com/help/aave-101/accessing-aave  
    Used for: confirmation that Base Sepolia is an Aave V3 testnet deployment.

## Source-confidence notes

- Competition rules: use KeeperHub organizer posts + DoraHacks live page; live DoraHacks page wins on conflicts.
- Technical behavior: runtime KeeperHub MCP schema wins over documentation if they differ.
- Third-party aggregators are intentionally not used as authoritative sources for prize or eligibility claims.

