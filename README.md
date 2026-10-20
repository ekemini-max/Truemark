# TrueMark

**Real records. Lasting trust.** A tamper-evident academic record system. A school issues a certificate or result, TrueMark anchors a fingerprint of it on a blockchain testnet, and anyone can scan a QR code to check that the record has not been altered.

Built to run for **$0**: Supabase (database and sign-in), a blockchain testnet, and Render's free web hosting.

> Setup, keys and deployment: **[docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md)**

## What it does

| Who | Can |
|---|---|
| **Anyone** (no account) | Open a verification page from a QR code or record ID, see a clear verdict (valid, altered, revoked), and test a printed copy against the original. |
| **Schools** (approved by an admin) | Issue records, get a record ID and QR code, print a certificate, search their records, revoke a record. |
| **Admins** | Approve, suspend and restore schools, see every record, read the audit log, and watch system health (database, ledger, wallet balance). |

## How verification works

1. A school enters a record. TrueMark computes a **fingerprint**: SHA-256 over a random per-record salt plus the record's details (record ID, school, student, course, grade, date) in a fixed format.
2. Only the fingerprint, a pseudonymous school reference and a timestamp are written to the **TrueMarkRegistry** smart contract. Names and grades stay in the database.
3. A public page recomputes the fingerprint from what the database holds now and asks the contract whether it was anchored. If someone edits the database, or presents a certificate with a changed grade or date, the fingerprint no longer matches and the page says so.
4. A school can revoke a record. The contract keeps the revocation and the public page shows it.

The salt stops anyone from guessing grades by hashing every possibility against the public chain.

## What the proof does and does not say

- It shows a record has **not changed since it was issued** and whether it was revoked.
- It does **not** show that the school entered true information. That is why schools must be approved by an admin before they can issue, and why every record carries the approved institution name.
- It does **not** show that the person holding a certificate is the student named on it.
- With `CHAIN_MODE=mock` the ledger is a database table, not a blockchain. Every page says "simulated" when this is the case, so a demo never overstates what it is.

## Quick start (no accounts needed)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env     # then set DEV_SEED=true and ADMIN_EMAILS=admin@truemark.test
uvicorn app.main:app_factory --factory --reload
```

Open <http://localhost:8000>. Demo logins use the password `truemark-demo-1`: `admin@truemark.test` (admin) and `registrar@greenfield.test` (approved school). Data is held in memory and lost on restart.

## Project layout

```
app/                    FastAPI application (server-rendered pages, no build step)
  main.py               App factory, middleware, error pages
  service.py            Business rules: issue, anchor, verify, check a copy, revoke
  hashing.py            The fingerprint recipe (mirrored in static/js/demo.js)
  chain.py              Ledger adapters: simulated (database) and EVM (web3.py)
  store.py              Storage adapters: in-memory and Supabase
  auth.py               Sign-in adapters: Supabase Auth and local (demo/tests)
  routes/               public.py, account.py (schools), admin.py
  templates/, static/   Pages, styles, fonts, scripts
contracts/              TrueMarkRegistry.sol and its compiled build/ artifact
scripts/                new_wallet, deploy_contract, create_admin, check_setup
supabase/schema.sql     Tables and row level security
tests/                  87 tests (pytest): end-to-end flows and unit tests
```

The compiled contract is committed in `contracts/build/`, so you do not need Node or any Solidity tooling. To change the contract, edit the `.sol` file and run `cd contracts && npm install && npm run compile`.

## Configuration

All settings are environment variables; see [`.env.example`](.env.example) for every one with comments. The important ones:

| Variable | Purpose |
|---|---|
| `BASE_URL` | Public address of the site. Printed inside QR codes. |
| `ADMIN_EMAILS` | Emails that become admins when they sign in. |
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` | Database and sign-in. Leave empty for in-memory storage. |
| `CHAIN_MODE` | `mock` (simulated ledger) or `evm` (real testnet). |
| `RPC_URL`, `CONTRACT_ADDRESS`, `ISSUER_PRIVATE_KEY` | Needed when `CHAIN_MODE=evm`. |

## Security notes

- Passwords are handled by Supabase Auth; TrueMark never stores them.
- Tables have row level security with no policies and no public grants: the publishable key can read nothing. Only the server's secret key can.
- Forms use CSRF tokens, cookies are `HttpOnly` and `SameSite=Lax`, responses carry a strict Content-Security-Policy, and sign-in, sign-up, verification and issuing are rate limited (in memory, so per server instance).
- Admin emails cannot be registered through public sign-up; the first admin is created with `scripts/create_admin.py`.
- The server holds one wallet key and signs every transaction. Use a throwaway testnet wallet only.

## Known limits of this prototype

- Public verification pages show the student's name, course and grade to anyone who has the record ID. Record IDs are random (about 40 bits), rate limited, and printed only on the certificate and in its QR code, but treat them like a shareable link. Check the Nigeria Data Protection Act 2023 and your institution's policies before using real student data.
- Sign-up creates pre-confirmed accounts; admin approval is the control, not email verification.
- One anchoring transaction per record. At scale you would batch records into a Merkle tree and anchor only the root.
- The contract and server have not had a professional security audit. Get one before any real pilot.

## Tests

```bash
python -m pytest
```

The end-to-end scenarios (register, approve, issue, verify, tamper, revoke, permissions, CSRF, rate limits) run against three setups: in-memory with the simulated ledger, in-memory with an in-process blockchain running the real contract, and a strict fake of Supabase's REST and Auth APIs.
