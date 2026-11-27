# MFA claims in the ID token of five OIDC providers (#2416)

Read 2026-11-27 from the documentation of each provider, of OpenID Connect
Core 1.0 (errata set 2) and of RFC 8176. Nothing was called or paid for. This
file records facts and rules nothing. The design decisions stay on map #2404.

## The question

Katra logs a person in only through an OIDC provider. Katra cannot enforce
multi-factor authentication (MFA) itself. The map wants an administrator
login to require MFA. So Katra needs two facts from each provider:

1. Which `amr` values and which `acr` values does the ID token carry after an
   MFA login?
2. Can the relying party ask for MFA, or for a new MFA check, through
   `acr_values`, `max_age`, `prompt=login` or a provider parameter? And does
   the provider then state the result in the token?

The providers are Microsoft Entra ID, Okta, Auth0, Keycloak and Ping Identity
(PingOne and PingFederate).

## The standards

### OpenID Connect Core 1.0

Source: <https://openid.net/specs/openid-connect-core-1_0.html>

- **`acr`** (Section 2) is OPTIONAL. It names the Authentication Context Class
  that the authentication satisfied. The value `"0"` means that the
  authentication did not meet ISO/IEC 29115 level 1, and such an
  authentication "SHOULD NOT be used to authorize access to any resource of
  any monetary value". "Parties using this claim will need to agree upon the
  meanings of the values used."
- **`amr`** (Section 2) is OPTIONAL. It is a JSON array of case-sensitive
  strings that identify the authentication methods. The values "SHOULD be
  from those registered in the IANA Authentication Method Reference Values
  registry".
- **`auth_time`** (Section 2) is REQUIRED when the request carries `max_age`
  or asks for `auth_time` as an Essential Claim. In other cases it is
  OPTIONAL.
- **`max_age`** (Section 3.1.2.1): when the elapsed time is greater than this
  value, "the OP MUST attempt to actively re-authenticate the End-User". The
  ID token then MUST include `auth_time`.
- **`prompt=login`** (Section 3.1.2.1): the server "SHOULD prompt the End-User
  for reauthentication". If it cannot, it MUST return an error, typically
  `login_required`.
- **`acr_values`** (Section 3.1.2.1) is OPTIONAL. It requests `acr` as a
  **Voluntary** Claim.
- **`claims` with an Essential `acr`** (Section 5.5.1.1): when the request
  asks for `acr` as an Essential Claim with given values, and the server
  supports the `claims` parameter, the server MUST return a matching value.
  If the server cannot meet the requirement, it MUST treat the result as a
  failed authentication. When the claim is not Essential and the server
  cannot give a requested value, it SHOULD return the current `acr` of the
  session.
- **ID token validation** (Section 3.1.3.7, items 12 and 13): when the client
  asked for `acr`, it SHOULD check that the value is appropriate. When it
  asked for `auth_time`, directly or through `max_age`, it SHOULD check the
  value and ask for a new authentication if too much time has elapsed.

### RFC 8176, Authentication Method Reference Values

Source: <https://www.rfc-editor.org/rfc/rfc8176.html>

RFC 8176 registers these `amr` values (Section 2): `face`, `fpt`, `geo`,
`hwk`, `iris`, `kba`, `mca`, `mfa`, `otp`, `pin`, `pwd`, `rba`, `retina`,
`sc`, `sms`, `swk`, `tel`, `user`, `vbm`, `wia`. The value `mfa` means
"multiple-factor authentication", and the token can list the specific methods
beside it. The registry has no `fido` value.

The RFC does not make `amr` a value that a relying party can request.
Section 1 states: "Whether "amr" values are provided and which values are
understood by what parties are both beyond the scope of this specification."
Section 3 compares the two claims: `acr` states that "the business rules for
the class were satisfied", and `amr` states which methods were used.

## Summary by provider

