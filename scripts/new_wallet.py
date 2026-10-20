"""Create a throwaway wallet for the TrueMark server to sign testnet transactions with.

    python scripts/new_wallet.py

Copy the private key into ISSUER_PRIVATE_KEY (in .env or Render's Environment tab) and send the
ADDRESS to a testnet faucet. Never use a wallet that holds real money for this.
"""
from eth_account import Account

account = Account.create()
print("Address (share this, paste it into a faucet):")
print(f"  {account.address}\n")
print("Private key (secret: goes in ISSUER_PRIVATE_KEY, never in git, chat or screenshots):")
print(f"  {account.key.hex()}\n")
print("This wallet is for testnet only. Anyone who sees the private key can spend its tokens.")
