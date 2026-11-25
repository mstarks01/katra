# Reading decisions: 21-partner-export-api

No extraction draft exists for this case, because a draft is a paid model call.
An agent wrote `model.json` by hand, sentence by sentence against `source.md`,
so there is no bootstrap value to reverse. The table records each decision a
correction pass would otherwise make, so that a reader can disagree with each
one specifically.

| # | Path | Value | Why (source text) |
|---|---|---|---|
| 1 | `data_stores` | no separate audit log store | "The audit log is a table in the partner registry." One store holds both, so the admin console's edit and delete reach the audit rows through the same flow. |
| 2 | `data_stores` | the export queue is a store | "The export API puts an export job on the export queue"; the worker "takes jobs off" it. Both flows point at the queue, because each side starts its own interaction. |
| 3 | `flow:…>request-exports.authentication` | client secret never expires and we cannot rotate it | "The client secret never expires. We cannot rotate a secret without deleting the partner". Both qualifiers sit in the attribute the spoofing lane reads, in the source's own words. The one-hour token and the deletion of the partner are in the description. |
| 4 | `flow:…>request-exports` | one flow for token, export, status and callback calls | The source names each call, and all of them go from the partner's system to the export API. |
| 5 | `flow:entity:partner-system>store:export-file-store>download-export` | entity to store, no process | "download the file straight from the export file store". The source names no download service. |
| 6 | `flow:…>download-export.authentication` | stated: a signed link that works for seven days, for anyone who holds it | A signed link is a mechanism, so the control is stated, not absent. "Anyone who holds the link" and "asks for no token" stay in the detail. |
| 7 | `flow:…>send-webhook.encryption_in_transit` | `unknown`, with the http:// qualifier | "Callback URLs can start with http:// as well as https://." Each partner's URL decides it, so the flow is not stated as absent. |
| 8 | `flow:…>send-webhook.authentication` | signed with a per-partner shared secret | "Each webhook is signed with a secret we share with that partner". |
| 9 | `flow:…>read-brand-rows.authentication` | one account that reads every brand's tables | "one database account that can read every brand's tables". |
| 10 | `process:export-worker.description` | no second scope check; waits for each webhook; no callback URL check | Three stated qualifiers, each kept where a lane reads it rather than only in an excerpt. |
| 11 | `process:export-api.notes` | two checks unstated, one hedged | "Ines thinks it also checks the customers/orders scope, but nobody has confirmed it" and "Nobody wrote down whether the export API checks that the job belongs to the partner". Neither is present or absent. |
| 12 | `store:partner-registry.description` | client secrets in plain text | "keeps client secrets in plain text". `encryption_at_rest` stays `unknown`: plain-text secrets are an application fact, and the source says protection at rest is not recorded. |
| 13 | `store:export-file-store.encryption_at_rest` | `unknown`, with the reason | "We do not encrypt the files, and nobody has checked whether the file store does." |
| 14 | `process:admin-console.exposure` | `internal` | "reachable only over the office VPN". |
| 15 | `flow:…>use-admin-console.encryption_in_transit` | `unknown` | The source names a VPN and says nothing of what it encrypts. |
| 16 | internal flows, `protocol`, `authentication`, `encryption_in_transit` | `unknown`, with notes | "Nobody has written down how the export API, the worker and the admin console connect … or whether those connections are encrypted." |
| 17 | `entity:partner-manager.trust_zone` | `boundary:office-vpn`, as an assumption | The source places the console's reach, not the managers. |
| 18 | `external_entities` | no element for the company single sign-on | "Partner managers sign in with the company single sign-on, which asks for a second factor." The model already holds 22 elements, the top of the band, and the source gives the sign-on no interaction beyond this sign-in. So it is the mechanism in `use-admin-console.authentication`, not an element. |
| 19 | `store:partner-registry` | no callback URLs | The source says partners set their callback URL through the export API and that the job carries it. It does not say where the URL is kept, so the registry does not hold it. |
| 20 | `process:export-api.assets` | `credentials` only | The export API issues tokens and checks secrets. The source gives it no personal data: the worker reads the rows and the file store holds them. |

## Signal

The worst findings sit after a legitimate export: the signed link, the
callback URL the partner sets, and the file store that keeps every file. A lane
that reads only the export API's front door finds none of them.
