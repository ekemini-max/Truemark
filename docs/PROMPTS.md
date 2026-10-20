# Prompts to rebuild or extend TrueMark with an AI coding tool

The repository already contains a working build. Use these prompts if you want to regenerate a part, port it to another stack, or hand a piece to another tool. Paste one prompt at a time. Each is written from the real implementation, so the result matches this project.

---

## 1. Backend prompt

```
Build the backend for TrueMark, a tamper-evident academic records system. Budget is $0.

STACK
- Python 3.13, FastAPI, uvicorn, httpx, pydantic-settings, web3.py (v7+), qrcode (SVG output).
- Server-rendered Jinja2 pages (no JSON SPA). All settings come from environment variables.
- Storage adapters with identical methods: MemoryStore (tests/local demo) and SupabaseStore that talks to
  Supabase PostgREST over httpx using the SECRET key (server only). Tables: profiles, records, audit_log, mock_ledger.
- Auth adapters: SupabaseAuth (GoTrue REST) and LocalAuth (in-memory, demo/tests).
  Create accounts through POST /auth/v1/admin/users with email_confirm=true (Supabase's default email
  sender only reaches team members at about 2 emails/hour). Sign in with grant_type=password, refresh with
  grant_type=refresh_token. Session = HttpOnly SameSite=Lax cookies; refresh silently when the access token expires.
- Ledger adapters: MockChain (fingerprints in the mock_ledger table, every page labels it "simulated")
  and EvmChain (web3.py, one signer wallet, a lock around sending so nonces stay ordered, legacy gasPrice x1.2,
  gas estimate x1.3, ExtraDataToPOAMiddleware for Polygon Amoy).

SMART CONTRACT (Solidity ^0.8.24, compiled with solc 0.8.28, evmVersion paris, committed as contracts/build/TrueMarkRegistry.json)
- TrueMarkRegistry: owner, operators mapping, private mapping(bytes32 => Anchor{bytes32 issuerRef; uint64 timestamp; bool revoked}).
- anchor(bytes32 recordHash, bytes32 issuerRef) onlyOperator; revoke(bytes32) onlyOperator;
  check(bytes32) view returns (bool exists, bool revoked, bytes32 issuerRef, uint64 timestamp);
  setOperator, transferOwnership (owner only); version() returns "1".
- Custom errors: NotOwner, NotOperator, ZeroAddress, ZeroHash, AlreadyAnchored, NotAnchored, AlreadyRevoked.
- Events: Anchored, Revoked, OperatorSet, OwnershipTransferred. Never store personal data on chain.

FINGERPRINT
- sha256( salt + "|" + canonical_json ) where canonical_json has sorted keys, no spaces, ensure_ascii=False, over the fields
  record_code, institution, student_name, course, grade, issued_on. Normalise every value first (Unicode NFC, collapse whitespace).
- A random 16-byte hex salt per record, stored in the database, never published.
- issuerRef on chain = sha256("truemark-issuer:" + issuer_id), so the chain never holds an institution name.

DATA RULES
- profiles: id (uuid, = auth user id), email, full_name, institution_name, role (issuer|admin), status (pending|approved|suspended), created_at, approved_at, last_login_at.
- records: id, code unique like TM-2026-K7P4-9QXD (alphabet without I, L, O, 0, 1; random), issuer_id, institution_name (always copied from the issuer's profile, never typed per record),
  student_name, course, grade, issued_on, salt, record_hash, status (pending|active|revoked|failed), tx_hash, block_number, chain_name, anchored_at, revoked_at, revoked_reason, anchor_error.
- audit_log: actor_id, actor_email, action, target, detail. Log sign-up, approve/suspend, role change, issue, anchor, anchor failure, revoke.

BEHAVIOUR
- New sign-ups are status=pending. Only approved schools can issue. ADMIN_EMAILS auto-promotes on sign-in, but admin emails cannot be registered through public sign-up
  (a script creates the first admin).
- Issue: save as pending, compute the fingerprint, anchor it, mark active; if the ledger fails mark failed with a readable reason and allow "try anchoring again".
- Verify(code): recompute the fingerprint from what the database holds NOW, ask the ledger. States: valid, revoked, altered (not on the ledger), pending, unavailable (ledger unreachable, not "invalid"), not_found.
- Check a copy: the visitor submits institution, student, course, grade, date. Recompute with the stored salt, compare to the ledger, and return a diff of changed fields. Whitespace/Unicode form differences must not count.
- Revoke: issuer or admin, reason 3 to 300 characters, only active records.
- Public pages only reveal record details when the state is valid or revoked.

ROUTES
Public: GET / , GET /verify?code= , GET /verify/{code} , POST /verify/{code}/check , GET /api/verify/{code} (JSON, 404 when unknown), GET /qr/{code}.svg , GET /healthz.
Schools: GET/POST /signup, /login, POST /logout, GET /dashboard (search + pagination), GET/POST /issue, GET /records/{id}, GET /records/{id}/certificate, POST /records/{id}/anchor, POST /records/{id}/revoke.
Admin (role=admin only): GET /admin, /admin/users, /admin/records, /admin/audit; POST /admin/users/{id}/status (approved|suspended), POST /admin/users/{id}/role (admin|issuer). Admins cannot change their own access.
Users can only open their own records (404 otherwise); admins can open any.

SECURITY
- CSRF token (cookie + hidden form field) on every state-changing POST. Validate redirect targets (no open redirects).
- Sliding-window rate limits: login (per IP and per email), sign-up, verification, issuing.
- Security headers incl. a strict Content-Security-Policy (script-src 'self', no inline scripts), X-Frame-Options DENY, no-store on signed-in pages.
- Escape all output. Never log secrets. Row level security ON with no policies and no grants to anon/authenticated (see supabase/schema.sql).

DELIVERABLES
- supabase/schema.sql, scripts/new_wallet.py, deploy_contract.py, create_admin.py, check_setup.py, Dockerfile, render.yaml, .env.example.
- Tests (pytest) that run the same end-to-end scenarios against: memory+mock, memory+EVM via web3 EthereumTester running the real compiled contract, and a strict fake of the Supabase REST/Auth APIs.
  Cover: full lifecycle, tamper by editing the database row, tamper by editing the presented copy, permissions, CSRF, rate limits, suspended users, token refresh, XSS escaping.
```

