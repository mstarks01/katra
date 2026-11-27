# An OIDC login session in the web app (#2409)

**Question.** What do the standards require of the web app when it becomes an
OIDC relying party? The scope is the authorization code flow with PKCE, `state`
and `nonce`, the session cookie, server-side session storage, CSRF protection,
the idle and absolute timeouts, logout at the app and at the provider, and the
session after a role change. Which maintained Python library fits the web app
and the `oidc` backend in `src/katra/auth.py`?

This file records facts. It makes no decision. The session design ticket #2410
makes the decisions.

**Date:** 2026-11-27.

**Read against:**

- repo `d6943828` (`main`), with `fastapi==0.139.2`, `starlette==1.3.1`,
  `pyjwt==2.15.1`, `httpx==0.28.1` and `authlib==1.9.1` from `uv.lock`;
- OWASP ASVS 5.0.0, tag `v5.0.0_release` of `OWASP/ASVS`;
- the OWASP Cheat Sheet Series at commit `5254440` (2026-11-26);
- RFC 9700 (January 2025), RFC 9207 (March 2022), RFC 7636,
  `draft-ietf-httpbis-rfc6265bis-22` (December 2025);
- OpenID Connect Core 1.0 errata set 2, Discovery 1.0 errata set 2,
  Back-Channel Logout 1.0 errata set 1 (all 2023-12-15), RP-Initiated Logout
  1.0 and Front-Channel Logout 1.0 (both 2022-09-12);
- NIST SP 800-63B-4;
- PyPI, the GitHub Advisory Database and each project's repository advisories,
  read on 2026-11-27.

The ASVS text carries CC BY-SA 4.0. This file cites each requirement by its
number and states the point in its own words. The level of each requirement
is in brackets, such as [L1]. Katra states no target ASVS level for the web
app, so this file lists the requirements of all three levels.

## Summary

1. The flow: use the authorization code flow. The client must have CSRF
   protection on the callback. PKCE or a one-time `state` gives it. For a
   confidential client, RFC 9700 recommends PKCE with `S256`. It does not
   require PKCE. The `nonce` must match the ID Token, and each of these values
   must be bound to the browser session that started the login.
2. The identity: identify the person by `iss` and `sub` only, never by
   `email`. Check the ID Token `aud` against the `client_id`. Check the
   discovery `issuer` against the configured issuer by exact match. The
   **Principal** already has this key.
3. The cookie: use `Secure`, `HttpOnly`, an explicit `SameSite` value and the
   `__Host-` prefix. Keep the name and the value under 4096 bytes. The
   callback from the provider is a cross-site navigation. So a cookie with
   `SameSite=Strict` does not reach it, and a `Lax` cookie does.
4. Storage: a server-side session satisfies the termination requirements
   directly. A self-contained session (a signed cookie) needs an extra
   mechanism, such as a list of terminated sessions or a per-account
   "not before" time.
5. CSRF: the web app already refuses each write that lacks
   `Sec-Fetch-Site: same-origin`. ASVS 3.5.3 accepts a strict check of the
   `Sec-Fetch-*` headers. Browsers send those headers only to an `https` or
   loopback origin. A back-channel logout POST comes from the provider's
   server, not from a browser, so it carries no such header.
6. Timeouts: ASVS requires an idle timeout and an absolute lifetime [L2].
   It does not give numbers. NIST SP 800-63B-4 gives 1 hour idle and 24 hours
   overall at AAL2. Termination must stop each further use of the session [L1].
   Disable or delete of an account must end all its sessions [L1].
7. Logout: RP-Initiated Logout sends the browser to the provider's
   `end_session_endpoint` with `id_token_hint`. Back-Channel Logout sends a
   signed logout token to the app, and the app must find the session by
   `sid` or by `iss` and `sub`. Front-Channel Logout depends on third-party
   cookies, and its own spec warns that browsers block them.
8. Role change: the cheat sheet requires a new session ID after each privilege
   change. ASVS 8.3.2 [L3] requires a change of authorization data to take
   effect at once.
9. Libraries: Authlib (BSD-3-Clause) is the only maintained candidate with a
   Starlette integration. Version 1.9.10 (2026-11-20) has no open advisory in
   the GitHub Advisory Database. The locked 1.9.1 is affected by nine
   repository advisories that 1.9.2 to 1.9.10 fix. Authlib 1.9.1 does not
   check the discovery `issuer`, the RFC 9207 `iss` parameter or a logout
   token. It takes the ID Token algorithms from the provider's metadata.
   PyJWT 2.15.1 is already in use and has no open advisory. It can verify an
   ID Token and a logout token, but it runs no login flow.

