# 147. A link replaces a Principal on the same source, and a removal keeps a mark

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2421](https://github.com/mstarks01/katra/issues/2421), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)
- **Relates to**: [ADR 0137](0137-an-identity-source-admits-people-by-invitation-or-by-group.md),
  [ADR 0139](0139-a-web-app-session-is-a-server-side-record.md),
  [ADR 0140](0140-authlib-runs-the-protocol-steps-and-katra-checks-the-tokens.md),
  [ADR 0143](0143-an-accounts-work-outlives-each-administrative-change.md),
  [ADR 0144](0144-a-change-of-identity-provider-links-each-account-and-moves-no-work.md),
  [ADR 0145](0145-an-audit-record-is-a-chained-row-and-a-json-log-line.md)

## Context

A person links a new **Principal** to their **Account** by a login with both
identities in one session (ADR 0144). The service sends no email (ADR 0137),
so a person learns about a link only in the web app. A link from a hijacked
session is the main risk: the attacker adds an identity of their own, or
replaces the owner's identity, and keeps the account.

## Decision

**The link is a second provider login inside a session.** The link needs a
provider login in the last 15 minutes (ADR 0139). Katra sends the person to the
chosen source with `prompt=login`, so the person chooses the identity on
purpose. The login record of ADR 0140 holds the ID of the session that starts
the link, and the callback links only to that session's account. The second
login applies every check of a normal login through that source, such as its
MFA rule and its group claim. A link needs no **Invitation**, because an
Invitation admits a new account, not a new identity of a known person.

**A link to a source with a group mapping applies the mapping.** The page first
shows the role that the mapping gives and says that the account's other
Principals stop working, because the link binds the account to that source
(ADR 0137). The last-administrator guard of ADR 0143 can refuse the link.

**An account holds one Principal for each source, and a link from the same
source replaces it.** The page names the old identity, and the person confirms
before the provider login. The new Principal and the removal of the old one
share one transaction, and the sessions of the old Principal end. A **Link
Code** link works the same way.

**The Identities section and a banner tell the person about each change.** The
section lists each Principal with its source, the email and name from its last
login, its link time, its link method and its last login. After a link, a
replacement or a removal, a banner shows at the next login through each other
Principal, until the person dismisses it.

**A removal or a replacement keeps a Removal Mark.** The mark holds the source,
the `sub`, the account ID, the time and the method. A login through a marked
identity gets a page that tells the person to ask an administrator, and it gets
no new account, also on an open source. An administrator clears the mark, or a
link of that identity to the account in the mark clears it. A self-service link
of a marked identity to any other account fails.

**A removal has five rules.**

1. A person can remove any of their own Principals, except the last one that
   can log in. For a bound account, only the Principal on the binding source
   can log in.
2. During a change window, a bound account cannot remove its Principal on the
   old source. The removal of the source takes that Principal away.
3. An administrator can remove any Principal of any account, also the last one.
   The last-administrator guard still applies.
4. A person can remove the Principal of the current session. The page warns
   first, and the session ends.
5. Each removal keeps a Removal Mark, writes an **Audit Record** and shows the
   banner.

**Six audit events cover the flow.** Each is OCSF 1.10.0 User Management
(3007), activity 99 "Other", with the event name in `activity_name`, because no
OCSF activity names a link of an identity.

| Event | Fields |
|---|---|
| `principal.linked` | method: `login-with-both` or `link-code` |
| `principal.replaced` | the old and the new source and `sub`, and the method |
| `principal.removed` | by: `self`, `administrator` or `source-removal` |
| `principal.link_refused` | reason: `identity-on-other-account`, `bound-account-source` or `login-check-failed` |
| `principal.marked_login` | a login through an identity with a Removal Mark |
| `removal_mark.cleared` | by: `administrator` or `link` |

A **Machine Account** has no web login, so this flow does not apply to it
(ADR 0146).

## Considered options

- **Refuse a link to a source with a group mapping.** Rejected: a person could
  then move to a company provider only in a change window.
- **Leave the account unbound after such a link.** Rejected: it gives a way past
  the directory, which ADR 0137 refuses.
- **Many Principals for each source, with a cap.** Rejected: one person needs
  one identity from each provider, and a second identity on a source is usually
  another person or an error.
- **Refuse a link from a source where the account has a Principal.** Rejected:
  a person with one Principal could never change it without an administrator.
- **The list of Principals only, with no banner.** Rejected: the owner must see
  a forced link soon, and nothing sends the owner to the list.
- **An email notice.** Rejected: it reverses ADR 0137 and adds mail settings to
  each install.
- **No mark after a removal.** Rejected: after a forced replacement of the only
  Principal, the owner's next login gives a new empty account and no sign of
  the loss.
- **The last-Principal guard for an administrator too.** Rejected: the
  administrator must act at once on a hijacked identity.
- **OCSF activity 2 "Update".** Rejected: a log tool cannot then tell a link
  from another change of the account.
- **No `prompt`, or `prompt=select_account`.** Rejected: a browser with a
  provider session can return another person's identity with no screen, and
  some providers do not support `select_account`.

## Consequences

A forced replacement of the only Principal still takes the account until an
administrator acts. The mark makes sure that the owner reaches an
administrator, and the Audit Records show the event. A person who removes an
identity on purpose cannot use it for a new account on an open source until an
administrator clears the mark. The permission table needs a permission for a
person's own Principals, one for any account's Principals and one to clear a
Removal Mark.
