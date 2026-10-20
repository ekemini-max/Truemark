# TrueMark setup guide ($0 from start to finish)

This guide takes you from a fresh download to a live site with real sign-ups, an admin page and fingerprints anchored on a blockchain testnet. Every service used has a free tier and none needs a payment card as far as I know. If a service asks for one, stop and check its current free-plan terms.

Dashboards change their menus often. If a button is not where this guide says, search the dashboard for the name in **bold**.

**How long it takes:** about 45 minutes the first time. Steps 1 to 3 and 7 are enough for a working site with a simulated ledger. Steps 4 to 6 add the real blockchain.

| Step | What you do | Needed for |
|---|---|---|
| 0 | Try it on your computer with no accounts | A first look |
| 1 | Create a Supabase project | Users and records |
| 2 | Create the tables | Users and records |
| 3 | Copy your three Supabase values | Users and records |
| 4 | Make a throwaway wallet and get test tokens | Real blockchain |
| 5 | Get a free RPC address | Real blockchain |
| 6 | Deploy the smart contract | Real blockchain |
| 7 | Create your admin account | Admin page |
| 8 | Put the code on GitHub | Hosting |
| 9 | Publish the site on Render | Public link |
| 10 | Test the live site | Launch |

---

## Step 0. Try it on your computer (no accounts needed)

You need Python 3.11 or newer.

```bash
cd truemark
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Open `.env` and set:

```
ADMIN_EMAILS=admin@truemark.test
DEV_SEED=true
```

Start the site:

```bash
uvicorn app.main:app_factory --factory --reload
```

Open <http://localhost:8000>. Sample accounts are created for you (password for both is `truemark-demo-1`):

| Account | Email |
|---|---|
| Admin | `admin@truemark.test` |
| Approved school | `registrar@greenfield.test` |
| School waiting for approval | `office@harbourview.test` |

Everything is stored in memory in this mode, so data disappears when you stop the server. The ledger is **simulated** and every page says so.

Run the tests any time with `python -m pytest`.

---

## Step 1. Create a Supabase project

1. Go to <https://supabase.com> and choose **Start your project**. Sign in with your GitHub account.
2. Create an **organization** if asked. Choose the **Free** plan.
3. Click **New project** and fill in:
   - **Name:** `truemark`
   - **Database password:** click **Generate a password** and save it in a password manager. TrueMark does not use this password directly, but you need it if you ever connect with other tools.
   - **Region:** pick the closest one to your users (South Africa or a European region is usually closest to Nigeria).
4. Click **Create new project** and wait a couple of minutes until the dashboard finishes loading.

Free-plan limits to know about: the free database is small (about 500 MB, which is plenty for a prototype), and a free project **pauses after about a week without activity**. If it pauses, open the dashboard and click **Restore project**. Open the site once a few days before any demo.

---

## Step 2. Create the tables

1. In the left menu of your project, open **SQL Editor**.
2. Click **New query**.
3. Open the file `supabase/schema.sql` from this repository, copy **all** of it, and paste it into the editor.
4. Click **Run**. You should see "Success. No rows returned."
5. Open **Table Editor**. You should see four tables: `profiles`, `records`, `audit_log` and `mock_ledger`.

This file also switches on **row level security** and removes access for public roles. That matters because Supabase publishes a web API for your tables. With this setup the public key can read and write nothing. Only your TrueMark server, which holds the secret key, can touch the data.

---

## Step 3. Copy your three Supabase values

You need three values. In the dashboard, open **Project Settings** (gear icon) and look under **API Keys** (or **Data API**). The **Connect** button at the top of the project page also shows them.

| Value | Where it is | Looks like | Goes in |
|---|---|---|---|
| **Project URL** | Project Settings, API / Data API | `https://abcdefgh.supabase.co` | `SUPABASE_URL` |
| **Publishable key** | API Keys | `sb_publishable_...` | `SUPABASE_PUBLISHABLE_KEY` |
| **Secret key** | API Keys, click **Reveal** | `sb_secret_...` | `SUPABASE_SECRET_KEY` |

