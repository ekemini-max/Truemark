import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.chain import EvmChain, MockChain  # noqa: E402
from app.config import Settings  # noqa: E402
from app.deploy import deploy_registry  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import MemoryStore, SupabaseStore  # noqa: E402

ADMIN = "boss@truemark.test"
PASSWORD = "correct-horse-battery"


def make_evm_chain(store=None):
    from eth_account import Account
    from web3 import EthereumTesterProvider, Web3

    w3 = Web3(EthereumTesterProvider())
    acct = Account.create()
    w3.eth.send_transaction({"from": w3.eth.accounts[0], "to": acct.address, "value": w3.to_wei(10, "ether")})
    address, _ = deploy_registry(w3, acct.key.hex())
    return EvmChain(w3=w3, contract_address=address, private_key=acct.key.hex(), chain_name="Test EVM", explorer_tx_url="https://scan.test/tx/")


@pytest.fixture
def evm_chain():
    return make_evm_chain()


def build_settings(**extra):
    return Settings(
        _env_file=None,
        base_url="http://testserver",
        admin_emails=ADMIN,
        storage="memory",
        chain_mode="mock",
        **extra,
    )


@pytest.fixture(params=["memory+mock", "memory+evm", "supabase-fake+mock"])
def backend(request):
    """The same end-to-end scenarios run against every storage/ledger combination."""
    settings = build_settings()
    if request.param == "supabase-fake+mock":
        from fake_supabase import FakeSupabase

        fake = FakeSupabase()
        store = SupabaseStore("https://fake.supabase.co", "sb_secret_test", transport=fake.transport())
        from app.auth import SupabaseAuth

        auth = SupabaseAuth("https://fake.supabase.co", "sb_publishable_test", "sb_secret_test", transport=fake.transport())
        fake.admin_users_allowed = True
        chain = MockChain(store)
        return create_app(settings, store=store, auth=auth, chain=chain), fake
    store = MemoryStore()
    chain = make_evm_chain() if request.param == "memory+evm" else MockChain(store)
    return create_app(settings, store=store, chain=chain), None


def csrf(client) -> str:
    client.get("/")  # makes sure the CSRF cookie exists
    return client.cookies.get("tm_csrf")


def post(client, url, data=None, **kwargs):
    data = dict(data or {})
    data["csrf_token"] = csrf(client)
    return client.post(url, data=data, follow_redirects=False, **kwargs)


def signup(client, email, institution="Greenfield Secondary School", name="Ngozi Eze", password=PASSWORD):
    return post(client, "/signup", {"full_name": name, "institution_name": institution, "email": email, "password": password})


def login(client, email, password=PASSWORD):
    return post(client, "/login", {"email": email, "password": password})


def find_id(html: str, prefix: str) -> str:
    return re.search(prefix + r"([0-9a-f-]{36})", html).group(1)