## 1. The web app today

These facts come from the code at `d6943828`.

- The web app is a FastAPI app (`webapp/main.py`). It embeds the service in
  process and does not call `/v1` over HTTP. It holds no bearer token.
- It binds `127.0.0.1` with no override (`HOST`, `webapp/main.py`).
  `TrustedHostMiddleware` admits only `127.0.0.1` and `localhost`
  (`LOOPBACK_HOSTS`, `webapp/page.py`).
- Each job belongs to one fixed caller, `OPERATOR = Identity.local(...)`,
  under a reserved local issuer. The app has no login and no session cookie.
- Each `POST`, `PUT` and `DELETE` route calls `_cross_origin` first. That
  check passes only when `Sec-Fetch-Site` equals `same-origin`
  (`is_same_origin`, `webapp/page.py`). A request with no such header fails
  the check.
- `SecurityHeaders` puts `nosniff`, `no-referrer` and `Cache-Control:
  no-store` on each response. Each page has a nonce CSP with
  `frame-ancestors 'none'`.
- `/v1` verifies bearer JWTs in `src/katra/auth.py` with PyJWT. It reads
  `KATRA_OIDC_ISSUER`, `KATRA_OIDC_AUDIENCE`, `KATRA_OIDC_JWKS_URL` and the
  optional `KATRA_OIDC_ALGORITHMS`. It refuses `none` and `HS*`, and it
  requires an `https` JWKS URL. It returns only the pair of `iss` and `sub`.
  Today the module has no client ID, no client secret, no discovery URL and
  no redirect URI.

## 2. The login: authorization code flow with PKCE

### What the sources require

| Topic | Source | The requirement, in this file's words |
| --- | --- | --- |
| Grant | RFC 9700 §2.1.1; OAuth cheat sheet item 10 | Use the authorization code grant. Do not use the implicit grant. |
| CSRF on the callback | ASVS 10.2.1 [L2]; RFC 9700 §2.1, §4.7.1 | The client must stop a forged callback. PKCE or a check of `state` gives this protection. A client may use PKCE for CSRF only after it confirms that the provider supports PKCE. Without PKCE, use `state` or `nonce`. |
| PKCE | RFC 9700 §2.1.1; RFC 7636 | PKCE is mandatory for a public client and RECOMMENDED for a confidential client. `S256` is the only method that does not expose the verifier. RFC 7636 sets the verifier to 43–128 characters. |
| Binding | ASVS 10.1.2 [L2]; RFC 9700 §2.1.1 | `code_verifier`, `state` and `nonce` must be unguessable and specific to one login. They must be bound to the client and to the browser session that started the login. The client must accept a code or an ID Token only from that login. |
| One-time `state` | RFC 9700 §4.2.4 | The client SHOULD invalidate `state` after its first use. |
| `nonce` | OIDC Core §3.1.2.1, §3.1.3.7 step 11, §15.5.2; ASVS 10.5.1 [L2]; RFC 9700 §4.5.3.2 | The `nonce` needs enough entropy and per-session state. The ID Token must carry the same `nonce`. The client disregards all tokens until that check passes. |
| Mix-up | ASVS 10.2.2 [L2]; RFC 9700 §4.4.2; RFC 9207 §2.4 | This applies only when the client can use more than one authorization server. The client stores the issuer of each request and compares the `iss` of the response with it. If the provider's metadata sets `authorization_response_iss_parameter_supported`, the client must reject a response without `iss`. |
| Metadata | ASVS 10.5.3 [L2]; OIDC Discovery §4.3 | The `issuer` in the discovery document must exactly equal the configured issuer. Otherwise the client rejects the metadata. |
| Scopes | ASVS 10.2.3 [L3] | Request only the scopes the app needs. |
| Tokens | ASVS 10.1.1 [L2] | Send a token only to a component that needs it. |
| Redirect URI | RFC 9700 §2.1, §4.1.3; ASVS 10.4.1 [L1, provider side] | The provider compares the redirect URI by exact string match. The client registers the exact callback URL. |
| Open redirect | OAuth cheat sheet item 1 | The client must not redirect the browser to a URL from a query parameter. This includes a "return to" value after login. |

### ID Token validation

OIDC Core §3.1.3.7 lists the checks. These are the ones for the code flow:

