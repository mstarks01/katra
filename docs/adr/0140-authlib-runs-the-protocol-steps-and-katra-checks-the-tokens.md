# 140. Authlib runs the protocol steps, and Katra checks the tokens

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2410](https://github.com/mstarks01/katra/issues/2410), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)

## Context

The web app becomes an OIDC relying party. Authlib is the one maintained Python
library with a Starlette integration, and Open WebUI, Airflow and Superset use
it. But Authlib does not compare the discovery `issuer` with the configured
issuer, it takes the ID Token algorithms from the provider's metadata, it does
not check the RFC 9207 `iss` parameter, and it has no code for a logout token.
Its Starlette client also keeps the login data in `request.session`. Katra's
`/v1` verifier in `src/katra/auth.py` already checks JWTs with PyJWT, with a
fixed algorithm allowlist and keys from a configured JWKS. The maintainer
requires that the security code has review from outside this repository.

## Decision

**Authlib's low-level `httpx` client runs the protocol steps.** It builds the
authorization URL with `state`, `nonce` and a PKCE `S256` challenge, exchanges
the code and authenticates the client with `client_secret_basic` or
`client_secret_post`. Katra pins Authlib at 1.9.10 or later.

**Katra's session store holds the login record.** The record holds `state`,
`nonce`, the PKCE verifier, the identity source, the return page and a
reference to an Invitation or a setup mark. It is single use and expires after
10 minutes. Katra does not use `request.session`.

**The `/v1` PyJWT verifier checks each token.** One reader holds the algorithm
allowlist and the key rules for both surfaces. The web app adds the `nonce`,
`azp` and exact `issuer` checks for an ID Token, and the `events` and absent
`nonce` checks for a logout token. The discovery `issuer` must equal the
configured issuer exactly, and the callback checks the RFC 9207 `iss` when the
provider advertises it.

**The OpenID Foundation relying-party conformance suite must pass before the
login ships.** It runs in Docker as a provider that sends bad responses on
purpose, and the login must refuse each one.

## Considered options

- **Authlib's Starlette client.** Rejected: Katra would override parts of a
  library it does not control, so a patch release could stop a Katra check
  without an error. It also needs a session before the login.
- **Katra's own code for each step, over PyJWT and `httpx`.** Rejected: the
  protocol steps get less outside review than in a library.

## Consequences

Katra supports a client secret only. `private_key_jwt` and encrypted ID Tokens
can come later if a provider needs them. Entra ID, AD FS and the Ping products
all accept a client secret.
