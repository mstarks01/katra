# Review sitting — is `21-partner-export-api`'s reference list right?

`evals/BLESSING.md` step 6, over `evals/corpus/21-partner-export-api`.

**A partner export API whose bulk customer files reach anyone who holds the link** — domain `partner data export`.

**What you are checking.** Not whether two write-ups are the same threat — the
identity rule decides that mechanically. This asks the question underneath:
**do these reference sets describe what could actually go wrong with this
system?** If a set misses a whole class of attack, the tool scores full marks
for missing it too, and nothing in the repo would ever say so.

## The one rule

**Read Part 1 and write your own list before you open Part 2.** If you read
the recorded threats first you will find them reasonable, and the sitting
measures nothing. Your list does not have to be good or complete — it only has
to be yours, written first.

Roughly an hour.

---

## Part 1 — the system

### System description (description)

> Partner export API: notes for the threat model, from the platform team.
>
> We run an order platform for about forty merchant brands. Every brand's
> customers and orders are in the order database. Some brands work with
> partners, such as fulfilment houses, that need bulk copies of a brand's
> customers or orders. The export API, the export worker, the export queue and
> the stores below all run in our cloud account.
>
> Partner access
> - A partner's system calls the export API over HTTPS. The export API is on the internet.
> - Each approved partner gets a client ID and a client secret. The partner's
>   system swaps them at the export API's token endpoint for an access token that
>   lasts one hour.
> - The client secret never expires. We cannot rotate a secret without deleting
>   the partner and approving it again.
> - Each partner has scopes: the brands it may export, and whether it may export
>   customers, orders or both. The export API checks the brand scope. Ines thinks
>   it also checks the customers/orders scope, but nobody has confirmed it.
> - The export API checks each client ID and secret against the partner registry
>   and reads the partner's scopes from there. The partner registry keeps client
>   secrets in plain text, so that a partner manager can read a secret back to a
>   partner who lost it.
>
> Export jobs
> - A partner asks for an export of one brand, one record type and a date range.
>   The export API puts an export job on the export queue and returns a job ID.
>   Job IDs count up from 1.
> - The partner then asks for the job's status by its job ID. Nobody wrote down
>   whether the export API checks that the job belongs to the partner who asks.
> - Nobody set a limit on how many exports a partner can ask for, or on how long
>   the date range can be.
> - The export worker takes jobs off the export queue one at a time. It reads
>   the rows from the order database with one database account that can read every
>   brand's tables. It does not check the job's brand against the partner's scopes
>   again.
> - The job carries the brand, the record type, the date range and the partner's
>   callback URL.
> - The worker writes each finished export as a CSV file to the export file store.
>   An export holds customer names, email addresses, postal addresses and order
>   history. Nobody deletes finished files. We do not encrypt the files, and
>   nobody has checked whether the file store does.
>
> Webhooks and downloads
> - When a file is ready, the worker posts a webhook to the partner's callback
>   URL, and waits for that call to finish before it takes the next job.
> - Partners set their own callback URL through the export API. The worker does
>   not check where a callback URL points. Callback URLs can start with http://
>   as well as https://.
> - Each webhook is signed with a secret we share with that partner.
> - The webhook carries a signed download link that works for seven days. Anyone
>   who holds the link can download the file straight from the export file store;
>   the download asks for no token.
>
> Admin console
> - Our partner managers approve partners in the admin console. They create the
>   client ID and secret and set the partner's scopes.
> - The admin console runs in our cloud account and is reachable only over the
>   office VPN. Partner managers sign in with the company single sign-on, which
>   asks for a second factor.
> - One partner manager can approve a partner and widen its scopes alone.
>
> Audit log
> - The audit log is a table in the partner registry. The export API writes a
>   row for each token it issues and each job it creates. The admin console
>   writes a row for each approval.
> - Scope changes are not written to the audit log. Downloads are not recorded
>   anywhere.
> - The admin console can edit and delete any row in the partner registry,
>   including the audit table.
>
> Not recorded
> - Nobody has written down how the export API, the worker and the admin console
>   connect to the queue, the registry and the stores, or whether those
>   connections are encrypted. How the order database and the partner registry
>   are protected at rest is not recorded.

### What the model says is in it

Not part of the question, but the records cite these names, so you need them.

**External entities**

| id | kind | zone |
|---|---|---|
| entity:partner-system | external-system | boundary:internet |
| entity:partner-manager | human | boundary:office-vpn |

**Processes**

