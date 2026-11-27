# 148. A framework is open to every account until an administrator restricts it

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2422](https://github.com/mstarks01/katra/issues/2422), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)
- **Relates to**: [ADR 0143](0143-an-accounts-work-outlives-each-administrative-change.md),
  [ADR 0145](0145-an-audit-record-is-a-chained-row-and-a-json-log-line.md),
  [ADR 0146](0146-v1-serves-only-machine-accounts.md)

## Context

An install can serve several teams, and each team can need a different set of
frameworks. The administrator must choose the frameworks of each team or of
one **Account**, whatever **Identity Source** the account logs in through. A
new framework must reach every account with no step, until an administrator
narrows it. A member does not need to know that other frameworks exist.

## Decision

**A framework is open to every account by default. An administrator can
restrict it to an audience.** A **Framework Restriction** is a record keyed by
the framework name. A framework with no record is open, a new one included.
The audience holds **Team**s and Accounts. An account can run a restricted
framework when the account, or one of its Teams, is in the audience. The
audience is a union: no entry denies. To keep one account from a framework
that its Team can run, an administrator takes the account out of the Team or
names the other accounts one by one.

**A Team is a record in the service.** An administrator creates, renames and
deletes Teams, and adds and removes accounts at any time. An account can be in
more than one Team, and the Teams add up. A **Machine Account** can be in a
Team, so `/v1` uses the same check as the web app.

**A restriction applies to members only.** An administrator can run each
framework that the install carries.

**One reader gives the frameworks that an account can run.** It is the carried
set, narrowed by each restriction whose audience does not hold the account or
one of its Teams. The picker, the refusal text, the submission check, the
check of a run from a paused job and the Controls editor all call it.

**The check runs when a run starts.** A running job finishes. Each stored job,
report and Control stays, and its **Owner** can read, export and delete it. An
answer, a continue or an **Amendment** that starts a run is refused when the
account cannot run one of the parent job's frameworks. A draft save and a
correction run nothing, so they still work. The same check refuses a parent
framework that the install no longer carries.

**A member cannot tell a restricted framework from one that the install does
not carry.** The picker shows only the frameworks that the account can run,
with no note about the others. A submission that names another framework gets
one 422 for both cases, and its message lists only the frameworks that the
account can run. When no framework is open to the account, the web page says so
and offers no submit.

**A Control row keeps its framework.** A new row offers only the units of the
frameworks that the account can run. An old row for a framework that the
account lost stays visible and editable for its Owner. It applies only when a
job runs that framework.

**An empty audience means administrators only.** A Team delete, an account
delete or the removal of the last entry leaves the framework restricted. Only
the action "Remove the restriction" opens it to every account again. Before a
Team delete, the page lists each framework whose audience the delete changes.
A whole-account move (ADR 0143) moves work, not Teams or audience entries.

**A restriction outlives its framework.** A record for a framework that the
install no longer carries stays, and it applies again when the framework comes
back. The record stores the name as a plain string, so a name that the code no
longer spells still loads. A container reads the records and writes none at
startup.

**Two permissions guard the records.** `frameworks.restrict` changes a
restriction and its audience, and `teams.change` changes a Team and its
members. Both have the `install` scope. Each change writes an **Audit Record**
(ADR 0145).

## Considered options

- **A framework list on each role, edited at runtime.** Rejected: it cannot
  give two teams of members different sets.
- **A list on each role, Team and account, with the intersection as the
  result.** Rejected: three records decide one answer, and each list needs its
  own "all" value so that a new framework stays open.
- **Provider groups in the audience, read at each login.** Rejected: Google,
  Apple and personal Microsoft accounts send no groups, and most other
  providers send them only when an administrator configures a claim. A later
  effort can add provider groups, or SCIM, as members of a Team.
- **A restriction that applies to administrators too.** Rejected: an
  administrator can edit any audience, so it controls nothing.
- **A deletion of the record when its framework leaves the install.**
  Rejected: a config edit or an upgrade would open the framework with no
  notice.
- **An empty audience that opens the framework.** Rejected for the same
  reason.
- **A stop of the running job, or a hidden report, when an account loses a
  framework.** Rejected: it throws away the result of model calls already
  made, and the Owner loses work.
- **A run from a paused job with only the allowed frameworks, or with all of
  them.** Rejected: the first changes the analysis with no request from the
  Owner, and the second lets a member bypass a restriction through one paused
  job.
- **A picker that shows a restricted framework, or a note about it, and a 403
  for a restricted name.** Rejected: each tells a member that the framework
  exists.
- **Role entries in the audience.** Not added: with two roles, an
  `administrator` entry adds nothing and a `member` entry equals no
  restriction. The effort that adds the manager role adds them.

## Consequences

A framework's options, such as the ASVS level, are not restricted. A member
who can run a framework can choose any of its options. A later effort can add
an option limit as a field of a restriction.

Each page that a member sees and that lists frameworks must read the one
reader, never the carried set.
