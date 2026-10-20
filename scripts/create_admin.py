"""Create the first admin account in Supabase.

    python scripts/create_admin.py you@example.com

The email must also be listed in ADMIN_EMAILS. The account is created already confirmed (no
email is sent), and the first time you sign in at /login it becomes an approved admin.
Admin emails cannot be registered from the public sign-up page, so nobody can claim yours first.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import AuthError, SupabaseAuth  # noqa: E402
from app.config import get_settings  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print("Usage: python scripts/create_admin.py you@example.com")
        return 1
    email = sys.argv[1].strip().lower()
    s = get_settings()
    if not s.use_supabase:
        print("Supabase is not configured, so there is nothing to create. With in-memory storage, set DEV_SEED=true instead.")
        return 1
    if email not in s.admin_email_set:
        print(f"{email} is not in ADMIN_EMAILS. Add it there first, then run this again.")
        return 1
    password = getpass.getpass("Choose a password (at least 8 characters, not shown): ")
    if len(password) < 8 or password != getpass.getpass("Type it again: "):
        print("Passwords did not match, or were shorter than 8 characters.")
        return 1
    auth = SupabaseAuth(s.supabase_url, s.supabase_publishable_key, s.supabase_secret_key)
    try:
        auth.sign_up(email, password, "TrueMark Admin", "TrueMark")
    except AuthError as exc:
        print(f"Could not create the account: {exc}")
        return 1
    print(f"Created {email}. Sign in at {s.base_url.rstrip('/')}/login. You will land on the dashboard with an Admin link in the menu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