| id | exposure | interface | zone | technology |
|---|---|---|---|---|
| process:export-api | internet-facing | web | boundary:cloud-account | HTTPS API with a token endpoint |
| process:export-worker | unknown | non-web | boundary:cloud-account | unknown |
| process:admin-console | internal | unknown | boundary:cloud-account | unknown |

**Data stores**

| id | zone | at rest | classification |
|---|---|---|---|
| store:partner-registry | boundary:cloud-account | unknown | unknown |
| store:export-queue | boundary:cloud-account | unknown | unknown |
| store:order-database | boundary:cloud-account | unknown | unknown |
| store:export-file-store | boundary:cloud-account | unknown; the files are not encrypted by the platform team, and nobody has checked whether the file store encrypts them | unknown |

**Data flows**

| id | source | destination | protocol | authentication | in transit |
|---|---|---|---|---|---|
| flow:entity:partner-system>process:export-api>request-exports | entity:partner-system | process:export-api | HTTPS | client secret never expires and we cannot rotate it | HTTPS |
| flow:entity:partner-system>store:export-file-store>download-export | entity:partner-system | store:export-file-store | unknown | signed link | unknown |
| flow:process:export-api>store:partner-registry>check-partners | process:export-api | store:partner-registry | unknown | unknown | unknown |
| flow:process:export-api>store:export-queue>queue-export-job | process:export-api | store:export-queue | unknown | unknown | unknown |
| flow:process:export-worker>store:export-queue>take-export-jobs | process:export-worker | store:export-queue | unknown | unknown | unknown |
| flow:process:export-worker>store:order-database>read-brand-rows | process:export-worker | store:order-database | unknown | account for every brand | unknown |
| flow:process:export-worker>store:export-file-store>write-export-file | process:export-worker | store:export-file-store | unknown | unknown | unknown |
| flow:process:export-worker>entity:partner-system>send-webhook | process:export-worker | entity:partner-system | HTTP or HTTPS, as the partner's callback URL says | signed with a secret | unknown; callback URLs can start with http:// as well as https:// |
| flow:entity:partner-manager>process:admin-console>use-admin-console | entity:partner-manager | process:admin-console | unknown | single sign-on with a second factor | unknown |
| flow:process:admin-console>store:partner-registry>manage-partners | process:admin-console | store:partner-registry | unknown | unknown | unknown |

**Trust boundaries**

| id | kind |
|---|---|
| boundary:internet | network |
| boundary:cloud-account | network |
| boundary:office-vpn | network |

**Recorded notes** — hedges, probed gaps and source disagreements live here, so read them before the sets.

- `process:export-api` — Nobody has confirmed whether it checks the customers/orders scope, and nobody wrote down whether it checks that a job belongs to the partner who asks for its status. Job IDs count up from 1. Nobody set a limit on how many exports a partner can ask for, or on how long the date range can be.
- `store:partner-registry` — The source states how the partner registry is protected at rest is not recorded. The audit log is a table in it; the admin console can edit and delete any row, the audit table included.
- `store:order-database` — The source states how the order database is protected at rest is not recorded.
- `flow:entity:partner-system>store:export-file-store>download-export` — Downloads are not recorded anywhere.
- `flow:process:export-api>store:partner-registry>check-partners` — The source states nobody has written down how the export API connects to the partner registry, or whether the connection is encrypted.
- `flow:process:export-api>store:export-queue>queue-export-job` — The source states nobody has written down how the export API connects to the export queue, or whether the connection is encrypted.
- `flow:process:export-worker>store:export-queue>take-export-jobs` — The source states nobody has written down how the worker connects to the export queue, or whether the connection is encrypted.
- `flow:process:export-worker>store:order-database>read-brand-rows` — The source states nobody has written down how the worker connects to the order database, or whether the connection is encrypted.
- `flow:process:export-worker>store:export-file-store>write-export-file` — The source states nobody has written down how the worker connects to the export file store, or whether the connection is encrypted.
- `flow:process:export-worker>entity:partner-system>send-webhook` — The worker does not check where a callback URL points before it posts to it.
- `flow:entity:partner-manager>process:admin-console>use-admin-console` — The console is reachable only over the office VPN; the source does not say what the VPN or the console connection encrypts.
- `flow:process:admin-console>store:partner-registry>manage-partners` — Scope changes are not written to the audit log. The source states nobody has written down how the admin console connects to the partner registry, or whether the connection is encrypted.

**Assumptions**