If your project only shows the older **anon** and **service_role** keys (look for a "Legacy API keys" tab), use **anon** as the publishable key and **service_role** as the secret key. TrueMark accepts both kinds.

Put them in your `.env` file:

```
SUPABASE_URL=https://abcdefgh.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
SUPABASE_SECRET_KEY=sb_secret_...
```

> **The secret key is a master key.** Anyone who has it can read and change all your data. Keep it only in `.env` (which git ignores) and in Render's Environment tab. Never paste it in a chat, a screenshot, a front-end file or a GitHub issue. If it leaks, open API Keys in Supabase and create a new one, then delete the old one.

Now set your own email as the admin, and check the connection:

```
ADMIN_EMAILS=you@example.com
DEV_SEED=false
```

```bash
python scripts/check_setup.py
```

Every Supabase line should say `OK`. If one says `FAIL`, the message tells you what to fix.

### Why TrueMark does not send sign-up emails

Supabase's built-in email service only delivers to members of your own Supabase team and is limited to about 2 emails per hour. Public sign-ups would break on day one. So TrueMark creates accounts directly (already confirmed) and relies on a stronger control: **every new school waits for an admin to approve it** before it can issue anything. If you later want email confirmation and password reset emails, connect a free custom SMTP provider in Supabase under **Authentication, SMTP settings**.

---

## Step 4. Make a throwaway wallet and get test tokens

*Skip steps 4 to 6 if you want to start with the simulated ledger. You can add the blockchain later, but read the warning at the end of step 6 first.*

The TrueMark server needs a wallet to pay the tiny network fee for each anchor. On a testnet that fee is paid in free test tokens.

1. Create a wallet:

   ```bash
   python scripts/new_wallet.py
   ```

2. Copy the **private key** into `.env` as `ISSUER_PRIVATE_KEY=...`. Keep the **address** (it starts with `0x`) for the faucet.

   > Use this wallet for TrueMark only. Never put real money in it and never reuse a wallet from MetaMask or an exchange.

3. Choose a network. Both work with TrueMark. Pick one:

   | | Polygon Amoy | Sepolia |
   |---|---|---|
   | `CHAIN_NAME` | `Polygon Amoy testnet` | `Sepolia testnet` |
   | `CHAIN_ID` | `80002` | `11155111` |
   | `EXPLORER_TX_URL` | `https://amoy.polygonscan.com/tx/` | `https://sepolia.etherscan.io/tx/` |
   | `EXPLORER_ADDRESS_URL` | `https://amoy.polygonscan.com/address/` | `https://sepolia.etherscan.io/address/` |

4. Request test tokens for your wallet address from a faucet. **Faucet rules change often and some need a small balance on the real network, which would break a $0 budget.** For example, Alchemy's Polygon Amoy faucet requires a small real-ETH balance and past activity on Ethereum mainnet, so skip it. I could not test faucets from my environment, so work through these and stop at the first that gives you tokens:
   - The official Polygon faucet (search "Polygon faucet" for Amoy tokens).
   - A QuickNode or other multi-chain faucet that lists Polygon Amoy or Sepolia.
   - For Sepolia: Google Cloud's Web3 faucet, or a browser-mining ("PoW") faucet that needs no account or balance.

   Wait for the tokens to arrive, then check the wallet address on the network's explorer (`amoy.polygonscan.com` or `sepolia.etherscan.io`).

How much do you need? A fraction of one token covers the contract deployment and dozens of records, because each anchor costs a tiny network fee. Claim a few days early, since faucets limit claims to roughly one per day per address.

**If no faucet works for you:** stay on `CHAIN_MODE=mock` and the simulated ledger. The site works fully and labels itself honestly. Try faucets again later.

---

## Step 5. Get a free RPC address

