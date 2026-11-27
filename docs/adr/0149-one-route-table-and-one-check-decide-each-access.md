# 149. One route table and one check decide each access

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2419](https://github.com/mstarks01/katra/issues/2419), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)
- **Relates to**: [ADR 0064](0064-an-owner-id-is-a-random-surrogate-for-a-principal.md),
  [ADR 0139](0139-a-web-app-session-is-a-server-side-record.md),
  [ADR 0141](0141-the-public-origin-decides-the-network-posture.md),
  [ADR 0143](0143-an-accounts-work-outlives-each-administrative-change.md),
  [ADR 0145](0145-an-audit-record-is-a-chained-row-and-a-json-log-line.md),
  [ADR 0146](0146-v1-serves-only-machine-accounts.md),
  [ADR 0148](0148-a-framework-is-open-to-every-account-until-an-administrator-restricts-it.md)

## Context

The web app and `/v1` serve more than one **Account**. A `member` reads and
changes only the work of its own account. An `administrator` can also read and
change the work of every account, and each such access writes an **Audit
Record**. The **Role** table is code, and a test must fail on a route or a
**Permission** with no row. Each owner-keyed store read answers nothing for
another owner's object, so a request for another owner's job reads as a job
that does not exist. A later effort adds a manager role, and the design must
take it as new rows, with no edit of a route or a template.

## Decision

**Three families of work permissions, with only the verbs that a route uses.**
`work` covers jobs, `controls` covers Controls and `files` covers **Owner
File**s. A family takes its verbs from `create`, `read`, `change` and `delete`.
`create` has no scope, because a new object always belongs to the caller's
account. Each other verb has an `_own` form and an `_any` form. A family has no
verb that no route uses, so `files` has no `change` until a route edits a file.
Each administrative permission names its scope, which is `install` today. Each
permission row states whether the action needs a recent login (ADR 0139).

**One check decides each access.** `authorize(caller, family, verb, target)`
is the one entry point. A target is a kind and an ID, and the kind is `job`,
`control`, `file` or `account`. The check reads the target's owner through
the store method `owner_of(kind, id)`, which only the check calls. The check
requires `_own` for an object of the caller's account and `_any` for an object
of another account. An `_any` access writes its Audit Record before the route
reads the object, and the check refuses when that write fails. The check
returns a grant, and a route takes an owner ID only from a grant. A list route
takes an optional `account` parameter, and the check treats that account as
its target.

**A refusal for another account's object reads as "not found".** A caller who
does not hold the `_any` permission gets the same answer as for an object that
does not exist. Only a refusal for an object of the caller's own account is a
403.

**One route table for each app, enforced on the whole app.** Each row is keyed
by method and path, and it names the credential, the permission and the path
parameter that holds the target. One dependency, installed on the whole app,
reads the row of the matched route and calls the check. It refuses a route
that has no row. The `Sec-Fetch-Site` exemption of ADR 0141 reads the
credential column of the same row. A test compares the table with the routes
of both apps in both directions, and it fails on a permission that no row
uses.

**The guard that keeps an administrator runs beside the write.** The check of
the permission comes first. The guard of ADR 0143 then counts the
administrators inside the store transaction that makes the change, after a
write lock, so two parallel changes cannot both pass.

**Pages read the same table.** The module gives the set of permissions that a
caller holds. A page shows a link or a button only when the set holds the
permission of the route that the link reaches. The reader of ADR 0148 that
gives the frameworks an account can run is in the same module.

**Work that an administrator starts stays with its owner.** An answer, an
**Amendment** or a continue by an administrator makes a job of the parent's
owner, and that job counts against the owner's limits. A new job names only
Owner Files, Controls and earlier jobs of the caller's account. A delete by an
administrator logs the cause `administrator`, and an account delete logs
`account-delete`. The code computes the cause from the two owner IDs.

## Considered options

- **One `work` family for jobs, Controls and Owner Files.** Rejected: a later
  role could not read reports without the Owner Files, which can hold call
  transcripts.
- **A delete inside `change`.** Rejected: a Legal Hold refuses a delete and
  allows an edit, so the two need separate verbs.
- **One coarse `.change` permission for each administrative family.**
  Rejected: a manager role could not disable an account without the right to
  move its work, delete it or clear a Legal Hold.
- **A permission dependency on each route.** Rejected: a route without one runs
  until a test finds it, and the policy spreads over many decorators. The
  table denies a route with no row when the app runs.
- **A 403 for each refusal.** Rejected: it tells a member that another
  account's object exists.
- **`get` as the owner read.** Rejected: it loads the whole job record, and it
  gives no owner for a Control or an Owner File.
- **The guard as a check before the route.** Rejected: two administrators who
  disable each other at the same time both pass it.
- **Separate administrative routes for another account's lists.** Rejected:
  each list exists twice, and the two copies can drift apart.
- **The recent-login rule on each route row.** Rejected: a new route for the
  same action could skip it.
- **A role check in each template.** Rejected: the manager role would need an
  edit in each template, and a template can disagree with the table.
- **A job that an administrator starts counts against the administrator's
  limits.** Rejected: each record then needs a second owner ID, and each limit
  reads two accounts.
- **An administrator submits a job with another account's objects.**
  Rejected: the copy in the new job escapes the other account's delete and
  Legal Hold.

## Consequences

The full access policy of each app is one table that a security review reads
in one file. A manager role adds rows in the role table and changes no route
and no template. Each store backend implements `owner_of` for the four kinds.
An administrator's answer can make the owner's count bound delete the owner's
oldest ended job, unless a Legal Hold is set.
