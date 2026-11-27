# 142. The install limit queues a job, and the account limit refuses it

- **Status**: accepted
- **Date**: 2026-11-27
- **Effort**: [#2412](https://github.com/mstarks01/katra/issues/2412), on the
  multi-user accounts map [#2404](https://github.com/mstarks01/katra/issues/2404)
- **Relates to**: [ADR 0007](0007-per-caller-concurrency-ceiling.md)

## Context

The web app and `/v1` serve many accounts in one process. Each account has a
limit on its running jobs, `max_active_jobs`, and the admission counts the
account's jobs from both surfaces. ADR 0007 refuses a job over that limit and
does not queue it. Its reason: a queued job holds the caller's place in the
provider quota, so only a refusal reduces that caller's load.

Many accounts can run many jobs at the same time, and each job makes many model
calls in parallel. The global token bound counts tokens in a window, not jobs
at the same time. So many running jobs can exceed the provider's rate limit,
and the retries run out after the jobs have spent tokens. The jobs also share
the memory and the event loop of one process.

## Decision

**A Deployment Setting limits the running jobs of the whole install, with a
default of 10.** A job over this limit waits in a queue, in submission order.

**A queued job counts against its account's limits.** The admission checks the
account's running-job limit and its Consumption Budget before the job enters
the queue. Over the account's own limit, the service refuses the job, as ADR
0007 says. So the queue never holds more jobs than the sum of the account
limits.

**The job deadline starts when the job runs**, not when it enters the queue.
The page shows a queued job as waiting for a free place, and it names no other
account.

**A restart fails a queued job.** A job runs on the Deployment that admitted
it, and a restart can load another Deployment. A job that ends before it runs,
because of a restart or a stop by its owner, settles to zero tokens. Its
failure message says that the job never started, so a new submission is safe.

**The install token bound refuses a job and does not queue it**, because only
the passage of time clears that bound.

## Considered options

- **Refuse at the install limit too.** ADR 0007's reason does not apply here:
  the account limits already cap each account's load, and the queue only moves
  a job to a later time. A refusal makes each person and each pipeline try
  again by hand.
- **Keep queued jobs over a restart.** The job would run on a Deployment that
  did not admit it. That needs a second admission path, which checks the job
  again against the new Deployment. Restarts are rare, and a person must submit
  a running job again after a restart in any case.
- **No install limit.** The global token bound does not limit jobs at the same
  time, so a rate-limit failure spends tokens and gives no report.

## Consequences

A member gets a result later when the install is busy, and a pipeline needs no
retry loop for a busy install. A `/v1` account can hold more queue places than
a web app account, in the ratio that the account limits set. A job that waits
in the queue at a restart fails, and its owner submits it again.
