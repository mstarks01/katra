# 145. An audit record is a chained row and a JSON log line

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2415](https://github.com/mstarks01/katra/issues/2415), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)
- **Relates to**: [ADR 0139](0139-a-web-app-session-is-a-server-side-record.md),
  [ADR 0141](0141-the-public-origin-decides-the-network-posture.md),
  [ADR 0143](0143-an-accounts-work-outlives-each-administrative-change.md),
  [ADR 0144](0144-a-change-of-identity-provider-links-each-account-and-moves-no-work.md)

## Context

The service targets ASVS 5.0 level 2. Chapter V16 asks that each authentication
operation, each refused authorization and each attempt to bypass a control goes
to a log. It asks that nobody can change a log, and that a copy goes to a
separate system, so that a breach of the service does not compromise every copy.
An administrator of a plain `docker run` install often has no separate log
system and still needs to see the records in the web app. An administrator can
read and change every **Account**'s work, so the records must also show what
each administrator did.

## Decision

**Each Audit Record goes to two places.** The service writes a row in the
`audit_records` table of the job store database. After the commit, it writes
the same record as one JSON line to the log stream, which an operator can send
to a separate system. Every other log line of the service is a JSON line too.

**An audit line is an OCSF 1.10.0 event, and every other line has a fixed
shape.** An audit record or a security event becomes an event of the matching
OCSF class, with the Date/Time profile, and `time_dt` comes first so that a
log processor finds the time with no setup. Every other line carries `time`
(RFC 3339, UTC), `severity`, `message`, `logger` and `request_id`, which Cloud
Logging and Splunk read with no setup. The row holds the service's own fields,
and no log format decides them. A table of encoders, keyed by format name,
turns a row into a line, and it has one row, `ocsf`. Another format, such as
CEF, is one more row in that table.

**Only two writers touch the table.** The writer adds rows, and the retention
sweep deletes them. A test fails on any other `UPDATE` or `DELETE` of the
table, and a database trigger refuses each `UPDATE`. Each row holds the SHA-256
of the row before it, calculated over the row's own fields and never over an
encoded line. The sweep checks the full chain, and an administrator can
start a check from the Audit page. A break writes a security log line and a
row, and it shows a banner to each administrator. The service keeps running.

**No row, no action.** A change and its row share one transaction. For an
event that changes nothing else, such as a login or a read, the service writes
the row first and refuses the action when the write fails.

**A row stays for `KATRA_AUDIT_RETENTION_DAYS`, 365 days by default.** No other
retention setting, no job expiry and no account delete removes a row. The sweep
deletes no row while any account has a **Legal Hold**. When it deletes rows, it
writes a row that holds the hash of the last deleted row, and the chain check
starts from that row.

**A row names the person as the person was at the event.** It holds the account
ID, a copy of the account's name and email, the client address and the request
ID. A refused login with no account holds the issuer and `sub`. A settings
change holds the old and new value of each key that holds no secret, and only
`set`, `replaced` or `removed` for a secret key. No row holds a token, a cookie
value, a code, an Access Key or a secret value.

**The table holds the events that an administrator acts on.** A refusal writes
a row once the service knows the caller or the identity. A login path writes one
summary row for each rate-limit window that refuses an address. A refusal
before the service knows the caller, an unexpected error and a failed security
control go only to the log stream. Each request that returns another account's
data writes a row, and so does each request to the Audit page.

**Only an administrator reads the records**, through the permission
`audit.read`. The Audit page exports the filtered rows as JSON Lines through
the same encoder as the log stream, with the chain hashes.

## Considered options

- **The log stream only.** Rejected: the web app cannot show the records, and
  an install with no log system keeps them only as long as Docker keeps its
  logs.
- **The table only.** Rejected: an attacker who controls the database can
  change every copy.
- **A hash chain with a key.** Rejected: it adds a secret that each install
  must keep, and the log stream copy already protects the records from an
  attacker who controls the database.
- **IDs only, with the name resolved on the page.** Rejected: after an account
  delete, no record names the person.
- **One row for every refusal.** Rejected: a caller with no login can grow the
  table without a limit, and a size cap lets a flood push out older rows.
- **A best-effort write.** Rejected: an administrator could read or change work
  with no record of it.
- **Splunk CIM field names.** Rejected: Splunk needs no map, but every other
  SIEM needs a custom parser. OCSF reaches Splunk's CIM through the
  Splunk-supported OCSF-CIM add-on.
- **OpenTelemetry semantic conventions for every line.** Rejected: they have no
  security event classes, so no SIEM maps an audit record to its security
  model without a custom parser.
- **CEF over syslog.** Not built now: it is a text line, Splunk parses its
  header only through a community add-on, and the encoder table can add it
  later.
- **A refusal to start on a chain break.** Rejected: one bad row locks every
  person out, and an administrator repairs the install in the web UI.

## Consequences

The table keeps a person's name and email for up to the retention period after
an account delete, and the chain stops an earlier erasure. The log stream holds
more events than the table, and the log inventory states what each holds. In
PostgreSQL, two transactions that add rows take turns on the chain. A person who
reads the log stream in a terminal sees JSON. Google Security Operations maps
the OCSF classes up to version 1.1.0 for logins, sessions and API actions, so
it does not normalize a role change or an account change. Cloud Logging reads
`time` only as text, so it stamps an audit line with the time it received the
line. The service has no setting to choose a format until the encoder table
has a second row.