- `iss` must exactly equal the issuer (step 2).
- `aud` must contain the `client_id` (step 3; ASVS 10.5.4 [L2]). If `azp` is
  present, it SHOULD equal the `client_id` (step 5).
- The signature must be valid (step 6; ASVS 6.8.2 [L2], 9.1.1 [L1]). In the
  code flow, step 6 lets TLS to the token endpoint take the place of the
  signature check. ASVS 6.8.2 does not make this exception.
- `alg` SHOULD be `RS256` or the registered algorithm (step 7). ASVS 9.1.2
  [L1] requires an allowlist without `none`. ASVS 9.1.3 [L1] requires keys
  from a pre-configured trusted source.
- `exp` must be in the future (step 9; ASVS 9.2.1 [L1]). `iat` can bound the
  token age (step 10).
- `nonce` must match (step 11).
- If the app asks for `acr` or `max_age`, it SHOULD check `acr` and
  `auth_time` (steps 12 and 13). ASVS 6.8.4 [L2] requires these checks when
  the app needs a given strength or recency of login. If the provider does not
  send the claims, ASVS 6.8.4 requires a documented fallback that assumes the
  weakest login.
- ASVS 9.2.2 [L2] requires the right token type. An ID Token proves the login.
  An access token does not.

### Identity

- OIDC Core §5.7: only `iss` and `sub` together identify a person.
  `email`, `phone_number`, `preferred_username` and `name` must not be used
  as a unique identifier. ASVS 10.5.2 [L2] and 6.8.1 [L2] state the same
  point for one provider and for more than one provider.
- The **Principal** in `GLOSSARY.md` already uses the pair of issuer and
  `sub`. Decision 4 of #2405 forbids a link by email.

### Other authentication rows that touch the login

- ASVS 6.1.3 and 6.3.4 [L2]: document each login path, and enforce the same
  strength on each. The web app login and the `/v1` bearer token are two
  paths.
- ASVS 6.3.3 [L2]: require multi-factor authentication, or a documented
  reason and other controls. With OIDC, the provider performs the login. The
  app can only read `acr` and `amr` (ASVS 6.8.4).
- ASVS 7.6.2 [L2]: a new session needs the person's consent or an explicit
  action. A silent login (`prompt=none`) is an example to check against it.

## 3. The session cookie

| Attribute | Source | The requirement |
| --- | --- | --- |
| `Secure` | ASVS 3.3.1 [L1]; Session cheat sheet "Secure Attribute" | Set `Secure`. Use the `__Secure-` prefix if the name has no `__Host-` prefix. |
| `__Host-` prefix | ASVS 3.3.3 [L2]; RFC 6265bis-22 §4.1.3.2 | Use `__Host-` unless the cookie must go to other hosts. The browser accepts a `__Host-` cookie only with `Secure`, `Path=/` and no `Domain`. The Session cheat sheet recommends `__Host-` for a session ID. |
| `HttpOnly` | ASVS 3.3.4 [L2] | Set `HttpOnly` on a cookie that scripts do not need. Send a session token only in `Set-Cookie`. |
| `SameSite` | ASVS 3.3.2 [L2]; Session cheat sheet "SameSite Attribute" | Set `SameSite` to suit the purpose of each cookie. The cheat sheet requires an explicit `Strict` or `Lax` on a session cookie and prefers `Strict`. Do not rely on the browser default. |
| Size | ASVS 3.3.5 [L3] | Keep the name and the value under 4096 bytes together. |
| Lifetime | Session cheat sheet "Expire and Max-Age Attributes" | A cookie with `Max-Age` or `Expires` persists on disk. Browser close does not end a session reliably. The server must enforce expiry. |
| Entropy | ASVS 7.2.3 [L1]; Session cheat sheet "Session ID Entropy", "Server-Side Session Token Storage" | A reference token needs a CSPRNG and at least 128 bits of entropy. The cheat sheet sets 64 bits as the floor and recommends 128 bits or more for a token you generate. If a read of the session store is in the threat model, store a hash of the token, not the token. |

**The callback and `SameSite`.** RFC 6265bis-22 §5.2 classes a request as
same-site only when its URL is same-site with the "site for cookies" of the
request's client. For a top-level navigation, the client is the page that
started the navigation (§5.2.1). The provider's page starts the redirect to
the callback, so the callback request is cross-site. Two consequences follow.
This file derives them from those sections; it did not test them in a
browser.