- `entity:partner-system` — Partner systems are placed on the internet because the schema requires a zone. (basis: They call the export API, which is on the internet, and receive webhooks at callback URLs; the source places them nowhere.)
- `entity:partner-manager` — Partner managers are placed on the office VPN because the schema requires a zone. (basis: The admin console is reachable only over the office VPN; the source does not say where partner managers work.)
- `process:export-api` — The export API's interface is web. (basis: Partners call it over HTTPS and it has a token endpoint; the source does not name its interface otherwise.)
- `process:export-worker` — The export worker has no web interface. (basis: It takes jobs off a queue and only makes outbound calls; the source names no interface it serves.)

### Your list

Write what could go wrong. Anything: an attack, a missing control, a question
the text does not answer. Bullet points, in any order, no need to sort by
category.

```
-
-
-
```

---

## Part 2 — the 18 recorded ASVS records

The narrower question, per record: **does this requirement apply to this system, and does the input show it satisfied?** An ASVS claim rules applicability and never a pass.


### encoding-and-sanitization

**A1.** `V1.3.6` — The worker posts to whatever callback URL a partner sets, and checks nothing about where it points.

- `process:export-worker`, `flow:process:export-worker>entity:partner-system>send-webhook`
- Stated outright, and the partner sets the URL itself.

> mark:


### configuration

**A2.** `V13.2.4` — Nothing limits which outside addresses the worker may send webhooks to.

- `process:export-worker`, `flow:process:export-worker>entity:partner-system>send-webhook`
- The same stated fact as V1.3.6, read as a deployment control.

> mark:


### secure-communication

**A3.** `V12.3.1` — Webhooks that carry download links go to http:// callback URLs as well as https:// ones.

- `flow:process:export-worker>entity:partner-system>send-webhook`
- Stated outright: callback URLs can start with http://.

> mark:

**A4.** `V12.3.3` — Nothing states that the connections from the export API, the worker and the admin console to the queue, the registry and the stores are encrypted.

- `flow:process:export-api>store:partner-registry>check-partners`, `flow:process:export-api>store:export-queue>queue-export-job`, `flow:process:export-worker>store:export-queue>take-export-jobs`, `flow:process:export-worker>store:order-database>read-brand-rows`, `flow:process:export-worker>store:export-file-store>write-export-file`, `flow:process:admin-console>store:partner-registry>manage-partners`
- The source says nobody has written it down. The submitter can state it, and the deployed setting also settles it.

> mark:


### configuration

**A5.** `V13.1.1` — The description says nobody has written down how the services connect to the queue, the registry and the stores.

- `flow:process:export-api>store:partner-registry>check-partners`, `flow:process:export-api>store:export-queue>queue-export-job`, `flow:process:export-worker>store:export-queue>take-export-jobs`, `flow:process:export-worker>store:order-database>read-brand-rows`, `flow:process:export-worker>store:export-file-store>write-export-file`, `flow:process:admin-console>store:partner-registry>manage-partners`
- Stated outright as missing documentation.

> mark:

**A6.** `V13.2.1` — Nothing states how the export API, the worker and the admin console authenticate to the queue, the registry, the order database and the file store.

- `flow:process:export-api>store:partner-registry>check-partners`, `flow:process:export-api>store:export-queue>queue-export-job`, `flow:process:export-worker>store:export-queue>take-export-jobs`, `flow:process:export-worker>store:order-database>read-brand-rows`, `flow:process:export-worker>store:export-file-store>write-export-file`, `flow:process:admin-console>store:partner-registry>manage-partners`
- The source says nobody has written it down. It names a database account for the worker's read of the order database, but not how that connection authenticates, and an account that reads every brand's tables can be a shared privileged account.

> mark:

**A7.** `V13.3.2` — Every partner manager can read every partner's client secret back from the registry.

- `store:partner-registry`, `process:admin-console`, `flow:process:admin-console>store:partner-registry>manage-partners`
- Stated outright: the secrets are kept in plain text so a partner manager can read one back to a partner. V11.4.2 is left out because it governs user passwords, and V13.3.1 because it governs the backend secrets the application itself uses. A partner's client secret is neither, so this record holds the stated plain-text storage.

> mark:


### authorization

**A8.** `V8.2.2` — Anyone who holds a signed download link gets the file for seven days with no token, and nothing states that the export API checks that a job belongs to the partner who asks for its status.