| Provider | `amr` after an MFA login | `acr` after an MFA login | How the relying party asks for MFA | What happens when the provider cannot meet the request |
| --- | --- | --- | --- | --- |
| Microsoft Entra ID | `mfa` plus method values such as `pwd`, `rsa`, `ngcmfa`, `totp`, `sms`, `fido`. In v2.0 tokens only when the app adds `amr` as an optional claim. | No `acr` in v2.0 tokens. The access token reference states that `acr` is "only present in v1.0 tokens" and is `0` or `1`. The `acrs` claim carries Conditional Access auth context IDs (`c1` to `c99`). | `claims` parameter with an Essential `acrs` value. The docs do not list `acr_values` or `max_age`. `prompt=login` re-enters credentials. | The token does not get the `acrs` value. |
| Okta | Example values include `pwd`, `mfa`, `sms`. The docs give no full list of the values that Okta emits. | The predefined value that the person satisfied, for example `urn:okta:loa:2fa:any`. | `acr_values` with a predefined value. `max_age` and `prompt=login` also work. | Error `unmet_authentication_requirements`. An unsupported `acr_values` value is ignored. |
| Auth0 | `["mfa"]`, only in the hosted login flow after an MFA challenge. Not after silent authentication or a refresh. | The example token shows `http://schemas.openid.net/pape/policies/2007/06/multi-factor`. | `acr_values` with the PAPE multi-factor URI, and an Action that reads it and calls `api.multifactor.enable`. `max_age` and `prompt=login` return `auth_time`. | The docs do not state it. The Action decides. |
| Keycloak (26.8.2) | Only the reference values that an administrator configures on each authenticator, and only with the AMR protocol mapper on the client. No default values are stated. | The level of authentication (LoA) number, or the name that the realm maps to it. `0` after a session-cookie login when the level expired. | `claims` with an Essential `acr`, or `acr_values` as non-essential. "Minimum ACR Value" on the client enforces a level on the Keycloak side. | Essential `acr`: Keycloak returns an error. `acr_values`: the docs do not state an error. |
| PingOne | The docs show only `pwd` in an example. They list no MFA value. | The name of the sign-on policy that the person completed. | `acr_values` with sign-on policy names, or one DaVinci flow policy ID. `max_age` also. | The docs do not state it. |
| PingFederate (13.1) | The core docs do not mention `amr`. An integration-kit guide adds `amr` to the OIDC policy attribute contract by hand. | The value of the `SAML_AUTHN_CTX` attribute, which a "Requested AuthN Context" selector can set from `acr_values`. | `acr_values` to a "Requested AuthN Context" selector. `max_age` and `prompt=login` also. | The selector fails and the next authentication policy runs. The docs state no error to the client. |

## Microsoft Entra ID

**`amr`.** The access token reference lists `amr` with the values `pwd`, `rsa`,
`otp`, `fed`, `wia`, `mfa`, `ngcmfa`, `wiaormfa` and `none`. It defines
`mfa` as "the use of Multifactor authentication" and states that the claim
"Includes the other authentication methods when this claim is present".
<https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference>

The ID token claims reference does not list `amr`, `acr` or `auth_time`.
<https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference>

The optional claims reference puts `amr` in the "v2.0-specific optional claims
set". Those claims "are always included in v1.0 tokens, but not included in
v2.0 tokens unless requested", and they apply to ID tokens and access tokens.
The same page states: "The `multipleauthn` and `mfa` values are emitted only
when the user has completed MFA." Its table of OIDC v2.0 values per method
follows:

| Entra method | `amr` values |
| --- | --- |
| Password | `pwd` |
| Authenticator push | `rsa`, `ngcmfa`, `mfa` |
| Authenticator TOTP | `totp`, `mfa` |
| Hardware OATH token | `hotp`, `mfa` |
| Phone sign-in | `swk`, `rsa`, `mfa` |
| SMS | `sms`, `mfa` |
| Phone call | `tel`, `mfa` |
| Email | `emailotp`, `mfa` |
| FIDO2 security key, passkey | `fido`, `mfa` |
| Windows Hello for Business | `hwk`, `mfa`, `ngcmfa` |
| Certificate-based authentication | `hwk` (multi-factor) or `x509` (single factor), `mfa`, `rsa` |
| Temporary Access Pass | `otp`, `mfa` |
| Windows integrated authentication | `wia` |
| Device-based X.509 | `x509` |

The page also states that `x509` alone "does not qualify as phishing-resistant
MFA". Entra forwards the `amr` values of an external MFA provider.
`auth_time` is an optional claim for JWTs on the same page.
<https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims-reference>

**`acr` and `acrs`.** The access token reference states that `acr` is "a `0` or
`1`, only present in v1.0 tokens". The value `0` means that the
authentication did not meet ISO/IEC 29115. The `acrs` claim "Indicates the
Auth Context IDs of the operations that the bearer is eligible to perform".
`acrs` is an optional claim for JWTs.
<https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference>

**How to ask for MFA.** Entra uses Conditional Access authentication context.
A tenant administrator defines context IDs `C1` to `C99` and attaches
Conditional Access policies to them, for example "Require strong
authentication". The app asks for a context through the `claims` request
parameter, for example `{"access_token":{"acrs":{"essential":true,"value":"c1"}}}`.
The feature needs a Microsoft Entra ID P1 licence. The docs tell apps not to
hard-code context IDs, because "the auth context ids in use could be
different and, in some cases, not available at all" in each tenant.
<https://learn.microsoft.com/en-us/entra/identity-platform/developer-guide-conditional-access-authentication-context>
<https://learn.microsoft.com/en-us/entra/identity-platform/claims-challenge>

