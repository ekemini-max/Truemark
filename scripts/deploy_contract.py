"""Deploy the TrueMarkRegistry contract to the network in RPC_URL.

    python scripts/deploy_contract.py

Needs RPC_URL, ISSUER_PRIVATE_KEY and CHAIN_ID in .env, and a little testnet balance in that
wallet. Prints the CONTRACT_ADDRESS to paste into .env (and into Render).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eth_account import Account  # noqa: E402
from web3 import Web3  # noqa: E402
from web3.middleware import ExtraDataToPOAMiddleware  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.deploy import deploy_registry  # noqa: E402


def main() -> int:
    s = get_settings()
    if not s.rpc_url or not s.issuer_private_key:
        print("Set RPC_URL and ISSUER_PRIVATE_KEY in .env first (see docs/SETUP_GUIDE.md, steps 4 and 5).")
        return 1
    w3 = Web3(Web3.HTTPProvider(s.rpc_url, request_kwargs={"timeout": 30}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        print("Could not reach RPC_URL. Check the address, or try another free RPC.")
        return 1
    actual_chain = w3.eth.chain_id
    if s.chain_id and actual_chain != s.chain_id:
        print(f"RPC_URL is chain {actual_chain} but CHAIN_ID is {s.chain_id}. Fix one of them.")
        return 1
    account = Account.from_key(s.issuer_private_key)
    balance = w3.eth.get_balance(account.address)
    print(f"Network chain id: {actual_chain}")
    print(f"Deployer wallet:  {account.address}")
    print(f"Balance:          {Web3.from_wei(balance, 'ether')} (native test token)")
    if balance == 0:
        print("\nThis wallet has no test tokens. Request some from a faucet (setup guide, step 4), then run this again.")
        return 1
    print("\nDeploying... this takes up to a minute.")
    try:
        address, tx_hash = deploy_registry(w3, s.issuer_private_key, chain_id=actual_chain)
    except Exception as exc:
        print(f"Deployment failed: {str(exc)[:300]}")
        return 1
    print("\nDeployed.")
    print(f"  CONTRACT_ADDRESS={address}")
    if s.explorer_address_url:
        print(f"  Contract: {s.explorer_address_url}{address}")
    if s.explorer_tx_url:
        print(f"  Deployment transaction: {s.explorer_tx_url}{tx_hash}")
    print("\nAdd the CONTRACT_ADDRESS line to .env (and to Render), set CHAIN_MODE=evm, then run scripts/check_setup.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
