# 141. The public origin decides the network posture, and a change of it is a trial

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2411](https://github.com/mstarks01/katra/issues/2411), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)

## Context

The web app serves the network itself, and a login is required on every bind.
The session cookies are `__Host-` and `Secure` (ADR 0139). A browser sends a
`Secure` cookie and the `Sec-Fetch-Site` header only to an `https` origin or to
`localhost`. A plain `docker run` must work with setup in the web UI and no
required CLI step. In a container, the app must listen on `0.0.0.0`, but the
browser on the host still opens `http://localhost:<port>`. So the listen
address does not tell the app whether the browser has `https`. The target is
ASVS 5.0 level 2.

## Decision

**The Public Origin is the one setting that starts the posture.** It is the
scheme, the host and the port at which people reach the web app. The bind is a
separate setting, and it chooses only where the socket listens. The default
origin is `http://localhost:<port>`, and the default bind is `127.0.0.1`. A
container image binds `0.0.0.0` and keeps the `localhost` origin. The `Host`
allowlist is the origin's host, and the OIDC redirect URI is the origin plus the
callback path. No forwarded header sets the scheme or the host.

**The app can serve TLS itself, and a proxy is optional.** The app reads a
certificate file and a key file under the `*_FILE` rules, with TLS 1.2 as the
minimum version. An `https` origin with a non-loopback bind requires the app's
own TLS, so the hop from a proxy to the app is TLS too (ASVS 12.3.3). An
`https` origin with a loopback bind can run plain `http` behind a proxy on the
same host. A new certificate takes effect when the listener starts again.

**The app trusts one forwarded header, from listed peers only.** The app turns
off the `uvicorn` `proxy_headers`. One module reads `X-Forwarded-For` only when
the TCP peer is on the trusted proxy list. It takes the rightmost address that
is not a listed proxy. The list is empty by default.

**The startup refuses a wrong configuration.** The process exits with a message
that names the setting, unless each of these is true:

1. The origin is `http` or `https`, with a host, an optional port and nothing
   else.
2. An `http` origin has the host `localhost`, `127.0.0.1` or `[::1]`.
3. An `https` origin with a non-loopback bind has a certificate file and a key
   file that match. The group and other users cannot read the key file.
4. The trusted proxy list does not hold `0.0.0.0/0` or `::/0`.
5. The certificate names the origin's host.

An `http` `localhost` origin with a non-loopback bind is allowed, because a
container needs it. The startup writes one log line that names the bind and
the origin.

**A change of the network settings on the Settings page is a trial.** The
network settings are the origin, the bind, the certificate file, the key file
and the trusted proxy list. The save runs the same check function as the
startup. The app then swaps its listener in the same process, and the swap
stops no job. The page shows the new URL and a 10-minute timer. The
administrator confirms the change by an administrator login on the new origin.
That login proves DNS, TLS, the proxy and the identity provider's redirect URI
together. Without the confirmation, the app goes back to the last confirmed
settings, which it keeps in a separate record, and logs the revert. A process
start ignores unconfirmed values. A network variable in the environment
overrides the page, and the page shows that setting read-only.

**The CSRF and frame controls stay.** Each write requires `Sec-Fetch-Site:
same-origin`, with no `Origin` fallback. Each page sends `frame-ancestors
'none'`. A table in code exempts the back-channel logout route and names its
own credential, the logout token. A test fails on a writing route that has
neither the check nor a row in that table.

**HSTS follows the confirmation.** On a confirmed `https` origin, each response
carries `Strict-Transport-Security: max-age=31536000; includeSubDomains`. A
trial sends no HSTS, so a reverted trial leaves no HSTS record in a browser.
The app never sends `preload`.

## Considered options

- **The bind starts the posture: a non-loopback bind requires `https`.**
  Rejected: a container must bind `0.0.0.0`, so a plain `docker run` on
  `localhost` then needs a certificate.
- **TLS at a proxy only.** Rejected: the hop from a proxy in another container
  to the app is then plain `http`, and ASVS 12.3.3 refuses it at level 2.
- **`X-Forwarded-Proto` and `X-Forwarded-Host` from a trusted proxy.**
  Rejected: the origin already states both, and a second source of the scheme
  or the host can disagree with it.
- **The network settings in the environment only.** Rejected: a move to the
  network then needs a new `docker run` command. The trial removes the lockout
  risk that made this option attractive.
- **An `Origin` header check where `Sec-Fetch-Site` is absent.** Rejected: each
  current browser sends `Sec-Fetch-Site`, and a second accepted path is a
  second rule to keep correct.

## Consequences

The app cannot use a private key that only an HSM holds, because Python's `ssl`
module loads a key from a file. Such a key needs a PKCS#11 proxy on the same
host, with a loopback bind. A tool such as Keyfactor that delivers the
certificate and the key as files works. In a container, a move to the network
through the Settings page needs the first `docker run` to publish the port on
all host interfaces. Until that move, the login and setup pages answer on the
network, and the `Host` check refuses any other name. A proxy must append the
peer address to `X-Forwarded-For`, and the documentation gives the line for
each common proxy. Each change and each revert of the network settings writes
an audit record in the format that the audit ticket decides.