- `flow:entity:partner-system>store:export-file-store>download-export`, `store:export-file-store`, `process:export-api`, `flow:entity:partner-system>process:export-api>request-exports`
- The download half is stated outright: the file store serves the file to anyone who holds the link. The job-status half is silent and alone would be needs-code; the stated half settles the record. V14.2.1 is left out: the source does not say where the link carries its signature.

> mark:

**A9.** `V8.2.1` — Only the brand scope is stated as checked; whether a partner limited to orders can export customers is a hedge.

- `process:export-api`, `flow:entity:partner-system>process:export-api>request-exports`
- One person thinks the check exists, and nobody has confirmed it.

> mark:

**A10.** `V8.4.1` — The worker reads every brand's tables with one account and exports the brand a job names without checking it against the partner's scopes.

- `process:export-worker`, `store:export-queue`, `store:order-database`, `flow:process:export-worker>store:order-database>read-brand-rows`
- The export API checks the brand scope when the job is created, so the gap turns on who else can write to the queue, which is a permission grant.

> mark:


### data-protection

**A11.** `V14.2.4` — Exports of customer personal data stay in the file store for ever, with no expiry rule.

- `store:export-file-store`
- Stated outright: nobody deletes finished files.

> mark:


### security-logging-and-error-handling

**A12.** `V16.3.3` — Changes to a partner's scopes are not logged, and downloads of exports are not recorded anywhere.

- `process:admin-console`, `flow:process:admin-console>store:partner-registry>manage-partners`, `flow:entity:partner-system>store:export-file-store>download-export`
- Stated outright for both events.

> mark:

**A13.** `V16.4.2` — The admin console can edit and delete any audit row.

- `store:partner-registry`, `process:admin-console`, `flow:process:admin-console>store:partner-registry>manage-partners`
- Stated outright.

> mark:

**A14.** `V16.4.3` — The audit log is a table in the partner registry that the admin console writes, not a separate system.

- `store:partner-registry`
- Stated outright.

> mark:

**A15.** `V16.3.1` — Issued tokens are logged; nothing states that failed client ID and secret checks are logged.

- `process:export-api`, `flow:process:export-api>store:partner-registry>check-partners`
- The source describes its logging in prose and names a row for each token issued. A fuller description can state whether failed checks are logged, and the code also settles it.

> mark:


### secure-coding-and-architecture

**A16.** `V15.2.2` — Nothing limits how many exports a partner can ask for or how long the date range can be, and one worker takes jobs one at a time.

- `process:export-api`, `process:export-worker`, `store:export-queue`
- Stated outright.

> mark:


### validation-and-business-logic

**A17.** `V2.4.1` — No control stops a partner from calling the export function without limit to pull bulk data.

- `process:export-api`, `flow:entity:partner-system>process:export-api>request-exports`
- The same stated absence as V15.2.2, read as anti-automation against data exfiltration.

> mark:


### oauth-and-oidc

**A18.** `V10.4.11` — One partner manager sets and widens a partner's scopes alone, and nothing states that a partner gets only the scopes it needs.

- `process:admin-console`, `flow:entity:partner-manager>process:admin-console>use-admin-console`
- The source states that one manager acts alone; whether managers keep scopes minimal is a practice to ask the team about.

> mark:

## Part 3 — the 19 recorded STRIDE threats

Only after your own list exists.

For each, mark one of:

- `agree` — a real finding against this system, worth reporting.
- `reject` — overstated, unsupported by the text, or not really a finding here.
- `duplicate` — the same finding as another entry on this list, by number.
- `unsure` — you read it and cannot decide. It is a real answer: say it rather
  than pick one of the other three to get past the entry.

Then, at the end of the last part, note anything on **your** list that is not
on either of them. That is the finding this sitting exists for.


### spoofing

**1.** An attacker who obtains a partner's client secret swaps it for access tokens and exports that partner's brands as the partner, for as long as the partner exists.

- `flow:entity:partner-system>process:export-api>request-exports`, `process:export-api`
- severity: medium/high · verb: `use-credential`
- Stated outright: the secret never expires and cannot be rotated without deleting the partner, and the registry holds it in plain text.

> mark:

**2.** An attacker who takes over a partner manager's single sign-on account approves a partner they run and gives it any brand's data.

- `flow:entity:partner-manager>process:admin-console>use-admin-console`, `process:admin-console`
- severity: low/high · verb: `use-credential`
- A second factor and the office VPN keep the likelihood low; one manager can approve and scope a partner alone, which keeps the impact high.

> mark:


### tampering

**3.** An attacker who can write to the export queue plants a job that names any brand and their own callback URL, and the worker exports that brand and posts the download link to them.