- A `SameSite=Strict` cookie does not reach the callback. If the login
  transaction (`state`, `nonce`, `code_verifier`) lives in a `Strict` cookie,
  the callback cannot find it.
- A `SameSite=Lax` cookie reaches the callback, because the callback is a
  top-level `GET` navigation (§5.6.7.1). A `form_post` response mode makes the
  callback a cross-site `POST`, and a `Lax` cookie does not reach it.
- RFC 6265bis-22 §8.8.2 describes a two-cookie design for this case: a `Lax`
  cookie for reads, and a `Strict` cookie that each write requires.

## 4. Where the session lives

ASVS 7.4 names two kinds of session: a reference token with state on the
server, and a self-contained token.

- **A reference token (server-side session).** ASVS 7.4.1 [L1] requires that
  logout or expiry invalidates the session data on the server. ASVS 7.2.1 [L1]
  requires the server to verify each token. A server-side record can hold the
  timestamps for the idle and absolute timeouts, the **Account**, and the
  `sid` and `sub` for back-channel logout.
- **A self-contained token (a signed cookie).** ASVS 7.4.1 [L1] requires an
  extra mechanism to stop its use after termination. It names a list of
  terminated tokens, a per-account "not before" time, and a per-account
  signing key. ASVS 9.1.1 and 9.1.2 [L1] then apply to the cookie itself.
- ASVS 7.4.2 [L1] requires the app to end all sessions of an account at
  disable or delete. ASVS 7.4.5 [L2] lets an administrator end the sessions of
  one account or of all accounts. ASVS 7.5.2 [L2] lets the person see and end
  their own active sessions. Each of these needs a list of the sessions of an
  account.
- ASVS 7.1.2 [L2] requires a documented limit on concurrent sessions for one
  account, and the action at that limit.
- The Session cheat sheet ("Logging Sessions Life Cycle") recommends a log
  record for session creation, renewal, destruction and privilege change.

**Starlette `SessionMiddleware` (1.3.1, read from the installed source).** It
keeps the whole session as base64 JSON in one cookie, signed with
`itsdangerous.TimestampSigner`. The signature uses HMAC-SHA1 by default
(`itsdangerous` `Signer.default_digest_method`). The value is signed but not
encrypted, so the browser can read it. The defaults are the cookie name
`session`, `max_age` 14 days, `same_site="lax"` and `https_only=False`, so
`Secure` is off by default. The middleware has no server-side record, so it
cannot end one session before its signature expires. `itsdangerous` is not
in `uv.lock` today, so this middleware needs a new dependency.

## 5. CSRF

- ASVS 3.5.1 [L1]: a request to sensitive functionality must prove that it
  came from the app. Anti-forgery tokens or a non-safelisted header satisfy
  this.
- ASVS 3.5.3 [L1]: sensitive functions use `POST`, `PUT`, `PATCH` or
  `DELETE`, not a safe method. As an alternative, a strict check of the
  `Sec-Fetch-*` headers satisfies the requirement.
- The CSRF cheat sheet ("Fetch Metadata headers") accepts a `Sec-Fetch-Site`
  policy for apps that target modern browsers. It requires a fallback to
  `Origin` or `Referer` verification when the headers are absent. For a
  sensitive endpoint, it recommends that the app refuse a request without the
  headers.
- The same section states that browsers send `Sec-Fetch-*` only to a
  potentially trustworthy URL: `https`, or `localhost` and loopback. On a
  network bind over plain `http`, the headers are absent, and the current
  check refuses each write.
- The CSRF cheat sheet ("Limitations of SameSite") lists the conditions under
  which `SameSite` alone is enough: no shared registrable domain, no state
  change on a safe method, `Strict` or `Lax` with `__Host-`, and `Origin`
  verification as a second layer.
