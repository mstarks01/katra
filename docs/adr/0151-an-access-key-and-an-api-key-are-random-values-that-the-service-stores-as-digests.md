# 151. An Access Key and an API Key are random values that the service stores as digests

- **Status**: accepted
- **Date**: 2026-11-28
- **Effort**: [#2424](https://github.com/mstarks01/katra/issues/2424), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)
- **Relates to**: [ADR 0137](0137-an-identity-source-admits-people-by-invitation-or-by-group.md),
  [ADR 0138](0138-the-first-administrator-presents-a-setup-code.md),
  [ADR 0139](0139-a-web-app-session-is-a-server-side-record.md),
  [ADR 0141](0141-the-public-origin-decides-the-network-posture.md),
  [ADR 0143](0143-an-accounts-work-outlives-each-administrative-change.md),
  [ADR 0144](0144-a-change-of-identity-provider-links-each-account-and-moves-no-work.md),
  [ADR 0145](0145-an-audit-record-is-a-chained-row-and-a-json-log-line.md),
  [ADR 0146](0146-v1-serves-only-machine-accounts.md),
  [ADR 0147](0147-a-link-replaces-a-principal-on-the-same-source-and-a-removal-keeps-a-mark.md)

## Context

Katra makes two secrets of its own. An **Access Key** logs a person in to the
web app with no external identity provider, and an **API Key** lets a
**Machine Account** call `/v1` (ADR 0146). In both cases the service is the
provider: no other system checks the person, sets a policy or gives a second
factor. ADR 0147 gives an account one **Principal** for each source, and a key
is not a provider identity, so that rule needs a reading for keys.

## Decision

**One format and one digest serve both kinds of key.** A prefix names the
kind: `katra_ak_` for an Access Key and `katra_api_` for an API Key. The body
is 256 bits from the operating system's secure random source, as 52 lowercase
base32 characters. The service stores the SHA-256 of the full key under a
unique index, and the last 4 characters as a hint, such as `katra_api_…x7qd`.
One table holds both kinds with a `kind` column, one function issues a key and
one function resolves a presented key. `/v1` reads an API Key from
`Authorization: Bearer` and tells it from a JWT by the prefix. The login form
refuses a `katra_api_` key and `/v1` refuses a `katra_ak_` key, each with a
message that names the correct place. An unknown key and a revoked key get the
same refusal. A key goes only in a `POST` body or that header, never in a URL,
a cookie or a log line.

**The Access Key source gives an account one Principal, which holds one key at
a time.** A replacement makes a new key and revokes the old key in one
transaction. It is a change of credential, so it keeps no **Removal Mark**. It
ends each session that the old key started, except the session that makes the
change. A revoke with no new key removes the Principal under the rules of ADR
0147. The source is always invitation only and has no group mapping, so it
never binds an account (ADR 0137).

**A person replaces a key, an administrator revokes one, and a lost key goes
through a Link Code.** A replacement needs a recent login (ADR 0139), which for
this source is the current key entered again. An administrator revokes the key
of any account directly. For a lost key the administrator makes a **Link
Code** (ADR 0144), and the service shows the new key to the person only.
`KATRA_RECOVERY=1` on this source makes a new `administrator` account through
the setup of ADR 0138. The old account keeps its work and comes back through a
Link Code. The Account page marks an account that a recovery made.

**A self-service link to the Access Key source needs a recent login through
the session's own Principal.** The service makes the key and shows it once, so
no second identity exists to prove. A change window to this source asks for a
key at each login through the old source, and the Link Code file of ADR 0144
covers a person who cannot log in.

**Each Machine Account holds at most 2 API Keys, and each API Key expires.**
Two keys let a rotation run with no downtime. The administrator chooses 30,
90 or 365 days at the create, and 90 is the default. The administration page
shows each key that expires in the next 14 days, and `/v1` refuses an expired
key with the reason `key-expired`. An Access Key has no expiry, because ASVS
6.2.10 rejects a forced periodic change of a person's secret.

**The Access Key source does not meet ASVS 6.3.3, and the build spec documents
the deviation.** A key is one factor, and Katra is the provider, so no other
system adds a second factor. The source is off until an administrator turns it
on, and the Settings page states the limit on the source. Its MFA rule, when it
is on, refuses an administrator login by key. The rule is off by default, and
the guard of ADR 0143 refuses to turn it on when no administrator could then
log in.

**A rate limit counts refused attempts for each client address in a sliding
window.** One limiter module holds a table keyed by route. The key login row
allows 10 refused attempts in 10 minutes, and the `/v1` row allows 30. The
address comes from the module of ADR 0141, and an IPv6 address counts by its
`/64`. The limiter keeps the times of the last refused attempts for each
address, and answers `429` with a `Retry-After` until the oldest time leaves
the window. The table lives in memory and holds at most 100,000 addresses,
and a full table drops the oldest address. The summary Audit Record of ADR 0145
records each window that the limit refuses. A slow attack under the limit
shows only in the log lines, and the build spec documents a log query that
finds it.

**The page shows a new key once, in a form that a password manager saves.**
The form has a read-only field with `autocomplete="username"` that holds the
account name, a field with `autocomplete="new-password"` that holds the key,
and a "Copy" button. The login form has the same two fields with
`autocomplete="current-password"`. The service finds the account by the key's
digest alone and ignores the name.

## Considered options

- **A slow hash, such as Argon2.** Rejected: it protects a secret with little
  entropy. Nobody can guess a 256-bit random key offline, and a slow hash
  costs CPU on each `/v1` request.
- **A checksum in the key.** Rejected: a mistyped key already fails the
  lookup, and a checksum is one more format rule for two readers.
- **Many Access Keys for each Principal, such as one for each device.**
  Rejected: more secrets can leak, and the Sessions page already ends the
  session of a lost device.
- **Each key as its own Principal.** Rejected: a replacement then keeps a
  Removal Mark for a value that nobody can present again.
- **A "Replace key" action that shows the new key to the administrator.**
  Rejected: the administrator then holds another person's login secret, and
  an Audit Record cannot show who logged in with it.
- **A recovery page that lists the administrator accounts and replaces one
  key.** Rejected: it shows names and emails to the holder of the Setup Code
  before any login, and it needs a second path for each kind of source.
- **A passkey after the key, or a passkey in place of the key.** Rejected:
  each adds an authentication protocol to Katra's own code, and no
  conformance suite tests it.
- **An open Access Key source.** Rejected: it gives an account to each person
  or program that reaches the login page.
- **An API Key with no expiry.** Rejected: many people and tools read a CI
  secret, and an expiry limits how long a leaked key works.
- **A fixed window for the rate limit.** Rejected: an attacker who sends
  attempts on both sides of a boundary passes two times the limit.
- **A counter in the job store.** Rejected: each refused attempt then costs a
  database write.
- **A check that the person saved the new key.** Rejected: a lost key costs
  one Link Code and loses no work.

## Consequences

An install that turns the Access Key source on does not meet ASVS level 2 for
the accounts that use it, and a stolen key works until somebody revokes it. An
install that needs level 2 uses an OIDC source with MFA. An expired API Key
stops a CI pipeline, and Katra sends no email (ADR 0137), so only an
administrator who opens the page sees the warning before the expiry. A restart
clears the rate limit table. When more than one container serves one origin,
each container keeps its own table.