- `flow:process:export-api>store:export-queue>queue-export-job`, `store:export-queue`, `process:export-worker`
- severity: low/high · verb: `plant`
- The worker does not check the job's brand against the partner's scopes again, reads with an account that reaches every brand's tables, and posts to the callback URL the job carries. Who can write to the queue is not recorded, which keeps the likelihood low.

> mark:

**4.** A partner manager edits the audit rows of an approval they made, through the admin console.

- `flow:process:admin-console>store:partner-registry>manage-partners`, `store:partner-registry`
- severity: low/medium · verb: `alter`
- Stated outright: the admin console can edit and delete any row in the partner registry, the audit table included. A deletion of the rows is the same reach with the verb `delete`; this claim holds the edit.

> mark:

**5.** An attacker with write access to the export file store replaces a finished export before the partner downloads it, and the partner loads the changed records into its own systems.

- `flow:process:export-worker>store:export-file-store>write-export-file`, `store:export-file-store`
- severity: low/medium · verb: `alter`
- Who can write to the file store is not recorded, and nothing states that a partner can check a file it downloads.

> mark:


### repudiation

**6.** A partner manager widens a partner's scopes, and nothing records who made the change.

- `process:admin-console`, `flow:process:admin-console>store:partner-registry>manage-partners`
- severity: medium/high · verb: `unattributable`
- Stated outright: scope changes are not written to the audit log, and one partner manager can widen a scope alone.

> mark:

**7.** Someone downloads an export with a leaked link, and nothing records who downloaded it or when.

- `flow:entity:partner-system>store:export-file-store>download-export`, `store:export-file-store`
- severity: medium/medium · verb: `unattributable`
- Stated outright: downloads are not recorded anywhere, because they go straight to the file store.

> mark:

**8.** A partner manager deletes the audit rows of an approval they made, and the record then holds no trace that the approval happened.

- `flow:process:admin-console>store:partner-registry>manage-partners`, `store:partner-registry`
- severity: low/medium · verb: `delete`
- Stated outright: the admin console can delete any row in the partner registry, and the audit log is a table there. The edit of the same rows is the tampering claim with the verb `alter`.

> mark:


### information-disclosure

**9.** Anyone who gets hold of a download link, from a forwarded webhook or a plain-http callback, downloads a brand's customer export with no token.

- `flow:entity:partner-system>store:export-file-store>download-export`, `store:export-file-store`
- severity: medium/high · verb: `read`
- Stated outright: anyone who holds the link can download for seven days, and the download asks for no token. Nobody deletes finished files, so the store keeps every export ever made. A partner's own logs or mail are further places a link can leak; the source names none of them.

> mark:

**10.** A partner manager, or an attacker who reads the partner registry, recovers every partner's client secret in plain text.

- `store:partner-registry`, `process:admin-console`
- severity: medium/high · verb: `recover-credential`
- Stated outright: the registry keeps client secrets in plain text so a partner manager can read one back. The secrets never expire.

> mark:

**11.** An attacker on the network path of a partner's http:// callback URL intercepts the webhook and takes the download link it carries.

- `flow:process:export-worker>entity:partner-system>send-webhook`
- severity: low/high · verb: `intercept`
- Callback URLs can start with http://. The webhook's signature proves who sent it and hides nothing.

> mark:

**12.** A partner asks the export API for the status of other job IDs, which count up from 1, and gets other partners' jobs.

- `flow:entity:partner-system>process:export-api>request-exports`, `process:export-api`
- severity: medium/high · verb: `elicit`
- Conditional: nobody wrote down whether the export API checks that a job belongs to the partner who asks.

> mark:

**13.** An attacker with access to the order database's storage reads every brand's customers and orders.

- `store:order-database`
- severity: low/high · verb: `read`
- The source leaves the order database's protection at rest unrecorded, and every brand sits in it.

> mark:


### denial-of-service

**14.** A partner asks for exports with very long date ranges, and the worker, which takes jobs one at a time, spends hours on them while every other partner's exports wait.

- `process:export-worker`, `flow:process:export-worker>store:order-database>read-brand-rows`
- severity: medium/medium · verb: `exhaust-resources`
- Stated outright: nobody set a limit on how many exports a partner can ask for or on how long the date range can be.

> mark:

**15.** A partner sends export requests without limit and fills the export queue, so other partners' jobs wait behind them.

