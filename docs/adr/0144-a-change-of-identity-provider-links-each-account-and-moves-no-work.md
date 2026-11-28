# 144. A change of identity provider links each account and moves no work

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2414](https://github.com/mstarks01/katra/issues/2414), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)
- **Relates to**: [ADR 0137](0137-an-identity-source-admits-people-by-invitation-or-by-group.md),
  [ADR 0140](0140-authlib-runs-the-protocol-steps-and-katra-checks-the-tokens.md),
  [ADR 0141](0141-the-public-origin-decides-the-network-posture.md),
  [ADR 0143](0143-an-accounts-work-outlives-each-administrative-change.md),
  [ADR 0151](0151-a-login-key-and-an-api-key-are-random-values-that-the-service-stores-as-digests.md)

## Context

An install can move its people from one **Identity Source** to another, such as
from one company provider to a new one. A provider can also keep its people
and change only its issuer URL. Each **Account** holds an owner ID, and each
object key starts with it (ADR 0065), so a change of provider must not change
the owner ID. An email match alone never links a new **Principal** to an
account, because a person can often set an email claim in some provider.

## Decision

**A change of provider links a new Principal to each existing account.** The
person keeps the account, its owner ID, its **Role**, its **Limit Override**
and its **Legal Hold**. The move of ADR 0143 serves only to give one person's
work to a different person.

**The service accepts two proofs for a link.** The first is a login with both
identities in one session. The second is a **Link Code**, which an
administrator makes for one account. The service shows the code once, stores a
digest, and lets it expire after 7 days or a revoke. The service refuses a link
of an identity that already belongs to another account. Each link writes an
audit record and gives a notice to the person.

**An administrator links many accounts through a change window.** The
administrator allows the new source beside the old one and marks it as the
replacement of the old source. At each login through the old source, the
service asks the person to link an identity from the replacement, and the
person can skip that step until the old source goes. A window between the
**Login Key** source and an OIDC source has an end date (ADR 0151). An
administrator page lists each account with no Principal on the replacement,
and one action makes a Link Code for each of them. The service gives these codes to the
administrator once, as a file of account names and links.

**The old source stays the only authority for a mapped role until its
removal.** An account that a group mapping binds to the old source can link a
Principal only from the replacement. A login through the replacement keeps the
role that the old mapping set last. At the removal of the old source, the
binding moves to the replacement. If the replacement has no mapping, the
account becomes unbound and keeps its last role, and the removal form states
this before the removal.

**An unknown identity on a replacement source gets a link page.** The page
offers a login through the old source and the entry of a Link Code. On an open
source only, it also offers a new account, with a warning that names the old
source. The page holds the identity only in the login record of ADR 0140, and
the service stores nothing about the person until a choice completes.

**A removal or a disable of the old source warns and does not refuse.** The
form lists the accounts with no Principal on the replacement and offers the
file of Link Codes. Only the last-administrator guard of ADR 0143 refuses the
change. The replacement mark ends with the removal of the old source. The
accounts and their work stay.

**A Principal belongs to its source, not to an issuer string.** The source and
the `sub` claim identify a Principal. An administrator can edit the issuer URL
of a source, and each Principal keeps its link. The edit is a trial, as in ADR
0141: it takes effect only when an administrator logs in through the new issuer
within 10 minutes and the `sub` of that login matches the administrator's own
Principal on the source. Otherwise the edit reverts. Each edit writes an audit
record.

## Considered options

- **A move of the work to a new account for each person.** Rejected: it changes
  each owner ID, copies each object in the install, adds a move to the history
  of work that did not change hands, and leaves the role, the override and the
  hold on the old account.
- **An administrator types the new issuer and `sub`, for one account or in a
  file.** Rejected: many providers make `sub` an opaque value, and one wrong
  row gives a person the wrong account with no proof from that person.
- **A match on a claim that the administrator trusts, such as an employee
  number.** Rejected: a person can sometimes edit such a claim in one of the
  two providers, which is the takeover path of an email match.
- **Two mappings that both set the role during the window.** Rejected: the role
  changes at each login when the two mappings disagree.
- **A refusal to remove the old source while an account has no link.**
  Rejected: an account of a leaver never gets a link, so each such account
  would need a disable or a delete first.
- **A new source for each new issuer URL.** Rejected: each person would link
  again when only a hostname changed.

## Consequences

A company whose old provider stops on a fixed date cannot use the login with
both identities, so each person gets a Link Code. A stolen Link Code gives the
account to the thief, as a stolen **Invitation** does. During a window, a person
whom the old directory removes can still log in through the replacement with
the old role, until an administrator disables the account. The issuer trial
proves that one `sub` matches. It does not prove that every `sub` matches, so it
catches a typing error or the wrong tenant, and it does not stop an
administrator who points the source at a provider that reuses `sub` values.
