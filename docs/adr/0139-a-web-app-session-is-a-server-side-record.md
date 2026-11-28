# 139. A web app session is a server-side record

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2410](https://github.com/mstarks01/katra/issues/2410), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)

## Context

The web app serves more than one person, and a login is required on every
bind. An administrator can disable an account or change its role, and a source
with a group mapping sets the role at each login (ADR 0137). Many company
providers, such as Entra ID, AD FS and PingOne, cannot tell the app about a
logout or a disable. So the app's own **Session** is the control that ends
access. The target is ASVS 5.0 level 2, plus the level 3 rows that cost almost
nothing.

## Decision

**A session is a row in the job store, and each request reads the row and the
Account.** The cookie holds only a random 256-bit session ID, and the row holds
a SHA-256 digest of it. The row records the Account, the Principal that logged
in, the login time, the last-use time, the provider's `sid` and `sub`, and a
short browser label such as "Firefox on Windows". With the `memory` job store,
a restart ends all sessions.

**Two cookies carry the login.** Both are `__Host-`, `Secure`, `HttpOnly`,
`Path=/` and `SameSite=Lax`. `__Host-katra-login` holds the ID of a login
record for 10 minutes. `__Host-katra-session` holds the session ID and has no
`Max-Age`. Each login makes a new session ID and ends the old one. The
`Sec-Fetch-Site: same-origin` check on each write stays the CSRF control.

**The server enforces two timeouts.** The idle timeout is 1 hour by default and
5 minutes to 1 hour in range. The absolute lifetime is 8 hours by default and
1 to 24 hours in range. An administrator sets both as `install` Deployment
Settings, and the service refuses a value outside the range. At the end of a
session the person goes back to the provider, which applies its own policy
again.

**An end of a session never stops a job.** The job belongs to the Account. The
event stream reads the session row before each event and every 30 seconds, and
it closes with a `session-ended` event when the session has ended. A refused
submit gets `401` with the reason `session-ended`. The page keeps the typed
form in the tab, with the account ID, and restores it after a new login of the
same account only.

**A change takes effect at the next request.** A disable or a delete of an
account deletes all its session rows. A disable of an identity source, or the
removal of a Principal, ends each session that came through it. A role change
by an administrator applies at the next request. A group mapping sets the role
at the next login.

**Logout ends the Katra session only.** Each page has a "Log out" control. The
logged-out page links to the provider's `end_session_endpoint` when one exists,
and the provider asks the person to confirm. Each identity source has a
back-channel logout endpoint, which ends the sessions that match `sid`, or
`iss` and `sub`.

**Each account holds at most 10 sessions.** The 11th login ends the oldest. A
person sees their sessions on a Sessions page and can end them. An
administrator can end the sessions of one account, or of the whole install.

**Some actions need a login in the last 15 minutes.** These are a change to an
identity source (with its group mapping and MFA rule), a Principal link or
unlink, a Login Key replacement or revocation, and the "End" buttons of the
Sessions page. A refused write gets `401` with the reason `reauth-required`.
Katra then sends the person through the provider with `prompt=login`. A page
with such a write asks for the login when it opens if less than 5 minutes
remain. No Deployment Setting needs a recent login.

## Documented deviations

- **No new session ID at a role change.** The OWASP Session Management Cheat
  Sheet asks for one. That rule stops session fixation. Katra makes a session ID
  only after a provider login, so nobody can plant one.
- **A logout token without `typ` is accepted.** ASVS 10.5.5 requires the type
  `logout+jwt`, and the Back-Channel Logout spec notes that many providers leave
  it out. The endpoint refuses a wrong `typ` and accepts an absent one.
- **A login in the last 15 minutes counts as the new login that ASVS 7.5.2
  asks for before a session ends.** Without the window, each "End" click needs
  a full provider login.

## Considered options

- **A signed cookie (Starlette `SessionMiddleware`).** Rejected: an early end
  needs a "not before" time for each account, a role stays in the cookie, and
  it signs with HMAC-SHA1 by default.
- **A `Strict` session cookie, or a `Lax` and `Strict` pair.** Rejected: the
  provider's callback and a link from email are cross-site, so a `Strict`
  cookie does not arrive. The `Sec-Fetch-Site` check already covers each write.
- **A provider logout at each Katra logout.** Rejected: with a company provider
  it also ends the person's other company apps in that browser.
- **A recent login for each Deployment Setting.** Rejected: ASVS puts it at
  level 3, and the maintainer wants the friendliest design within level 2.

## Consequences

A non-loopback bind must serve `https`, or the browser refuses the cookies and
nobody can log in. With a group mapping, a person removed from the
administrator group can keep the role until the absolute lifetime ends, unless
the provider sends a back-channel logout. Each session event writes an audit
record in the format that the audit ticket decides.