- Login CSRF (CSRF cheat sheet, "Possible CSRF Vulnerabilities in Login
  Forms"): an attacker can log a victim in as the attacker. With OIDC, the
  `state` or PKCE binding of section 2 is the control. The cheat sheet also
  requires a new session at login, not an upgrade of the pre-login session.
- RFC 6265bis-22 §5.6.7.1: Lax enforcement does not stop CSRF as a class. An
  attacker can still open a window or start a top-level navigation.
- **Back-channel logout.** The provider sends the logout token as an HTTP
  `POST` from its server. The request has no browser and no `Sec-Fetch-Site`
  header, so `_cross_origin` refuses it. The logout token itself
  authenticates the request (section 7).

## 6. Timeouts

- ASVS 7.3.1 [L2]: an idle timeout forces a new login, set by a documented
  risk decision.
- ASVS 7.3.2 [L2]: an absolute session lifetime forces a new login, set the
  same way.
- ASVS 7.1.1 [L2]: document both values and justify each deviation from the
  NIST SP 800-63B re-authentication rules.
- NIST SP 800-63B-4 §2.2.3 (AAL2): the overall timeout SHOULD be at most
  24 hours, and the idle timeout SHOULD be at most 1 hour. §2.1.3 (AAL1): the
  overall timeout SHOULD be at most 30 days, and an idle timeout is optional.
  §2.3.3 (AAL3): 12 hours overall and 15 minutes idle.
- The Session cheat sheet ("Session Expiration") gives common ranges: 2 to 5
  minutes idle for a high-value app and 15 to 30 minutes for a low-risk app.
  It gives 4 to 8 hours absolute for an app used through an office day. It
  requires the server to enforce both timeouts. A timeout that the client
  tracks is open to change by an attacker.
- ASVS 7.6.1 [L2] and 7.1.3 [L2]: document how the app session and the
  provider session relate, and force a new login when the maximum time
  between provider logins passes. OIDC Core §3.1.2.1 defines `max_age` and
  `prompt=login` for this. With `max_age`, the ID Token carries `auth_time`.
- ASVS 10.4.8 [L2] (provider side): a refresh token has an absolute expiry.
  The web app has no stated need for a refresh token, because it calls no API
  with the access token (section 1).

## 7. Logout

### At the app

- ASVS 7.4.1 [L1]: after logout or expiry, the session allows no further use.
- ASVS 7.4.4 [L2]: each authenticated page has a visible logout control.
- The Session cheat sheet ("Logout Button") requires the app to revoke all
  session IDs of one logical session together, including IDs from rotation.
- The Session cheat sheet ("Web Content Caching and Clear-Site-Data")
  requires `Cache-Control: no-store` on session responses. It recommends a
  `Clear-Site-Data` header at logout. The web app already sends `no-store`.

### At the provider: RP-Initiated Logout 1.0

- The provider publishes `end_session_endpoint` in its metadata (§2.1).
- The app redirects the browser there. `id_token_hint` is RECOMMENDED.
  `post_logout_redirect_uri`, `state`, `client_id`, `logout_hint` and
  `ui_locales` are OPTIONAL (§2).
- The `post_logout_redirect_uri` must be registered, and the provider
  redirects only on an exact match (§2, §3).
- Without `id_token_hint`, the provider must ask the person to confirm the
  logout (§2, §6). ASVS 10.6.2 [L2] states the same control on the provider
  side.
- So the app keeps the ID Token, or enough to send it, if it sends
  `id_token_hint`. A raw ID Token can be over 1 KB, which matters for a
  cookie limit of 4096 bytes (ASVS 3.3.5).

### At the provider: Back-Channel Logout 1.0

- The provider sends a signed logout token to the app's
  `backchannel_logout_uri` (§2.5).
- The logout token carries `iss`, `aud`, `iat`, `exp`, `jti` and an `events`
  claim with the member `http://schemas.openid.net/event/backchannel-logout`.
  It carries `sub`, `sid` or both. It must not carry `nonce` (§2.4).
- The spec RECOMMENDS a `typ` header of `logout+jwt` and notes that many
  deployments omit it (§2.4, §4.1). ASVS 10.5.5 [L2] goes further: it requires
  the app to check the `logout+jwt` type, the `events` member and the absent
  `nonce`. It also recommends a short expiry, such as two minutes.
- Validation (§2.6): check the signature as for an ID Token, refuse `none`,
  check `iss`, `aud`, `iat` and `exp`, check `sub` or `sid`, check `events`,
  check that `nonce` is absent. A `jti` replay check is optional. On a failure
  the app returns `400`. On success it returns `200` (§2.8).
- The app must find the sessions by `iss` and `sub`, by `sid`, or by both, and
  clear them (§2.7). A logout of a session that is already gone counts as a
  success.
- The `backchannel_logout_session_required` metadata tells the provider that
  the app needs `sid` (§2.2).
- So back-channel logout needs a store that maps `sid` or `sub` to the app's
  sessions, and an endpoint that the provider can reach on the network.

### At the provider: Front-Channel Logout 1.0

- The provider loads the app's `frontchannel_logout_uri` in an iframe.
- §4.1 of the spec states that browsers block third-party content, so the
  iframe may not see the app's cookie. It recommends code that detects this.

## 8. Session renewal and an account change

- ASVS 7.2.4 [L1]: issue a new session token at each login, including a
  repeated login, and end the old token.
- The Session cheat sheet ("Renew the Session ID After Any Privilege Level
  Change") requires a new session ID after each privilege change. It names a
  permission change and a switch to an administrator role as examples. It
  requires the app to destroy the old ID.
- ASVS 8.3.2 [L3]: a change of the data that authorization reads takes
  effect at once. Where that is not possible, as with a self-contained token,
  the app needs a control that alerts on and reverts actions taken after the
  change.
- ASVS 8.2.4 [L3]: adaptive controls apply both when a session starts and
  during the session.
- ASVS 7.4.2 [L1]: disable or delete of an account ends all its sessions.
- ASVS 7.4.3 [L2]: after a change of an authentication factor, the app offers
  to end the other sessions. With OIDC, the provider holds the factors, so
  the app learns of a change only through the provider, for example through
  back-channel logout.
- ASVS 7.5.1 [L2] and 7.5.3 [L3]: a change to sensitive account data and a
  highly sensitive operation need a new login or a further factor. OIDC
  `max_age=0` or `prompt=login` forces the provider to log the person in
  again (OIDC Core §3.1.2.1).
- With a server-side session that reads the **Account** on each request, a
  role change takes effect at the next request. With a role copied into a
  signed cookie, the old role stays valid until the cookie expires or a
  revocation check (section 4) refuses it.

## 9. Libraries

### The candidates

| Library | Latest release | In `uv.lock` | Open advisories against the latest release | Starlette fit | Login flow | Session | RP-Initiated Logout | Back-channel logout token |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Authlib | 1.9.10, 2026-11-20 (1.10.0b1 on 2026-11-12) | 1.9.1, through `google-adk==2.5.0` | none in the Advisory Database; 1.9.1 is affected by 9 repository advisories | Yes: `authlib.integrations.starlette_client` | Yes | No; it stores the login transaction in `request.session` | Yes: `logout_redirect` | No |
| PyJWT | 2.15.1, 2026-09-28 | 2.15.1, direct | none | Framework-neutral | No | No | No | It can verify the token; the app checks `typ`, `events` and `nonce` |
| idpyoidc | 5.0.0, 2024-09-15 | no | none | No ASGI integration; it uses `requests` (synchronous) | Yes (`RPHandler`) | No | Yes (`end_session`) | Yes (`BackChannelLogoutRequest`) |
| oic (pyoidc) | 1.7.0, 2024-04-25 | no | none (CVE-2020-26244 fixed in 1.2.1) | No ASGI integration | Yes | No | Not read | Not read |
| fastapi-sso | 0.23.0, 2026-09-21 | no | none (CVE-2025-14546 fixed in 0.19.0) | FastAPI | Yes | No | Not read | No |
| fastapi-oidc | 0.1.0, 2026-06-15 | no | none | FastAPI | No: it verifies bearer ID Tokens for an API | No | No | No |
| starsessions | 2.2.1, 2024-10-23 (2.3.0a1 on 2026-03-16) | no | none in the Advisory Database | Starlette | No | Yes: server-side stores, ID regeneration | No | No |
| itsdangerous | 2.2.0, 2024-04-16 | no | none | Needed by Starlette `SessionMiddleware` | No | Signs the cookie | No | No |

### Authlib

**Maintenance.** The `authlib/authlib` repository had its last push on
2026-11-20. Authlib shipped nine patch releases (1.9.2 to 1.9.10) between
2026-11-01 and 2026-11-20. Each release has only security entries in the
changelog. The Advisory Database lists 17 Authlib advisories published
between 2026-01-08 and 2026-10-30, and the repository lists nine more
between 2026-11-01 and 2026-11-17. Many concern the server side (grants,
client registration, OAuth 1.0 server). These concern the client or the
`authlib.jose` code that the client uses:

- GHSA-c5mf-xmp2-59rc (fixed 1.9.0): an ID Token with `nonce_supported: false`
  turned off the nonce check in `parse_id_token`.
- GHSA-m344-f55w-2m6j (fixed 1.6.9): the `at_hash` and `c_hash` check failed
  open on an unknown algorithm.
- GHSA-jj8c-mmj3-mmgv (fixed 1.6.11) and GHSA-fg6f-75jq-6523 (fixed 1.6.6):
  with the `cache` option, the login state was not bound to the browser
  session. This allowed login CSRF and a one-click account takeover.
- GHSA-f7j6-p4qx-gq99 (fixed 1.9.5) and GHSA-8cj9-p42v-64gg (fixed 1.9.7):
  `authlib.jose` HMAC key confusion and a JWE denial of service.

The nine repository advisories from November 2026 are not in the global
Advisory Database on 2026-11-27. A scanner that reads only that database
does not flag `authlib==1.9.1`.

**Fit, read from the installed 1.9.1 source.**

- `StarletteOAuth2App.authorize_redirect` stores `redirect_uri`,
  `code_verifier` and `nonce` under the key `_state_<name>_<state>` in
  `request.session`, with a one-hour expiry
  (`FrameworkIntegration.expires_in = 3600`). Any middleware that puts a
  dict-like session in the ASGI scope works. Starlette's `SessionMiddleware`
  and starsessions both do.
- `authorize_access_token` raises `MismatchingStateError` if no stored data
  matches `state`. It clears the stored data after one use.
- PKCE is on only when the client sets `code_challenge_method` (for example
  `S256`) in `client_kwargs`. The verifier is 48 characters from a
  62-character alphabet, from `random.SystemRandom`.
- The client adds a `nonce` (20 characters, about 119 bits) when the scope
  contains `openid`. It validates the ID Token only when the token response
  has `id_token` and the stored data has `nonce`.
- `parse_id_token` checks `iss` against the `issuer` of the fetched metadata,
  not against a configured value. It checks `aud` against the `client_id`,
  with a default leeway of 120 seconds.
- `parse_id_token` takes the algorithm list from the provider's
  `id_token_signing_alg_values_supported`, with `RS256` as the default. The
  docstring of `OidcSettings._allowed_algorithms` in `src/katra/auth.py`
  states that the `/v1` verifier refuses that pattern.
- `load_server_metadata` does not compare the metadata `issuer` with the
  discovery URL. ASVS 10.5.3 and OIDC Discovery §4.3 require that comparison.
- `authorize_access_token` reads only `code` and `state` from the callback.
  It does not read the RFC 9207 `iss` parameter.
- `logout_redirect` builds the RP-Initiated Logout redirect. It adds a random
  `state` when `post_logout_redirect_uri` is set.
- No code in the package handles `logout_token` or `backchannel_logout`.
- The client uses `httpx` (in `uv.lock`) and `joserfc` (1.7.7 in `uv.lock`;
  the Advisory Database lists no open advisory for it).

### PyJWT

PyJWT 2.15.1 is a direct dependency, and `src/katra/auth.py` uses it. It has
no open advisory: each advisory in the database names a range that ends at
2.14.0 or lower. It verifies the signature, `exp`, `iss` and `aud`, and it can
require claims. It does not check `nonce`, `typ`, `events` or `azp`.
`jwt.decode_complete` returns the header, so code can check `typ`.
`PyJWKClient` in 2.15.1 has a `cooldown_duration` argument (default 30
seconds). PyJWT runs no part of the login flow: no authorization URL, no PKCE
pair, no code exchange, no discovery.

### Other candidates

- **idpyoidc** has a full RP with back-channel logout support. It uses the
  synchronous `requests` client and has no ASGI integration. Its last PyPI
  release is from 2024-09-15, and its repository had its last push on
  2026-10-02.
- **oic (pyoidc)** has no release since 2024-04-25. Its repository is active
  (last push 2026-11-27).
- **fastapi-sso** targets social login. It sets `uses_pkce = False` by
  default. With `use_id_token_for_user_info`, it decodes the ID Token without
  a signature check (`_decode_id_token`, `verify=False`). It sends no
  `nonce`. Version 0.22.0 turned the `state` check on by default.
- **fastapi-oidc** verifies bearer ID Tokens for an API. It does not run a
  login flow.
- **starsessions** gives server-side session stores (memory, Redis, custom)
  and session ID regeneration for Starlette. Its last stable release is from
  2024-10-23. The alpha 2.3.0a1 (2026-03-16) contains a commit named
  "security: fix multiple vulnerabilities found in audit". No advisory names
  those fixes, and no stable release carries them.

## 10. Questions that #2410 must answer

These questions follow from the facts above. This file does not answer them.

1. Which ASVS level does the web app session target? The level decides
   whether rows such as 7.3.1, 7.4.5, 10.5.5 and 8.3.2 apply.
2. Is the session a server-side record or a signed cookie? Termination,
   back-channel logout, admin termination and role changes depend on it.
3. Which library runs the login flow: Authlib, or code over PyJWT and
   `httpx`? If Authlib, which gaps does Katra close itself (metadata `issuer`,
   the algorithm allowlist, RFC 9207 `iss`, the logout token)? Which minimum
   version does Katra pin?
4. Which `SameSite` value does each cookie get, given that the callback is a
   cross-site navigation?
5. What are the idle and absolute timeouts, and do they follow NIST AAL1 or
   AAL2?
6. Does logout reach the provider (RP-Initiated), and does the app accept
   back-channel logout?
7. What does the app do with an open session when an administrator changes
   the role or disables the account?
8. Which **Deployment Settings** does the login add (client ID, client
   secret, discovery URL, redirect URI, timeouts), and how do they relate to
   the `KATRA_OIDC_*` settings of `/v1`?
9. How does the same-origin check behave on a network bind without `https`,
   where the browser sends no `Sec-Fetch-Site`?

## Sources

- OWASP ASVS 5.0.0: [V3](https://github.com/OWASP/ASVS/blob/v5.0.0_release/5.0/en/0x12-V3-Web-Frontend-Security.md),
  [V6](https://github.com/OWASP/ASVS/blob/v5.0.0_release/5.0/en/0x15-V6-Authentication.md),
  [V7](https://github.com/OWASP/ASVS/blob/v5.0.0_release/5.0/en/0x16-V7-Session-Management.md),
  [V8](https://github.com/OWASP/ASVS/blob/v5.0.0_release/5.0/en/0x17-V8-Authorization.md),
  [V9](https://github.com/OWASP/ASVS/blob/v5.0.0_release/5.0/en/0x18-V9-Self-contained-Tokens.md),
  [V10](https://github.com/OWASP/ASVS/blob/v5.0.0_release/5.0/en/0x19-V10-OAuth-and-OIDC.md)
- OWASP cheat sheets: [Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
  [CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
  [OAuth 2.0](https://cheatsheetseries.owasp.org/cheatsheets/OAuth2_Cheat_Sheet.html)
- [RFC 9700, OAuth 2.0 Security BCP](https://www.rfc-editor.org/rfc/rfc9700.html);
  [RFC 9207, issuer identification](https://www.rfc-editor.org/rfc/rfc9207.html);
  [RFC 7636, PKCE](https://www.rfc-editor.org/rfc/rfc7636.html);
  [draft-ietf-httpbis-rfc6265bis-22](https://www.ietf.org/archive/id/draft-ietf-httpbis-rfc6265bis-22.txt)
- OpenID: [Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html),
  [Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html),
  [RP-Initiated Logout 1.0](https://openid.net/specs/openid-connect-rpinitiated-1_0.html),
  [Back-Channel Logout 1.0](https://openid.net/specs/openid-connect-backchannel-1_0.html),
  [Front-Channel Logout 1.0](https://openid.net/specs/openid-connect-frontchannel-1_0.html)
- [NIST SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html)
- Authlib: [changelog](https://docs.authlib.org/en/stable/upgrades/changelog.html),
  [repository advisories](https://github.com/authlib/authlib/security/advisories),
  source of 1.9.1 in the project environment
  (`authlib/integrations/starlette_client/apps.py`,
  `authlib/integrations/base_client/`)
- PyJWT: [repository advisories](https://github.com/jpadilla/pyjwt/security/advisories),
  source of 2.15.1 in the project environment
- Starlette `starlette/middleware/sessions.py` 1.3.1 in the project
  environment; itsdangerous [`signer.py`](https://github.com/pallets/itsdangerous/blob/main/src/itsdangerous/signer.py)
- [idpy-oidc](https://github.com/IdentityPython/idpy-oidc),
  [pyoidc](https://github.com/CZ-NIC/pyoidc),
  [fastapi-sso](https://github.com/tomasvotava/fastapi-sso),
  [fastapi-oidc](https://github.com/HarryMWinters/fastapi-oidc),
  [starsessions](https://github.com/alex-oleshkevich/starsessions)
- Release dates: the PyPI JSON API. Advisories: the GitHub Advisory Database
  (`gh api advisories?ecosystem=pip&affects=<name>`) and each repository's
  security advisories.
