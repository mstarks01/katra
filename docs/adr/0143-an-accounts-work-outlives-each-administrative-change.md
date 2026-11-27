# 143. An account's work outlives each administrative change

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2413](https://github.com/mstarks01/katra/issues/2413), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)
- **Relates to**: [ADR 0065](0065-a-job-record-splits-into-rows-and-two-objects.md),
  [ADR 0066](0066-a-deleted-job-leaves-a-usage-row.md),
  [ADR 0137](0137-an-identity-source-admits-people-by-invitation-or-by-group.md),
  [ADR 0138](0138-the-first-administrator-presents-a-setup-code.md),
  [ADR 0139](0139-a-web-app-session-is-a-server-side-record.md),
  [ADR 0142](0142-the-install-limit-queues-a-job-and-the-account-limit-refuses-it.md)

## Context

An administrator disables an **Account**, deletes it, or gives its work to a
colleague when a person leaves. A lawsuit can require that a person's work
stays. Each of these is an administrative change, and none of them may remove
work as a side effect. The work of an account is its jobs, its **Control**s and
its **Owner File**s. Each object key starts with the owner ID (ADR 0065), and
the count bound deletes an account's oldest finished jobs when a new job does
not fit.

## Decision

**A disable stops the person and keeps the work.** It stops the account's
logins and `/v1` tokens and deletes its session rows (ADR 0139). Each running
job finishes. Each queued job fails with the reason `account-disabled` and
settles to zero, as on a restart (ADR 0142). Each record keeps its sources. A
paused job stays paused, and retention applies as to any other account. A
login through any identity source does not re-enable the account. A re-enable
restores the logins only.

**A Legal Hold keeps all of an account's work.** An administrator sets and
clears it, separate from a disable, on an active or a disabled account. While
it is set, retention skips the account's work, and the service refuses each
delete of a job, a Control or an Owner File, an account delete and a move. The
count bound then refuses a new job and deletes no old one.

**An administrator can move all of one account's work to one other account.**
The move copies each object to the key of the new owner ID, then deletes the
old object. Each job keeps its ID, sources, events, answers and report. The
move refuses while a job of the source account runs or is queued, and it
refuses when the receiver would go over its count bound. That refusal states
the Limit Override value that lets the move pass. A moved Control or Owner File
whose name collides gets " (moved)", then " (moved 2)", added to its name.
Each moved item records the earlier owner ID, the move time and the earlier
name, one entry for each move. The Limit Override stays with its account.

**An account delete makes the administrator choose what happens to the work.**
The form selects a move to a named account by default. A delete of the work
needs the job count typed as confirmation, and each deleted job keeps its usage
row (ADR 0066). The delete waits until no job of the account runs or is
queued.

**One guard keeps an administrator who can log in.** It counts the
`administrator` accounts that are enabled and have a Principal on an enabled
identity source. It refuses each disable, delete, role change, Principal
removal, source disable, source removal or mapping change that would bring the
count to zero. ADR 0138's recovery path covers a removal in the directory.

**A removal in the provider needs no new mechanism.** The next login fails, a
back-channel logout ends the sessions, and an open session ends at its idle or
absolute limit. The account and its work stay.

## Considered options

- **A disable lets queued jobs run.** Rejected: an administrator often
  disables an account because somebody else may have it, and the queue would
  continue to spend install tokens.
- **A disable stops retention.** Rejected: it does not stop the owner's own
  deletes and does not cover an active account, so it does not serve a legal
  hold. It also keeps a leaver's work with no end date.
- **No move.** Rejected: the only way to keep a leaver's work is then to keep
  the leaver's account.
- **A move of one job at a time.** Not built: nobody needs it yet.
- **A move that raises the receiver's override by itself.** Rejected: a later
  reader of the override cannot tell why it is high.
- **A move that refuses on a name collision.** Rejected: nobody can rename a
  Control or an Owner File, so the only way forward is a delete.
- **A delete that always deletes the work, or always gives it to the
  administrator.** Rejected: the first removes work as a side effect, and the
  second can push the administrator over the count bound.
- **A periodic refresh with the provider for each session.** Rejected: it
  stores a long-lived provider secret for each session.

## Consequences

An administrator who must stop a person at once disables the account. A person
whose account an administrator deleted can log in again through an open source
and gets a new, empty account, so a disable or the directory keeps a leaver
out. Each lifecycle change has its own permission and writes an audit record.