- `flow:process:export-api>store:export-queue>queue-export-job`, `store:export-queue`
- severity: medium/medium · verb: `flood`
- Stated outright: no limit on how many exports a partner can ask for.

> mark:

**16.** A partner's callback URL answers slowly or never, and the worker, which waits for each webhook call before it takes the next job, stops every other partner's exports.

- `flow:process:export-worker>entity:partner-system>send-webhook`, `process:export-worker`
- severity: medium/medium · verb: `disable`
- Stated outright: the worker waits for the webhook call to finish before it takes the next job, and takes jobs one at a time.

> mark:


### elevation-of-privilege

**17.** A partner sets its callback URL to an address inside our cloud account, and the worker posts to it, so the partner sends requests to internal services that no partner may call.

- `flow:process:export-worker>entity:partner-system>send-webhook`, `process:export-worker`
- severity: medium/high · verb: `escalate`
- Stated outright: partners set their own callback URL, and the worker does not check where it points before it posts to it.

> mark:

**18.** A partner whose scope allows only orders exports a brand's customers.

- `flow:entity:partner-system>process:export-api>request-exports`, `process:export-api`
- severity: medium/high · verb: `abuse-grant`
- Conditional: the export API checks the brand scope; whether it checks the customers/orders scope is a hedge nobody has confirmed.

> mark:

**19.** A partner manager approves a partner and gives it every brand's customers alone, with no second person to review the scope.

- `flow:entity:partner-manager>process:admin-console>use-admin-console`, `process:admin-console`
- severity: low/high · verb: `abuse-grant`
- Stated outright: one partner manager can approve a partner and widen its scopes alone.

> mark:

---

## What was on your list and not on either of theirs

The point of the sitting. One line each, and say which set you expected it in.

```
-
-
```

---

## What to do with the result

**Counts first**, kept apart per framework: how many `agree`, `reject`,
`duplicate` per part, and how many of your own items are missing from either set.

- **Few `reject` marks, nothing important missing** — the sets hold, and the numbers
  measured against them have a standard behind them.
- **A whole class of attack missing** — the serious outcome. Recall is measured
  against these sets, so the tool has been scoring full marks for a gap nobody
  could see. Extend the set, and re-derive what was quoted against it.
- **Several `reject` marks** — the sets overstate, inflating the denominator. Cheaper
  direction, still wrong.

**Then record the sitting.** This document is your reading aid and the
evidence that the method ran; it is not the record. The record is **one JSON
file** under `evals/review/submissions/`, carrying your own list, your marks,
your missing list, your notes and a digest of each file you read:

```json
{
  "envelope": 1,
  "submitted_by": "<the GitHub login opening the PR>",
  "submitted_for": "<who read the case: a login, or the word anonymous>",
  "generated": "<YYYY-MM-DDTHHMMSSZ>",
  "cases": {
    "21-partner-export-api": {
      "own_list": ["<what you wrote before the sets opened>"],
      "marks": {"<finding fingerprint>": "agree | reject | duplicate | unsure"},
      "missing": ["<what the recorded sets do not name>"],
      "notes": "<counts, and anything you would change>",
      "opened_digests": {
      "source.md": "ab06a85e26f3af2be139b9b8d8b4c3bb84c0332ca49d134425b67d220283797f",
      "model.json": "33bc78758a47838af34af50d30bce4c9337c12651e1f5a25d51fe7e71251cd6b",
      "claims/asvs.json": "0442cd2dec7200471f23f657d447e1f096426b70e4ca73526593cbfc91919641",
      "claims/stride.json": "019399cd345279d3ce0d8d4768984a01b5393fb928d43d540e0a876ba1f163dc"
      }
    }
  }
}
```

The app (`uv run python webapp/sitting.py`) and the standalone page both write
that file for you and open the pull request; a reader with no clone lands on
GitHub's editor with it already filled in. The file is named for its own
digest, so an edited file no longer matches its name.

**Two names, because they answer two questions.** `submitted_by` is the account
that opens the pull request and answers for the sitting; contribution CI binds
it to that account, so it needs no roster line. `submitted_for` is who read the
case: the same login where you read it yourself, another login, or `anonymous`
where the reader takes part on no name of their own.

The digests above are the files as they were when this document was
generated. A submission covers the frameworks whose reference sets it carries
a matching digest for, and it stops covering one the moment that file changes.
CI checks that every finding of every set you read carries a mark, that the
digests match the tree, and that the pull request adds this one file and
nothing else. `uv run python webapp/sitting.py --list` names the cases still
waiting, and derives that list from the merged submissions.
