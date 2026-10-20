"""Deploy the TrueMarkRegistry contract. Used by scripts/deploy_contract.py and by the tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import ARTIFACT_PATH


def deploy_registry(w3: Any, private_key: str, *, chain_id: int | None = None, artifact_path: Path = ARTIFACT_PATH) -> tuple[str, str]:
    """Deploy the contract from the wallet behind `private_key`. Returns (contract_address, tx_hash)."""
    from eth_account import Account

    artifact = json.loads(Path(artifact_path).read_text())
    account = Account.from_key(private_key)
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
    params = {
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, "pending"),
        "chainId": chain_id or w3.eth.chain_id,
        "gasPrice": int(w3.eth.gas_price * 1.2),
    }
    tx = contract.constructor().build_transaction(params)
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.3) + 20_000
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180, poll_latency=2)
    if receipt["status"] != 1:
        raise RuntimeError("Deployment transaction failed.")
    return receipt["contractAddress"], w3.to_hex(tx_hash)