The documented examples target the `access_token`. The auth context page
states that for opportunistic evaluation "Each token type needs to be
individually opted-in (ID token, Access token)".

**Does the token state the result?** Yes, for `acrs`. The auth context page
gives a table: when the app requests a context and a policy applies, the token
gets the `acrs` value only when the control is satisfied. When no policy is
attached to the context, the token still gets the value. So an `acrs` value
alone does not prove MFA. It proves that the policies on that context, if
any, were satisfied.

**`acr_values`, `max_age`, `prompt=login`.** The OIDC and auth code flow
references list `prompt` with the values `login`, `none`, `consent` and
`select_account`. "`prompt=login` forces the user to enter their credentials
on that request, negating single-sign on." The pages do not say that
`prompt=login` repeats MFA. The pages do not list `acr_values` or `max_age`.
<https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc>
<https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow>

## Okta

**`amr`.** The OAuth overview gives the example
`["pwd", "mfa", "otp", "kba", "sms", "swk", "hwk"]` and points to the AMR
values draft for the meanings. It lists `auth_time` as an ID token claim.
<https://developer.okta.com/docs/api/openapi/okta-oauth/guides/overview/>

The AMR claims mapping guide is about `amr` values that Okta accepts from an
external IdP. It shows an Okta ID token with `["sms", "mfa", "pwd"]` and
states: "Okta responds with the access token and the AMR claims in the ID
token." Its table maps authenticators to values, among them `pwd`, `kba`,
`email`, `sms`, `tel`, `otp`, `swk`, `phr`, `pop`, `fed`, `sc` and `hwk`.
The guide does not say that Okta uses the same table for its own outbound
tokens.
<https://developer.okta.com/docs/guides/configure-amr-claims-mapping/main/>

No page that this research read gives the full list of `amr` values that Okta
emits.

**`acr` and how to ask for MFA.** The step-up guide defines these
`acr_values`:

| Value | Meaning |
| --- | --- |
| `urn:okta:loa:1fa:any` | Any one factor. |
| `urn:okta:loa:1fa:pwd` | The password only. |
| `urn:okta:loa:2fa:any` | Any two factors. |
| `urn:okta:loa:2fa:any:ifpossible` | Two factors if the person enrolled them, else one. Identity Engine only. |
| `phr` | Phishing-resistant. Identity Engine only. |
| `phrh` | Phishing-resistant and hardware-protected. Identity Engine only. |

Both the org authorization server and custom authorization servers support
`acr_values`. "The authorization server returns an access token and/or an ID
token that contains the acr claim." The example ID token carries
`"acr": "urn:okta:loa:1fa:any"`, `"amr": ["pwd"]` and `auth_time`.
<https://developer.okta.com/docs/guides/step-up-authentication/main/>

**When Okta cannot meet the request.** "If the user is unable to satisfy the
level of assurance, Okta returns an error (`error=unmet_authentication_requirements`)
to the callback endpoint." But "Any unsupported acr_values sent in the
authorize request are ignored."
<https://developer.okta.com/docs/guides/step-up-authentication/main/>

**`max_age` and `prompt=login`.** `max_age=0` ignores the session and
re-authenticates each time (`max_age=1` on Classic Engine). The `/authorize`
reference states that `prompt=login` will "Always prompt the user for
authentication, regardless of whether they have an Okta session." On a
refresh, the tokens keep the `acr_values` of the original request, and the
guide says to use `auth_time` to see when that authentication occurred.
<https://developer.okta.com/docs/guides/step-up-authentication/main/>
<https://developer.okta.com/docs/api/openapi/okta-oauth/oauth/orgas/authorize>

## Auth0

**`amr`.** The step-up guide for web apps states that the `amr` claim "must be
present in the ID token's payload and must contain the value `mfa`" after an
MFA login. Its values "may include any of the pre-defined Authentication
Method Reference Values" of RFC 8176. If `amr` is absent or has no `mfa`,
"the user did not log in with MFA".

The guide lists two exceptions. In hosted login flows, Auth0 adds `amr` only
after the person passes an MFA challenge. "If the app uses silent
authentication or Refresh Tokens for newly issued ID tokens, the `amr` claim
will not be present." Tokens from the MFA API do not contain `amr`.
<https://auth0.com/docs/secure/multi-factor-authentication/step-up-authentication/configure-step-up-authentication-for-web-apps>