An RPC address is how the server talks to the blockchain. Public ones are free:

| Network | Public RPC to try |
|---|---|
| Polygon Amoy | `https://rpc-amoy.polygon.technology` |
| Sepolia | `https://ethereum-sepolia-rpc.publicnode.com` |

Put it in `.env`: `RPC_URL=...`

Public RPCs are sometimes slow or rate-limited. For something steadier, create a free account at Alchemy, Infura or QuickNode, create an app for your network, and copy its **HTTPS** URL instead. That URL contains a secret, so treat it like a password.

---

## Step 6. Deploy the smart contract

```bash
python scripts/deploy_contract.py
```

The script checks your network and balance, deploys the contract, and prints something like:

```
Deployed.
  CONTRACT_ADDRESS=0x1234...abcd
  Contract: https://amoy.polygonscan.com/address/0x1234...abcd
```

1. Put the `CONTRACT_ADDRESS` line in `.env`.
2. Set `CHAIN_MODE=evm`.
3. Run `python scripts/check_setup.py` again. The ledger lines should all say `OK`.

The wallet that deploys the contract becomes its owner and its only approved writer, so nobody else can add or revoke fingerprints.

> **Warning: decide the ledger before you issue real demo records.** Records issued while `CHAIN_MODE=mock` are not on any blockchain. If you switch to `evm` afterwards, those records will show as "altered" because their fingerprints are missing from the contract. Issue your demo records after the final switch, or re-issue them.

---

## Step 7. Create your admin account

Admin emails are blocked from the public sign-up page, so nobody can register your address before you do. You create the account with a script instead:

```bash
python scripts/create_admin.py you@example.com
```

It asks for a password twice (nothing is shown as you type). Then:

```bash
uvicorn app.main:app_factory --factory --reload
```

Open <http://localhost:8000/login>, sign in, and you will see **Admin** in the menu. From there you can:

- **Overview:** approve or reject new schools, see system health (database, ledger connection, wallet balance, whether the wallet may write) and recent activity.
- **Schools and users:** approve, suspend or restore schools, and promote another person to admin.
- **All records:** search every record from every school and open any of them (admins can revoke too).
- **Audit log:** sign-ups, approvals, issues, anchors and revocations, with who did them.

To test the school side, open a private window, go to `/signup`, register a school, then approve it from the admin page.

---

## Step 8. Put the code on GitHub

1. Go to <https://github.com/new>, sign in as `ekeminiokono304`, name the repository `truemark`, leave it empty (no README, no .gitignore) and click **Create repository**. Public or private both work.
2. In the project folder, run:

   ```bash
   git remote add origin https://github.com/ekeminiokono304/truemark.git
   git branch -M main
   git push -u origin main
   ```

   If Git asks you to sign in, use the browser prompt, or run `gh auth login` first if you have the GitHub CLI.

3. Open the **Actions** tab on GitHub. A `tests` run starts and should turn green.

Your `.env` file is listed in `.gitignore`, so your keys are not uploaded. Check with `git status` before every push; `.env` must never appear.

---

## Step 9. Publish the site on Render

1. Go to <https://render.com> and sign up with GitHub.
2. Click **New**, then **Blueprint**, and select your `truemark` repository. Render reads `render.yaml` and proposes a free web service called `truemark`.
3. Render asks for the variables marked as secret. Enter the same values as in your `.env`:

   | Variable | Value |
   |---|---|
   | `ADMIN_EMAILS` | your admin email |
   | `SUPABASE_URL` | from step 3 |
   | `SUPABASE_PUBLISHABLE_KEY` | from step 3 |
   | `SUPABASE_SECRET_KEY` | from step 3 |
   | `RPC_URL` | from step 5 |
   | `CONTRACT_ADDRESS` | from step 6 |
   | `ISSUER_PRIVATE_KEY` | from step 4 |
   | `BASE_URL` | leave a placeholder for now |

   To use the simulated ledger instead, set `CHAIN_MODE` to `mock` and leave the three blockchain values empty. To use Sepolia, change `CHAIN_NAME`, `CHAIN_ID`, `EXPLORER_TX_URL` and `EXPLORER_ADDRESS_URL` to the Sepolia values from step 4.
