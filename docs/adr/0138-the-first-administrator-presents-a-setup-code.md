# 138. The first administrator presents a setup code

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2406](https://github.com/mstarks01/katra/issues/2406), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)

## Context

An operator must be able to launch the container with no settings and finish
the setup in the web app. Until an administrator exists, a stranger who reaches
the port first must not be able to connect their own identity provider and take
the install.

## Decision

**The first administrator presents a Setup Code, and until the setup ends the
service serves only the setup page.** The code reaches the operator through a
channel that a stranger cannot see:

- If the Deployment Setting `KATRA_SETUP_CODE` holds a value, the setup page
  requires that value. The service refuses to start when the value is shorter
  than 32 characters.
- Otherwise the service makes a 256-bit code from the operating system's secure
  random source at each start, and writes a link to the log in the form
  `/setup#code=…`. The browser does not send the part after `#`, so the code
  stays out of access logs. A restart makes the earlier code invalid.

The setup page compares the code in constant time, under a rate limit. The
operator then enters the first identity source and logs in through it, and that
login becomes the first `administrator` account. The code then stops working.

**Recovery uses the same path.** When no administrator can log in, the operator
sets `KATRA_RECOVERY=1` and restarts, and the service makes a new setup code.

## Considered options

- **The first visitor becomes the administrator.** Rejected: a stranger can
  arrive first.
- **A default login.** Rejected: everybody knows the default.
- **Setup only from loopback.** Rejected: a container's port mapping makes the
  operator's browser look remote.
- **A command on the host that makes the code.** Rejected: a container platform
  can give the operator no shell.
- **A Deployment Setting that names the first administrator's issuer and
  `sub`.** Rejected: many providers make `sub` an opaque value that the person
  does not know before the first login.

## Consequences

A log collector that reads the container log sees the code, and the code works
until the setup ends. The identity source is data that the setup writes, so the
service stores the source's client secret, and that secret needs encryption at
rest.
