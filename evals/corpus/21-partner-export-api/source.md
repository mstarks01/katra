Partner export API: notes for the threat model, from the platform team.

We run an order platform for about forty merchant brands. Every brand's
customers and orders are in the order database. Some brands work with
partners, such as fulfilment houses, that need bulk copies of a brand's
customers or orders. The export API, the export worker, the export queue and
the stores below all run in our cloud account.

Partner access
- A partner's system calls the export API over HTTPS. The export API is on the internet.
- Each approved partner gets a client ID and a client secret. The partner's
  system swaps them at the export API's token endpoint for an access token that
  lasts one hour.
- The client secret never expires. We cannot rotate a secret without deleting
  the partner and approving it again.
- Each partner has scopes: the brands it may export, and whether it may export
  customers, orders or both. The export API checks the brand scope. Ines thinks
  it also checks the customers/orders scope, but nobody has confirmed it.
- The export API checks each client ID and secret against the partner registry
  and reads the partner's scopes from there. The partner registry keeps client
  secrets in plain text, so that a partner manager can read a secret back to a
  partner who lost it.

Export jobs
- A partner asks for an export of one brand, one record type and a date range.
  The export API puts an export job on the export queue and returns a job ID.
  Job IDs count up from 1.
- The partner then asks for the job's status by its job ID. Nobody wrote down
  whether the export API checks that the job belongs to the partner who asks.
- Nobody set a limit on how many exports a partner can ask for, or on how long
  the date range can be.
- The export worker takes jobs off the export queue one at a time. It reads
  the rows from the order database with one database account that can read every
  brand's tables. It does not check the job's brand against the partner's scopes
  again.
- The job carries the brand, the record type, the date range and the partner's
  callback URL.
- The worker writes each finished export as a CSV file to the export file store.
  An export holds customer names, email addresses, postal addresses and order
  history. Nobody deletes finished files. We do not encrypt the files, and
  nobody has checked whether the file store does.

Webhooks and downloads
- When a file is ready, the worker posts a webhook to the partner's callback
  URL, and waits for that call to finish before it takes the next job.
- Partners set their own callback URL through the export API. The worker does
  not check where a callback URL points. Callback URLs can start with http://
  as well as https://.
- Each webhook is signed with a secret we share with that partner.
- The webhook carries a signed download link that works for seven days. Anyone
  who holds the link can download the file straight from the export file store;
  the download asks for no token.

Admin console
- Our partner managers approve partners in the admin console. They create the
  client ID and secret and set the partner's scopes.
- The admin console runs in our cloud account and is reachable only over the
  office VPN. Partner managers sign in with the company single sign-on, which
  asks for a second factor.
- One partner manager can approve a partner and widen its scopes alone.

Audit log
- The audit log is a table in the partner registry. The export API writes a
  row for each token it issues and each job it creates. The admin console
  writes a row for each approval.
- Scope changes are not written to the audit log. Downloads are not recorded
  anywhere.
- The admin console can edit and delete any row in the partner registry,
  including the audit table.

Not recorded
- Nobody has written down how the export API, the worker and the admin console
  connect to the queue, the registry and the stores, or whether those
  connections are encrypted. How the order database and the partner registry
  are protected at rest is not recorded.