---

## 2. Database setup (Supabase)

Do this once. Full screenshots-free detail is in [SETUP_GUIDE.md](SETUP_GUIDE.md), steps 1 to 3.

1. <https://supabase.com> -> sign in with GitHub -> **New project** (name `truemark`, Free plan, generate and save the database password, pick the nearest region).
2. **SQL Editor** -> **New query** -> paste all of [`supabase/schema.sql`](../supabase/schema.sql) -> **Run**. Check **Table Editor** shows `profiles`, `records`, `audit_log`, `mock_ledger`.
3. **Project Settings** -> **API Keys**: copy the **Project URL**, the **Publishable key** (`sb_publishable_...`) and the **Secret key** (`sb_secret_...`). Older projects show **anon** and **service_role** instead; use anon as publishable and service_role as secret.
4. Put them in `.env` (never in git):

   ```
   SUPABASE_URL=https://xxxx.supabase.co
   SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
   SUPABASE_SECRET_KEY=sb_secret_...
   ADMIN_EMAILS=you@example.com
   ```
5. `python scripts/check_setup.py` should print OK for every Supabase line. Then `python scripts/create_admin.py you@example.com` creates your admin login.

Free projects pause after about a week of inactivity. Use **Restore project** in the dashboard if that happens.

---

## 3. Frontend prompt

