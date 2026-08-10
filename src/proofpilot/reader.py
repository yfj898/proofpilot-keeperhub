from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Any

from .policy import looks_like_evm_address


BASE_SEPOLIA_RPC_URL = "https://sepolia.base.org"
WEI_PER_ETH = Decimal(10**18)


class ReadLayerError(RuntimeError):
    pass


class BaseSepoliaReader:
    """Independent read-only Base Sepolia JSON-RPC client.

    It contains no key material, signing, or broadcast surface. ProofPilot uses it to
    verify KeeperHub execution against an independent chain view.
    """

    def __init__(
        self,
        rpc_url: str = BASE_SEPOLIA_RPC_URL,
        timeout: float = 20.0,
        *,
        prefer_curl: bool = False,
        fallback_rpc_urls: tuple[str, ...] = (),
    ):
        self.rpc_url = rpc_url
        self.rpc_urls = tuple(dict.fromkeys((rpc_url, *fallback_rpc_urls)))
        self.timeout = timeout
        self.prefer_curl = prefer_curl
        self._next_id = 1

    def get_native_balance(self, address: str, *, block: str = "latest") -> Decimal:
        if not looks_like_evm_address(address):
            raise ValueError("address must be a 20-byte EVM address")
        result = self._rpc("eth_getBalance", [address, block])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise ReadLayerError("eth_getBalance returned a non-quantity result")
        return Decimal(int(result, 16)) / WEI_PER_ETH

    def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        if not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
            raise ValueError("tx_hash must be a 0x-prefixed transaction hash")
        result = self._rpc("eth_getTransactionReceipt", [tx_hash])
        if result is None:
            return None
        if not isinstance(result, dict):
            raise ReadLayerError("eth_getTransactionReceipt returned an invalid result")
        return result

    def get_transaction(self, tx_hash: str) -> dict[str, Any] | None:
        """Read a raw transaction envelope from the independent JSON-RPC layer."""
        if not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
            raise ValueError("tx_hash must be a 0x-prefixed transaction hash")
        result = self._rpc("eth_getTransactionByHash", [tx_hash])
        if result is None:
            return None
        if not isinstance(result, dict):
            raise ReadLayerError("eth_getTransactionByHash returned an invalid result")
        return result

    def eth_call(self, to_address: str, data: str, *, block: str = "latest") -> str:
        """Perform a read-only EVM call with already encoded calldata."""
        if not looks_like_evm_address(to_address):
            raise ValueError("to_address must be a 20-byte EVM address")
        if not isinstance(data, str) or not data.startswith("0x"):
            raise ValueError("data must be 0x-prefixed calldata")
        result = self._rpc("eth_call", [{"to": to_address, "data": data}, block])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise ReadLayerError("eth_call returned an invalid result")
        return result

    def read_uint256(self, to_address: str, selector: str, *, block: str = "latest") -> int:
        result = self.eth_call(to_address, selector, block=block)
        if result == "0x":
            raise ReadLayerError("uint256 eth_call returned empty data")
        return int(result, 16)

    def read_bool(self, to_address: str, selector: str, *, block: str = "latest") -> bool:
        value = self.read_uint256(to_address, selector, block=block)
        if value not in {0, 1}:
            raise ReadLayerError(f"bool eth_call returned non-boolean word: {value}")
        return bool(value)

    def get_storage_uint256(
        self,
        to_address: str,
        slot: int = 0,
        *,
        block: str = "latest",
    ) -> int:
        """Read a raw uint256 storage slot from the independent Base RPC."""
        if not looks_like_evm_address(to_address):
            raise ValueError("to_address must be a 20-byte EVM address")
        if slot < 0:
            raise ValueError("slot must be non-negative")
        result = self._rpc("eth_getStorageAt", [to_address, hex(slot), block])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise ReadLayerError("eth_getStorageAt returned an invalid result")
        return int(result, 16)

    def get_code(self, address: str, *, block: str = "latest") -> str:
        if not looks_like_evm_address(address):
            raise ValueError("address must be a 20-byte EVM address")
        result = self._rpc("eth_getCode", [address, block])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise ReadLayerError("eth_getCode returned an invalid result")
        return result

    def erc20_balance_of(self, token: str, account: str, *, block: str = "latest") -> int:
        """Read ERC-20 balanceOf(address) using its stable selector."""
        if not looks_like_evm_address(account):
            raise ValueError("account must be a 20-byte EVM address")
        data = "0x70a08231" + account[2:].lower().rjust(64, "0")
        result = self.eth_call(token, data, block=block)
        if result == "0x":
            raise ReadLayerError("ERC20 balanceOf returned empty data")
        return int(result, 16)

    def aave_user_emode(
        self,
        pool: str,
        account: str,
        *,
        block: str = "latest",
    ) -> int:
        """Read Aave V3 Pool.getUserEMode(address) through the independent RPC layer."""

        if not looks_like_evm_address(account):
            raise ValueError("account must be a 20-byte EVM address")
        # keccak256("getUserEMode(address)")[:4]
        data = "0xeddf1b79" + account[2:].lower().rjust(64, "0")
        result = self.eth_call(pool, data, block=block)
        if result == "0x":
            raise ReadLayerError("Aave getUserEMode returned empty data")
        return int(result, 16)

    def chain_id(self) -> str:
        result = self._rpc("eth_chainId", [])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise ReadLayerError("eth_chainId returned an invalid result")
        return str(int(result, 16))

    def _rpc(self, method: str, params: list[Any]) -> Any:
        request_id = self._next_id
        self._next_id += 1
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        ).encode("utf-8")
        if self.prefer_curl:
            errors: list[str] = []
            for rpc_url in self.rpc_urls:
                try:
                    body = self._rpc_via_curl(payload, rpc_url=rpc_url)
                    if not isinstance(body, dict):
                        raise ReadLayerError("Base Sepolia RPC returned a non-object response")
                    if body.get("error") is not None:
                        raise ReadLayerError(f"Base Sepolia RPC error: {body['error']}")
                    if "result" not in body:
                        raise ReadLayerError("Base Sepolia RPC response has no result")
                    return body["result"]
                except ReadLayerError as exc:
                    errors.append(f"{rpc_url}: {exc}")
            raise ReadLayerError("All Base Sepolia RPC candidates failed: " + " | ".join(errors))

        request = urllib.request.Request(
            self.rpc_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "ProofPilot/0.1 read-only verifier",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError):
            # Some Linux/TLS combinations observed during the hackathon timed out
            # during urllib's TLS handshake while curl to the same official Base RPC
            # succeeded immediately.  Keep a read-only curl fallback so verification
            # does not depend on one Python TLS stack.
            body = self._rpc_via_curl(payload)
        except json.JSONDecodeError as exc:
            raise ReadLayerError(f"Base Sepolia RPC returned invalid JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise ReadLayerError("Base Sepolia RPC returned a non-object response")
        if body.get("error") is not None:
            raise ReadLayerError(f"Base Sepolia RPC error: {body['error']}")
        if "result" not in body:
            raise ReadLayerError("Base Sepolia RPC response has no result")
        return body["result"]

    def _rpc_via_curl(
        self,
        payload: bytes,
        *,
        rpc_url: str | None = None,
    ) -> dict[str, Any]:
        endpoint = rpc_url or self.rpc_url
        try:
            completed = subprocess.run(
                [
                    "curl",
                    "-sS",
                    "--fail-with-body",
                    "--max-time",
                    str(max(1, int(self.timeout))),
                    "-H",
                    "content-type: application/json",
                    "--data-binary",
                    "@-",
                    endpoint,
                ],
                input=payload,
                capture_output=True,
                check=False,
                timeout=self.timeout + 2,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReadLayerError(f"Base Sepolia curl fallback failed to start: {exc}") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            raise ReadLayerError(
                f"Base Sepolia curl fallback failed (exit={completed.returncode}): {stderr}"
            )
        try:
            parsed = json.loads(completed.stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ReadLayerError("Base Sepolia curl fallback returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise ReadLayerError("Base Sepolia curl fallback returned a non-object response")
        return parsed