**`acr`.** The example ID token "with MFA" on the same page carries
`"acr": "http://schemas.openid.net/pape/policies/2007/06/multi-factor"` and
`"amr": ["mfa"]`. The page tells the app to validate `amr`, not `acr`. The
ID token structure page does not mention `acr`, `amr` or `auth_time`.
<https://auth0.com/docs/secure/tokens/id-tokens/id-token-structure>

**How to ask for MFA.** The app sends `acr_values` with the PAPE multi-factor
URI. The guide makes this work through an Action: the Action reads
`event.transaction.acr_values` and calls
`api.multifactor.enable('any', { allowRememberBrowser: true })` when the URI
is present. The guide does not state that `acr_values` alone, with no Action,
causes MFA.

**`max_age` and `prompt=login`.** With `max_age`, the ID token must carry
`auth_time`. "Auth0 has made a choice to send the `auth_time` claim in the ID
token when responding to a `prompt=login` request." The page warns that a
person can strip `prompt=login` in the browser. So the relying party must
check `auth_time` on the server. The page does not say that a new
authentication repeats MFA.
<https://auth0.com/docs/authenticate/login/max-age-reauthentication>

## Keycloak

All statements come from the Server Administration Guide for Keycloak
26.8.2. <https://www.keycloak.org/docs/latest/server_admin/index.html>

**`amr`.** "Authentication executions can optionally have a reference value
configured." When the client has the "Authentication Method Reference (AMR)"
protocol mapper, "it will populate the amr claim with the reference value for
any authenticator execution the user successfully completes". The guide
states no default reference values. So the `amr` values are what the realm
administrator configures.

**`acr`.** The realm maps each ACR value to a numeric level of authentication
(LoA). "The acr claim can be requested in the claims or acr_values parameter
sent in the OIDC request and it is also included in the access token and ID
token." The "acr loa level" protocol mapper in the default `acr` client scope
adds the claim. The step-up flow uses "Conditional - Level Of Authentication"
sub-flows, for example level 1 for username and password and level 2 for
username, password and OTP.

**How to ask for MFA.** The client sends `claims` with an Essential `acr`, for
example `{"id_token":{"acr":{"essential":true,"values":["gold"]}}}`, or
`acr_values` to "request particular levels as non-essential". "Default ACR
Values" on the client set the level when the request names none. The guide
states that a default level "cannot be reliably used to enforce login with
the particular level", because the person can send `acr_values=1`. "To
actually enforce the usage of a certain ACR on the Keycloak side, use the
Minimum ACR Value setting."

**`max_age`.** Each level condition has its own "Max Age". When a requested
level expired, Keycloak asks for that level again. "Max Age" `0` makes a level
valid for one authentication only. Without a requested level, an expired level
gives "acr in the token will have the value 0".

**When Keycloak cannot meet the request.** For an Essential `acr`, "Keycloak
will always return one of the specified levels. If it is not able to return
one of the specified levels ... then Keycloak will throw an error." The guide
also warns that the person can change `claims` or `acr_values` in the URL, and
says "clients are encouraged to check the ID Token to double-check that acr in
the token corresponds to the expected level."

**`prompt=login`.** The guide states that `prompt=login` "will always require
user to actively re-authenticate as described in the OIDC specification". The
guide does not mention `auth_time`.

## PingOne

**`acr`, `amr`, `auth_time`.** The token claims reference describes `acr` in
the ID token as "the name of the sign-on policy that was completed when the
original authentication was performed". It describes `amr` as "A string array
that specifies the methods associated with the authenticators used". The only
`amr` value on the page is `pwd` in an example. The page lists no MFA value.
`auth_time` is in the ID token, the access token and the refresh token.
<https://developer.pingidentity.com/pingone-api/foundations/authentication-concepts/access-tokens-and-id-tokens/token-claims.html>

**How to ask for MFA.** `acr_values` names "one or more PingOne policies by
specifying the policy names", separated by spaces, or "a single DaVinci
policy, by using its flow policy ID".
<https://docs.pingidentity.com/sdks/latest/oidc/sdkconfiguration/add-acr-values.html>

The step-up guide sends `acr_values=strong_authentication_policy&max_age=300`.
The server then asks the person to authenticate again with the named policy.
The guide puts the check of `acr` and `auth_time` on the resource server.
<https://docs.pingidentity.com/pingone/authentication/p1_stepup_authentication_for_apis.html>

The authorize reference lists `acr_values`, `max_age` and `prompt` as
optional strings and gives no further text.
<https://developer.pingidentity.com/pingone-api/auth/openid-connect-oauth-2/authorization/authorize-authorization_code-1.html>