```
Build the front end for TrueMark, an academic record verification site, as server-rendered Jinja2 templates with one CSS file and small
progressive-enhancement scripts. No framework and no build step. Everything must work without JavaScript except the landing-page demo.
Strict CSP: all scripts in external files, no inline scripts, fonts self-hosted.

DESIGN DIRECTION: "security paper"
- Subject: certificates and the stamp that says whether they can be trusted. The verdict is the hero, drawn as a rubber-stamp seal.
- Palette: paper green-grey #e9efe7, surface #f7f9f4, certificate #fbfcf8, ink navy #0f1c2b, soft ink #475666, rule #c4cec1.
  Verdict colours are reserved for verdicts only: valid #0b6b4b, altered #b3261e, revoked #8a5a00.
- Type: Young Serif for headings and the certificate, Public Sans for everything else, system monospace for record IDs and fingerprints. Sentence case. No all-caps eyebrow labels.
- Structure: thin ink rules and tables with a heavy top rule instead of boxed cards. One memorable moment per page.
- Motion: only the stamp pressing onto the page when a verdict loads; respect prefers-reduced-motion.
- Accessible by default: visible focus rings, 44px tap targets, labelled inputs, AA contrast, works down to 360px wide, print stylesheet for the certificate (A4 landscape).

PAGES
1. Landing: headline "Real records. Lasting trust.", a record-ID lookup field, and beside it a tilted demo certificate with EDITABLE fields (name, course, grade, date).
   As the visitor edits, compute SHA-256 in the browser (same recipe as the server) and flip the stamp from VALID to INVALID with the original and current fingerprints shown, red when they differ.
   Label it as a demo that is not on a ledger. Below: how it works (issue, anchor, verify), "what the proof says and what it doesn't", who it serves, call to register a school.
2. Verify /verify/{code}: big stamp + plain-language verdict (valid, altered, revoked, not anchored yet, ledger unreachable, not found). Show the record on file, the recomputed fingerprint with a copy button,
   ledger name and a block-explorer link. If the ledger is simulated, show a visible amber notice. Then a form "Check the copy you were given" with a "Fill with the record on file" demo button;
   the result is a green, red or amber panel with a small stamp and a table of changed details (anchored vs your copy).
3. Sign in, Register a school (explain that an admin approves every school), "waiting for approval" and "suspended" pages, friendly error pages.
4. School dashboard: figures strip (issued, active, revoked, need attention), search, table of records with status chips, pagination, empty states that say what to do next.
5. Issue a record form, then a record page: details, fingerprint, transaction link, QR code, share link, "Print certificate", "Try anchoring again" on failure, and a revoke form with a confirm dialog.
6. Printable certificate: guilloche border, student, course, grade, date, QR code and record ID, verdict stamp.
7. Admin: sub-navigation (Overview, Schools and users, All records, Audit log). Overview: setup warnings, figures, approval queue with Approve/Reject,
   system panel (database, ledger connection, wallet balance with a low-balance warning, operator status), recent activity.
   Users: filter by status, approve, suspend, make or remove admin (no actions on your own row). Records: search + status filter. Audit log: paginated table.

COPY RULES
Plain, active, sentence case. Buttons say what happens ("Issue and anchor", "Check this copy"). Errors say what went wrong and how to fix it. Never claim more than the proof shows:
anchoring shows a record is unchanged, not that the school entered true data.
```

---

## 4. If you use Lovable, Bolt, v0 or similar

Those tools build JavaScript front ends. To keep this backend, ask for the front end only and point it at the JSON endpoint:

```
Build a React (Vite) front end for TrueMark that calls GET {API_BASE}/api/verify/{code}.
It returns {code, status: valid|revoked|altered|pending|unavailable|not_found, record?: {institution, student_name, course, grade, issued_on, revoked}, proof?: {fingerprint, ledger, simulated, anchored_at, tx_hash, tx_url}}.
Use the design direction above. Show the verdict stamp, the record, the proof, and a simulated-ledger notice when proof.simulated is true.
```

Sign-in, issuing and admin are server-rendered forms in this build; a separate JavaScript front end would need those JSON endpoints added first.
