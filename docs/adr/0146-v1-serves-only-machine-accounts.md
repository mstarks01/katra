# 146. `/v1` serves only machine Accounts

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2418](https://github.com/mstarks01/katra/issues/2418), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)
- **Relates to**: [ADR 0064](0064-an-owner-id-is-a-random-surrogate-for-a-principal.md),
  [ADR 0137](0137-an-identity-source-admits-people-by-invitation-or-by-group.md),
  [ADR 0139](0139-a-web-app-session-is-a-server-side-record.md),
  [ADR 0144](0144-a-change-of-identity-provider-links-each-account-and-moves-no-work.md),
  [ADR 0145](0145-an-audit-record-is-a-chained-row-and-a-json-log-line.md)

## Context

`/v1` takes a bearer token from one issuer that environment variables name, and
it creates a **Principal** at the first job that a new token submits. The web app
now admits people through the **Identity Source** records, with Invitations, group
mappings and a guard that keeps an administrator who can log in. A web session
has an idle end, a recent-login check and an optional MFA rule. A bearer token
has none of these, and it often sits in a script or a CI secret. An install
with only the **Access Key** source has no OIDC provider that can issue a token.
The maintainer wants only an administrator to set up the work that a program
starts.

## Decision

**`/v1` serves only a Machine Account.** An administrator creates a **Machine
Account** on the account administration page. It always has the `member` role,
and it has no web login, no session and no Invitation. A token whose Account is
a person's Account gets a 403 that tells the person to ask an administrator.
`/v1` never creates an Account. A valid token with no Account gets a 403, and
the service stores nothing about it.

**`/v1` trusts the identity source records.** An OIDC source can have an API
audience, separate from its client ID, so a web ID token does not work as a
`/v1` token. The environment variables for one `/v1` issuer go. A token resolves
to a Principal by the source and the `sub` claim, as a web login does.

**A Machine Account has two kinds of credential, and an administrator issues
each one.** The first is one OIDC Principal. The administrator makes a **Link
Code**, and the client presents it once with its token to
`POST /v1/account/link`, which is the one `/v1` route that a token with no
Account can reach. The second is an **API Key** that the administrator creates
and can revoke. The service shows the key once and stores a digest. A group
mapping on a source does not apply to a Machine Account's token, because a
client-credentials token usually carries no group claim.

**Each `/v1` route checks one `_own` work permission, and `/v1` has no
administrative route.** A Machine Account reads and changes only its own jobs.
A submission with `questions: true` gets a 422, because no person answers the
questions of a program. `GET /healthz` needs no credential, checks no
dependency, and is exempt from the `Host` allowlist of ADR 0141, so that a
platform probe reaches it. The web app gets the same route.

**An accepted request writes a JSON log line, not an audit row.** A Link Code
use, a key create, a key revoke, the first use of each key or Principal, and
each refusal of a known caller write an Audit Record. Each key and each
Principal stores the time of its last use.

## Considered options

- **`/v1` also serves a person's own OIDC token.** Rejected: a person can then
  start work through a program with no administrator, and the person rarely
  needs it, because the web app covers a person's work.
- **An administrator's token holds the `*_any` work permissions on `/v1`.**
  Rejected: a token that leaks from a script then reads every Account's work,
  with no MFA and no idle end.
- **`/v1` keeps its own issuer and its own Principals.** Rejected: an
  administrator could not disable or hold that access from the web app, and a
  second identity path would sit outside the Settings page.
- **`/v1` creates an Account at the first submission.** Rejected: it gives an
  Account to a stranger on an invitation-only source.
- **An administrator types a client's `sub`.** Rejected for the reason in ADR
  0144: a `sub` is often an opaque value, and one wrong value binds the wrong
  client.
- **The Access Key also works on `/v1`.** Rejected: a leak from a CI secret then
  gives a web login with the Account's full role.
- **An audit row for each accepted request.** Rejected: a program can poll a
  job every few seconds, and the log line already records each authentication.

## Consequences

An install with no OIDC provider can serve a program through an API Key. No
person sees a Machine Account's reports in the web app; only `/v1` and an
administrator with `work.read_any` read them. A person who wants to script many
submissions asks an administrator for a Machine Account. ADR 0137 states that a
group mapping applies only to a person's login.
