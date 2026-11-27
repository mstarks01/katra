# 137. An identity source admits people by invitation or by group

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2406](https://github.com/mstarks01/katra/issues/2406), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)

## Context

An install can allow more than one **Identity Source** at the same time. Some
sources limit who can log in, such as a company provider that admits only the
members of a directory group. Other sources, such as Google, admit anybody.
The service must not give an **Account** to a stranger, and it must not keep a
**Role** that the directory has taken away.

## Decision

**Each identity source is open or invitation only, and a new source is
invitation only.** An open source gives a `member` account at the first login.
An invitation-only source admits a person only with an **Invitation**. An
administrator edits the sources in the web app, and a source is data, not a
Deployment Setting.

**By default the role lives in the account record. A source can map groups to
roles instead.** The mapping names a claim and maps each group value to a role.
A source with a mapping is always open, sets the role at each login, and
refuses a token that holds no group claim or no mapped group. An account whose
role a mapping sets logs in only through that source, so a person whom the
directory removes has no other way in.

**An invitation is a single-use code with a role.** The service shows the link
once and stores a digest of the code. The administrator sends the link. The
code expires after 7 days, and the administrator can revoke it. The service
refuses an invitation for a Principal that already has an account. It sends no
email.

**A refused person sees a plain refusal page, and the service stores nothing
about them.**

**The service refuses a change after which no administrator can log in.** This
covers a mapping change and the removal of a source.

## Considered options

- **A role only in the account record.** Rejected for a company provider: a
  person who leaves the administrator group keeps the role until somebody edits
  the account. A directory administrator gains no new power from the mapping,
  because that person can already reset the password of any directory login.
- **A login through another source with the stored role, or with `member`.**
  Rejected: both leave a way in for a person whom the directory removed.
- **An invitation and a mapping on the same source.** Rejected: the role on the
  invitation would do nothing.
- **A list of access requests from refused people.** Rejected: anybody with a
  public login could add rows and put text on an administrator's page.
- **A group check in the service for a source that the provider already
  limits.** Not required: the provider's own rule is the gate. A mapping is the
  place for a group check when the administrator wants one.

## Consequences

The claim name and each group value are data on the source, because providers
send a group as a name, a distinguished name or an identifier, and one provider
drops the claim when a person has many groups. A move to a new provider needs a
new mapping. A group change takes effect at the next login, so the session
design decides how a group change ends an open session.