**When PingOne cannot meet the request.** The pages that this research read do
not state it.

## PingFederate

All statements come from PingFederate 13.1 documentation.

**`acr` and `auth_time`.** "The `SAML_AUTHN_CTX` attribute is involved in
determining the authentication context value for the flow", and it is "mapped
into the `acr` claim in the OpenID Connect (OIDC) ID token".
`SAML_AUTHN_INSTANT` maps into `auth_time`. The page states no default `acr`
value for OIDC.
<https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/pf_special_attr_names_contracts.html>

**`amr`.** The PingFederate pages that this research read do not mention
`amr`. A Microsoft EAM integration guide extends the OIDC policy attribute
contract with `amr` and fills it from a source attribute. So in that setup an
administrator maps `amr` by hand, and PingFederate defines no values.
<https://docs.pingidentity.com/integrations/microsoft-eam/setup/pf_ms_eam_adjusting_the_oidc_policy_configuration.html>

**How to ask for MFA.** The authorization endpoint accepts `acr_values` as "a
space-separated string" in order of preference. It accepts `max_age`: "If the
elapsed time exceeds the value of `max_age`, PingFederate prompts the end user
for authentication." It supports `prompt` values `none`, `login`, `consent`
and `create`.
<https://docs.pingidentity.com/pingfederate/13.1/developers_reference_guide/pf_authorization_endpoint.html>

The "Requested AuthN Context" selector chooses authentication sources from the
contexts that the relying party requests. With "Override AuthN Context for
Flow", the selector result "takes precedence and determines the authorization
context" in "the outgoing assertion or ID token".
<https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/pf_config_request_authn_context_auth_selector.html>

**When PingFederate cannot meet the request.** When the requested context
matches no selector result value, "Selector evaluation fails and the next
applicable authentication policy is executed". The page states no error to
the client.

## Facts across the providers

1. **No `amr` value is common to all six products.** Entra, Okta and Auth0 document
   `mfa` after an MFA login. Entra emits it in v2.0 tokens only when the app
   requests the optional claim. Auth0 omits it after silent authentication
   and refresh. Keycloak emits only the values that an administrator
   configures. The PingOne and PingFederate pages define no MFA value.
2. **The method values are not all in RFC 8176.** Entra emits `fido`, `totp`,
   `hotp`, `emailotp`, `rsa`, `ngcmfa` and `x509`. Okta's inbound table uses
   `email`, `phr` and `pop`. None of these is in the RFC 8176 registry.
3. **No `acr` value is common.** Each provider defines its own: Okta's
   `urn:okta:loa:*` values, Auth0's PAPE multi-factor URI, Keycloak's realm
   mapping, the PingOne policy name and PingFederate's selector values. Entra
   v2.0 tokens carry no `acr`, and its `acrs` IDs differ in each tenant.
4. **Five products take `acr_values`. Entra takes `claims` with `acrs`.**
   Auth0 needs an Action to act on `acr_values`. Keycloak also takes
   `claims` with an Essential `acr`.
5. **The result of an unmet request differs.** Okta returns an error. Keycloak
   returns an error only for an Essential `acr`. PingFederate runs the next
   policy. Entra omits the `acrs` value. The Auth0 and PingOne pages do not
   state it. OIDC Core makes `acr_values` voluntary, so a provider may answer
   with the current `acr` of the session.
6. **The request alone proves nothing.** OIDC Core, Keycloak and Auth0 tell the
   relying party to check `acr`, `amr` or `auth_time` in the returned token.
   Keycloak and Auth0 state that the person can change or strip the request
   parameters in the browser.
7. **A new authentication does not always repeat MFA.** No provider page that
   this research read states that `prompt=login` or `max_age` alone repeats
   the second factor. Keycloak states that "Max Age" per level controls when
   a level must be shown again.

## What the docs do not state

- Entra: whether `amr` and `acrs` in the ID token behave the same as in the
  access token. The documented step-up examples use the access token.
- Okta: the full list of `amr` values that Okta emits in its own tokens.
- Auth0: whether `acr` is in the ID token when the request has no
  `acr_values`, and what happens when the Action does not enforce MFA.
- Keycloak: default `amr` reference values for the built-in authenticators,
  and `auth_time` in the Server Administration Guide.
- PingOne: the `amr` values after an MFA login, and the result when the policy
  that `acr_values` names cannot be satisfied.
- PingFederate: any built-in `amr` support outside a hand-mapped contract
  attribute.

A test login against each provider would settle these gaps. This research did
not run one.
