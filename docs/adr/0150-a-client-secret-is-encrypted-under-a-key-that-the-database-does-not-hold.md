# 150. A client secret is encrypted under a key that the database does not hold

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2423](https://github.com/mstarks01/katra/issues/2423), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)
- **Relates to**: [ADR 0092](0092-the-settings-directory-and-its-strict-env-file.md),
  [ADR 0137](0137-an-identity-source-admits-people-by-invitation-or-by-group.md),
  [ADR 0138](0138-the-first-administrator-presents-a-setup-code.md),
  [ADR 0140](0140-authlib-runs-the-protocol-steps-and-katra-checks-the-tokens.md),
  [ADR 0145](0145-an-audit-record-is-a-chained-row-and-a-json-log-line.md)

## Context

An **Identity Source** is a database row that an administrator edits in the web
app (ADR 0137), so the client secret of an OIDC source arrives at runtime. The
Settings page keeps a vendor API key as a `0600` file in the settings directory
and puts only the path in `settings.env` (ADR 0092). A file exists in one
container only, and a database backup does not carry it. A provider often
shows a client secret only once, so a lost secret means a new secret at the
provider, and every login through that source fails until an administrator
enters it.

## Decision

**The source row holds the client secret, encrypted with AES-256-GCM under a
key that the database does not hold.** The Deployment Setting
`KATRA_SECRET_KEY_FILE` names a file of 32 random bytes, and the `_FILE` rules
for the mode and the content apply to it. A missing file, a file of the wrong
length or a file with a bad mode stops the start.

**With no setting, the service makes the key itself.** At the first save of a
client secret, it writes 32 bytes from the operating system's secure random
source to `secret.key` in the settings directory, by `create_private`. It logs
one line with the path and tells the operator to back the file up. The key
stays out of the data directory, so a copy of the database alone does not show
a secret. The setup needs no command on the host.

**Each ciphertext starts with a key ID, the first 8 bytes of the SHA-256 of its
key.** The GCM associated data is the source ID and the field name, so a
ciphertext that somebody copies to another row fails the check.

**A key change uses one old key beside the current key.** The operator sets
`KATRA_SECRET_KEY_FILE` to the new key and `KATRA_SECRET_OLD_KEY_FILE` to the
old key, and restarts. At the start, the service re-encrypts each row from the
old key to the new key in one transaction. It writes one audit record with the
count, and logs that the operator can remove the old setting. To replace a
generated key, the operator names `secret.key` as the old key.

**A secret that the service cannot decrypt takes only its source out of use.**
This covers a key ID that names no loaded key and a failed GCM check. The
service starts. The login page shows that source as unavailable and refuses a
login through it before any redirect. The source page says that the secret
cannot be read and asks for it again, and a new save encrypts under the current
key. Each such source gets one error line and one audit record at the start,
and a failed GCM check gets its own event, because it shows a changed row. When
no administrator can log in, the **Login Key** source or `KATRA_RECOVERY=1`
(ADR 0138) is the way back.

**The secret is write only.** The source page shows "set" and the date of the
last change, and never the value. An empty field on an edit keeps the stored
secret. The audit record of a change names the source and the field, and never
holds the value (ADR 0145).

**The source row holds `token_endpoint_auth_method`, an enum of
`client_secret_basic` and `client_secret_post` (ADR 0140).** A `private_key_jwt`
value can join the set when a provider needs it, and its private key then uses
the same encryption, key ID and associated data.

## Considered options

- **A `0600` file for each secret, as for a vendor key.** Rejected: a second
  container that reads the same database finds a source with no secret, and a
  database backup loses the link between the row and its secret.
- **The secret as plain text in the row.** Rejected: a database dump gives an
  attacker a working client.
- **A setup that refuses a client secret until the operator sets a key.**
  Rejected: a plain `docker run` must finish the setup in the web app.
- **A key derived from the Setup Code.** Rejected: a generated Setup Code
  changes at each start.
- **No re-encryption, and an administrator enters each secret again after a
  key change.** Rejected: each key change then needs a new secret at each
  provider and can lock out the administrator.
- **A key change on the Settings page, with a trial and a revert.** Rejected:
  the operator changes the key rarely, and a Deployment Setting pair is less
  code.
- **A refusal to start when a secret cannot be decrypted.** Rejected: it also
  closes the web app that the administrator needs for the repair.
- **A page that can show the secret again after a recent login.** Rejected: a
  stolen administrator session could then read the secret.

## Consequences

On one host with SQLite, the key and the database sit on the same machine, so
the encryption protects only a copy of the database that leaves the host, such
as a backup. A settings directory that is not on a volume loses the generated
key at a restart, together with `settings.env` and the vendor key files, and
each source then asks for its secret again. When more than one container
serves one origin, each container needs the same key, and a re-encryption
needs each container to restart with the new key. An attacker who can write
to the database can take a source out of use, but that attacker can already
delete the row.
