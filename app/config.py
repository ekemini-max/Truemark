from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = ROOT / "contracts" / "build" / "TrueMarkRegistry.json"


class Settings(BaseSettings):
    """All configuration comes from environment variables (or a local .env file)."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # Public URL of the site. Used inside QR codes, so set it to your live address.
    base_url: str = "http://localhost:8000"

    # Storage: "auto" uses Supabase when its keys are present, otherwise temporary memory.
    storage: str = "auto"  # auto | supabase | memory
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""

    # Comma-separated emails that become admins when they sign in.
    admin_emails: str = ""
    allow_signup: bool = True

    # Ledger: "mock" keeps fingerprints in the database (clearly labelled as a simulation),
    # "evm" anchors on a real blockchain.
    chain_mode: str = "mock"  # mock | evm
    chain_name: str = "Polygon Amoy testnet"
    chain_id: int = 80002
    rpc_url: str = ""
    contract_address: str = ""
    issuer_private_key: str = ""
    explorer_tx_url: str = "https://amoy.polygonscan.com/tx/"
    explorer_address_url: str = "https://amoy.polygonscan.com/address/"

    # Local demo only: create sample accounts and records when running on memory storage.
    dev_seed: bool = False

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def use_supabase(self) -> bool:
        if self.storage == "supabase":
            return True
        if self.storage == "memory":
            return False
        return bool(self.supabase_url and self.supabase_secret_key)

    @property
    def cookie_secure(self) -> bool:
        return self.base_url.lower().startswith("https://")

    def problems(self) -> list[str]:
        """Human-readable configuration problems, shown in the admin status page and logs."""
        found: list[str] = []
        if self.use_supabase:
            if not self.supabase_url:
                found.append("SUPABASE_URL is missing.")
            if not self.supabase_publishable_key:
                found.append("SUPABASE_PUBLISHABLE_KEY is missing.")
            if not self.supabase_secret_key:
                found.append("SUPABASE_SECRET_KEY is missing.")
        elif self.cookie_secure:
            found.append("Running on temporary memory storage: all data is lost on restart. Set the Supabase variables.")
        if self.chain_mode == "evm":
            for name, value in (
                ("RPC_URL", self.rpc_url),
                ("CONTRACT_ADDRESS", self.contract_address),
                ("ISSUER_PRIVATE_KEY", self.issuer_private_key),
            ):
                if not value:
                    found.append(f"{name} is missing (required when CHAIN_MODE=evm).")
        if not self.admin_email_set:
            found.append("ADMIN_EMAILS is empty, so nobody can open the admin page.")
        return found


@lru_cache
def get_settings() -> Settings:
    return Settings()
