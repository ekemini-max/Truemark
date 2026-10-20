"""Check that your configuration works before you go live.

    python scripts/check_setup.py

Tests, in order: configuration, Supabase keys, the database tables, and the blockchain
connection. Each line says OK or FAIL and what to do about it. Secrets are never printed.
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.main import build_chain, build_store  # noqa: E402
from app.supa import api_headers  # noqa: E402

failures = 0


def report(ok: bool, label: str, fix: str = "") -> None:
    global failures
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        failures += 1
        if fix:
            print(f"       -> {fix}")


def main() -> int:
    s = get_settings()
    print("Configuration")
    report(bool(s.admin_email_set), "ADMIN_EMAILS is set", "Add your email to ADMIN_EMAILS.")
    report(s.base_url.startswith(("http://", "https://")), f"BASE_URL is {s.base_url}", "BASE_URL must start with http:// or https://")

    print("Database and sign-in")
    if not s.use_supabase:
        print("  --   Supabase is not configured: running on temporary in-memory storage.")
    else:
        base = s.supabase_url.rstrip("/")
        try:
            r = httpx.get(f"{base}/auth/v1/settings", headers=api_headers(s.supabase_publishable_key), timeout=15)
            report(r.status_code == 200, "Publishable key is accepted", "Check SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY (setup guide, step 3).")
            r = httpx.get(f"{base}/auth/v1/admin/users", params={"per_page": 1}, headers=api_headers(s.supabase_secret_key), timeout=15)
            report(r.status_code == 200, "Secret key is accepted", "Check SUPABASE_SECRET_KEY. It starts with sb_secret_ (or is the long service_role key).")
        except httpx.HTTPError as exc:
            report(False, f"Supabase is reachable ({exc.__class__.__name__})", "Check SUPABASE_URL, and that the project is not paused.")
        try:
            build_store(s).ping()
            report(True, "Tables exist and the server can read them")
        except Exception as exc:
            report(False, "Tables exist and the server can read them", f"Run supabase/schema.sql in the SQL Editor (step 2). Detail: {str(exc)[:140]}")

    print(f"Ledger ({s.chain_mode})")
    if s.chain_mode != "evm":
        print("  --   Simulated ledger: fingerprints are kept in your database and labelled as a simulation.")
    else:
        try:
            status = build_chain(s, None).status()
        except Exception as exc:
            report(False, "Wallet and contract settings are valid", f"{str(exc)[:160]}")
            status = None
        if status:
            report(bool(status.get("connected")), f"Connected to {status['name']}", status.get("error") or "Check RPC_URL (step 5).")
            if status.get("connected"):
                report(status.get("chain_id") == s.chain_id, f"Network id is {status.get('chain_id')}", f"CHAIN_ID is {s.chain_id}; make them match.")
                report(status.get("balance", 0) > 0, f"Wallet balance is {status.get('balance', 0):.4f}", "Request test tokens for the wallet address from a faucet (step 4).")
                report(bool(status.get("is_operator")), "Wallet is allowed to write to the contract", "Deploy the contract from this same wallet (step 6).")

    print()
    if failures:
        print(f"{failures} problem{'s' if failures != 1 else ''} to fix.")
        return 1
    print("Everything checked looks good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
