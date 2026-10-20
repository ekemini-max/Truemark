"""Ledger adapters.

  * MockChain - keeps fingerprints in the database. Honest about it: everything that reads
                `is_simulated` labels the result as a simulation, never as a blockchain.
  * EvmChain  - anchors fingerprints in the TrueMarkRegistry smart contract on an EVM testnet
                (Polygon Amoy, Sepolia, ...) through web3.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .config import ARTIFACT_PATH
from .store import Conflict

log = logging.getLogger("truemark.chain")


class ChainError(Exception):
    """The ledger could not complete the request."""


@dataclass
class AnchorResult:
    tx_hash: str
    block_number: Optional[int]
    timestamp: int


@dataclass
class ChainState:
    exists: bool
    revoked: bool = False
    issuer_ref: str = ""
    timestamp: Optional[int] = None


def _check_hash(h: str) -> str:
    if not (isinstance(h, str) and len(h) == 66 and h.startswith("0x")):
        raise ChainError("Fingerprint must be a 0x-prefixed 32-byte hex string.")
    try:
        int(h, 16)
    except ValueError as exc:
        raise ChainError("Fingerprint is not valid hex.") from exc
    return h.lower()


# --------------------------------------------------------------------------- simulation


class MockChain:
    is_simulated = True
    name = "Simulated ledger"

    def __init__(self, store) -> None:
        self.store = store

    def anchor(self, h: str, issuer_ref: str) -> AnchorResult:
        h = _check_hash(h)
        ts = int(time.time())
        try:
            self.store.ledger_put(h, issuer_ref, ts)
        except Conflict as exc:
            raise ChainError("This fingerprint is already anchored.") from exc
        return AnchorResult("0x" + hashlib.sha256(f"sim:{h}:{ts}".encode()).hexdigest(), None, ts)

    def revoke(self, h: str) -> AnchorResult:
        h = _check_hash(h)
        row = self.store.ledger_get(h)
        if not row:
            raise ChainError("This fingerprint is not anchored.")
        if row["revoked"]:
            raise ChainError("This record is already revoked on the blockchain.")
        self.store.ledger_revoke(h)
        ts = int(time.time())
        return AnchorResult("0x" + hashlib.sha256(f"sim-revoke:{h}:{ts}".encode()).hexdigest(), None, ts)

    def lookup(self, h: str) -> ChainState:
        row = self.store.ledger_get(_check_hash(h))
        if not row:
            return ChainState(False)
        return ChainState(True, bool(row["revoked"]), row["issuer_ref"], int(row["ts"]))

    def tx_url(self, tx_hash: Optional[str]) -> Optional[str]:
        return None

    def address_url(self, address: str) -> Optional[str]:
        return None

    def status(self) -> dict[str, Any]:
        return {"mode": "mock", "name": self.name, "simulated": True, "connected": True}


# --------------------------------------------------------------------------- real chain


class EvmChain:
    is_simulated = False

    def __init__(
        self,
        *,
        contract_address: str,
        private_key: str,
        rpc_url: str = "",
        chain_id: Optional[int] = None,
        chain_name: str = "EVM testnet",
        explorer_tx_url: str = "",
        explorer_address_url: str = "",
        w3: Any = None,
        artifact_path: Path = ARTIFACT_PATH,
    ) -> None:
        from eth_account import Account
        from web3 import Web3

        self._Web3 = Web3
        if w3 is None:
            from web3.middleware import ExtraDataToPOAMiddleware

            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
            # Polygon (Amoy) and several other networks use block headers that web3.py rejects by default.
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.w3 = w3
        artifact = json.loads(Path(artifact_path).read_text())
        self.contract = self.w3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=artifact["abi"])
        self.account = Account.from_key(private_key)
        self._chain_id = chain_id
        self.name = chain_name
        self.explorer_tx_url = explorer_tx_url
        self.explorer_address_url = explorer_address_url
        self._lock = threading.Lock()

    @property
    def chain_id(self) -> int:
        return self._chain_id or self.w3.eth.chain_id

    @staticmethod
    def _b32(h: str) -> bytes:
        return bytes.fromhex(_check_hash(h)[2:])

    def _send(self, fn) -> AnchorResult:
        w3 = self.w3
        addr = self.account.address
        with self._lock:  # one transaction at a time keeps nonces in order
            try:
                params = {
                    "from": addr,
                    "nonce": w3.eth.get_transaction_count(addr, "pending"),
                    "chainId": self.chain_id,
                    "gasPrice": int(w3.eth.gas_price * 1.2),
                }
                params["gas"] = int(fn.estimate_gas({"from": addr}) * 1.3) + 10_000
                signed = self.account.sign_transaction(fn.build_transaction(params))
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120, poll_latency=2)
            except ChainError:
                raise
            except Exception as exc:  # network, gas, revert...
                raise ChainError(self._explain(exc)) from exc
        if receipt["status"] != 1:
            raise ChainError("The blockchain transaction failed (reverted).")
        block = w3.eth.get_block(receipt["blockNumber"])
        return AnchorResult(w3.to_hex(tx_hash), int(receipt["blockNumber"]), int(block["timestamp"]))

    @staticmethod
    def _explain(exc: Exception) -> str:
        text = str(exc)
        low = text.lower()
        if "insufficient funds" in low or "insufficient balance" in low:
            return "The issuer wallet is out of test tokens. Top it up from a faucet (see the setup guide)."
        if "alreadyanchored" in low or "already anchored" in low:
            return "This fingerprint is already anchored."
        if "notoperator" in low:
            return "The issuer wallet is not an approved operator of the contract."
        if "timed out" in low or "timeout" in low:
            return "The blockchain network is slow right now. Try again in a minute."
        return f"Blockchain error: {text[:200]}"

    def anchor(self, h: str, issuer_ref: str) -> AnchorResult:
        if self.lookup(h).exists:  # cheap read first: avoids paying gas for a guaranteed revert
            raise ChainError("This fingerprint is already anchored.")
        return self._send(self.contract.functions.anchor(self._b32(h), self._b32(issuer_ref)))

    def revoke(self, h: str) -> AnchorResult:
        state = self.lookup(h)
        if not state.exists:
            raise ChainError("This fingerprint is not anchored.")
        if state.revoked:
            raise ChainError("This record is already revoked on the blockchain.")
        return self._send(self.contract.functions.revoke(self._b32(h)))

    def lookup(self, h: str) -> ChainState:
        try:
            exists, revoked, ref, ts = self.contract.functions.check(self._b32(h)).call()
        except Exception as exc:
            raise ChainError(f"Could not read the blockchain: {str(exc)[:160]}") from exc
        return ChainState(bool(exists), bool(revoked), "0x" + bytes(ref).hex(), int(ts) if exists else None)

    def tx_url(self, tx_hash: Optional[str]) -> Optional[str]:
        return f"{self.explorer_tx_url}{tx_hash}" if tx_hash and self.explorer_tx_url else None

    def address_url(self, address: str) -> Optional[str]:
        return f"{self.explorer_address_url}{address}" if address and self.explorer_address_url else None

    def status(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "mode": "evm",
            "name": self.name,
            "simulated": False,
            "wallet": self.account.address,
            "contract": self.contract.address,
            "connected": False,
        }
        try:
            info["chain_id"] = self.w3.eth.chain_id
            info["block"] = self.w3.eth.block_number
            info["balance"] = float(self._Web3.from_wei(self.w3.eth.get_balance(self.account.address), "ether"))
            info["is_operator"] = bool(self.contract.functions.operators(self.account.address).call())
            info["connected"] = True
        except Exception as exc:
            info["error"] = str(exc)[:200]
        return info
