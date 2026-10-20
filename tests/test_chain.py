import pytest
from eth_account import Account

from app.chain import ChainError, EvmChain, MockChain
from app.store import MemoryStore

H1 = "0x" + "11" * 32
REF = "0x" + "22" * 32


@pytest.fixture(params=["mock", "evm"])
def chain(request, evm_chain):
    return MockChain(MemoryStore()) if request.param == "mock" else evm_chain


def test_anchor_then_lookup(chain):
    assert chain.lookup(H1).exists is False
    result = chain.anchor(H1, REF)
    assert result.tx_hash.startswith("0x")
    state = chain.lookup(H1)
    assert state.exists and not state.revoked and state.issuer_ref == REF and state.timestamp


def test_cannot_anchor_twice(chain):
    chain.anchor(H1, REF)
    with pytest.raises(ChainError, match="already anchored"):
        chain.anchor(H1, REF)


def test_revoke(chain):
    chain.anchor(H1, REF)
    chain.revoke(H1)
    assert chain.lookup(H1).revoked is True
    with pytest.raises(ChainError):
        chain.revoke(H1)


def test_revoke_unknown_hash_fails(chain):
    with pytest.raises(ChainError, match="not anchored"):
        chain.revoke(H1)


@pytest.mark.parametrize("bad", ["", "abc", "0x12", "0x" + "zz" * 32])
def test_bad_fingerprints_rejected(chain, bad):
    with pytest.raises(ChainError):
        chain.lookup(bad)


def test_evm_blocks_wallets_that_are_not_operators(evm_chain):
    """A stranger's wallet must not be able to write to the registry."""
    from web3 import Web3

    stranger = Account.create()
    w3 = evm_chain.w3
    w3.eth.send_transaction({"from": w3.eth.accounts[0], "to": stranger.address, "value": w3.to_wei(1, "ether")})
    outsider = EvmChain(w3=w3, contract_address=evm_chain.contract.address, private_key=stranger.key.hex())
    with pytest.raises(ChainError):
        outsider.anchor(H1, REF)
    assert evm_chain.lookup(H1).exists is False


def test_evm_status_reports_wallet_and_operator(evm_chain):
    status = evm_chain.status()
    assert status["connected"] and status["is_operator"] and status["balance"] > 0


def test_http_chain_tolerates_poa_block_headers():
    """Polygon Amoy blocks carry long extraData that web3.py rejects unless this middleware is installed."""
    chain = EvmChain(rpc_url="http://127.0.0.1:9", contract_address="0x" + "11" * 20, private_key="0x" + "22" * 32)
    from web3.middleware import ExtraDataToPOAMiddleware

    assert ExtraDataToPOAMiddleware in chain.w3.middleware_onion