4. Click **Apply** and wait for the first deploy to finish. Render shows your address, for example `https://truemark-abcd.onrender.com`.
5. Open the service's **Environment** tab, set `BASE_URL` to that exact address (no trailing slash), and save. Render redeploys. **This matters:** `BASE_URL` is what gets printed inside every QR code.
6. Open `https://your-address/healthz`. It should show `"status":"ok"`.

Free Render services **go to sleep after a period of inactivity**, and the first visit afterwards can take up to a minute to wake the site. Open it a few minutes before any demo. Render's free-plan terms can change, so check them on their pricing page.

---

## Step 10. Test the live site

Work through this list once, on your phone as well as your computer:

1. Sign in as admin at `/login`. Open the Admin overview and confirm there are no red setup warnings and the ledger shows **Connected** with a wallet balance.
2. In a private window, register a test school at `/signup`.
3. As admin, approve it under **Schools and users**.
4. As the school, click **Issue a record**. After a few seconds you land on the record page with a QR code and a transaction link.
5. Click the transaction link. The explorer shows your contract call.
6. Scan the QR code with your phone. The page says **Valid, unaltered**.
7. On the verify page, use **Check the copy you were given**, change the grade, and press **Check this copy**. The page says **Invalid, altered** and lists what changed. This is your investor demo.
8. Revoke the record and refresh the public page. It now says **Revoked**.
9. Open **Audit log** as admin and confirm steps 2 to 8 are listed.

---

## Troubleshooting

| What you see | What it means and what to do |
|---|---|
| `check_setup` says "Tables exist ... FAIL" | The schema was not run. Do step 2. |
| `check_setup` says the publishable or secret key is rejected | A value is mistyped, or it is for another project. Copy it again with no spaces. |
| Everything is slow or errors on a Supabase call | The free project may be paused. Open the Supabase dashboard and click **Restore project**. |
| "The issuer wallet is out of test tokens" | Get more from a faucet (step 4). The Admin overview shows the balance. |
| "The issuer wallet is not an approved operator" | The contract was deployed by a different wallet. Deploy again from the wallet in `ISSUER_PRIVATE_KEY` (step 6) and update `CONTRACT_ADDRESS`. |
| A record shows "Anchoring failed" | Open the record and click **Try anchoring again**. The reason is shown above the button. |
| Old demo records show "altered" after switching to `evm` | They were issued on the simulated ledger. Re-issue them (see the warning in step 6). |
| The QR code opens `localhost` | `BASE_URL` is wrong. Fix it and redeploy. Existing printed QR codes keep the old address, so re-print. |
| The site takes a minute to open | A free Render service was asleep. Wait, then reload. |
| You forgot the admin password | In Supabase open **Authentication, Users**, delete that user, then run `scripts/create_admin.py` again. |
| `/signup` says an email "is reserved" | That email is in `ADMIN_EMAILS`. Use step 7 for admin accounts. |
| Sign-in works online but loops back to the login page on your computer | `BASE_URL` starts with `https://`, which marks cookies as secure, and your local site runs on `http://`. In your local `.env` use `BASE_URL=http://localhost:8000`. |

---

## Costs and limits

- **Supabase free plan:** $0. Small database, project pauses after about a week without activity.
- **Render free plan:** $0. The site sleeps when idle.
- **Testnet blockchain:** $0. Test tokens have no value.
- **GitHub:** $0.
- **A custom domain** is optional, around $10 a year, and not needed for a prototype.

Moving to a real network later would cost real money per anchor. The standard fix is to group many records into one fingerprint (a Merkle tree) on a low-fee network. That is a later decision and not part of this prototype.
