# Each read and write that assumes one owner (#2417)

**Question.** Map [#2404](https://github.com/mstarks01/katra/issues/2404)
adds accounts. Which web app routes, store calls, pages and background tasks
assume one owner today? What must each one check when more than one account
exists?

**This file records facts. It decides nothing.** The permission table ticket
[#2419](https://github.com/mstarks01/katra/issues/2419) reads this list and
decides the permissions.

**Method.** Each row cites a file and a line at commit `91ef3a02` on `main`.
The rows come from a read of the code path and from a search for `OPERATOR`,
`held_owner_id`, `owner_id`, the store methods, the route decorators and the
pages.

## The state now

The web app has one fixed identity, `OPERATOR`
(`webapp/main.py:419`). It is the local caller `in-process` under the reserved
issuer `local:` (`src/katra/principals.py:27`). Each web app route reads or
writes the work of that one owner. The web app has no login. It binds to
loopback (`webapp/main.py:361`), it accepts only loopback host names
(`webapp/main.py:1699`), and its write routes check only that the request
came from its own page (`webapp/main.py:1490`).

The `/v1` API already takes the owner from the Principal of a bearer token
(`src/katra/api.py:600`). So `/v1` scopes each job read to one owner now. It
has no route for Owner Files, Controls or Deployment Settings.

## How to read the tables

- **The caller's account** is the Account of the web app session, or the
  Account that the `/v1` token's Principal links to (#2405, decision 4′).
- **"Owner, or `X` with an audit record"** means: the owner ID of the object
  equals the owner ID of the caller's account, or the caller's role holds `X`
  and the service writes an audit record of the access.
- **A permission name is a candidate.** Ticket #2419 decides the names. The
  candidates use the `work.read_any` form of #2405, decision 8.

| Candidate permission | What it allows |
|---|---|
| `work.create` | Submit a new analysis. |
| `work.read_own`, `work.change_own`, `work.delete_own` | Read, change or delete the jobs of the caller's account. |
| `work.read_any`, `work.change_any`, `work.delete_any` | The same for the jobs of every account. #2405 names `work.read_any` and `work.delete_any`. |
| `files.read_own`, `files.change_own` | Read, add or delete the Owner Files of the caller's account. |
| `files.read_any`, `files.change_any` | The same for every account. See open question 2. |
| `controls.read_own`, `controls.change_own` | Read, add, edit or delete the Controls of the caller's account. |
| `controls.read_any`, `controls.change_any` | The same for every account. See open question 2. |
| `settings.read` | Read the Deployment Settings and the diagnostic detail. |
| `settings.change` | Change a Deployment Setting. |

## 1. The identity and the owner ID (8 rows)

These rows are the places where a caller becomes an owner ID. A change here
changes every row in the later tables.

| Location | What it reads or writes | Owner it assumes now | What it must check with more than one account |
|---|---|---|---|
| `webapp/main.py:419` | Defines `OPERATOR = Identity.local(DEFAULT_CALLER)`. Each web app route names this identity. | The one local operator. | Remove the constant. Each route takes the caller's account from the session. |
| `src/katra/job_answers.py:1005` | `held_owner_id(identity)`: reads `store.principal(identity)` and returns its owner ID. The docstring calls it "the one read of a caller's owner ID". | The Principal of the identity. | Read the Account that the Principal links to, and return the account's owner ID and role. |
| `src/katra/job_answers.py:1014` | `owner_id(identity, job_id)`: raises `NoSuchJob` where the identity holds no Principal. | The Principal of the identity. | The same as the row above. A caller with no account gets the answer of a job that does not exist. |
| `src/katra/job_answers.py:1025` | `submitter(identity)`: makes a new Principal on the first submission. `admit` stores it with the job (`job_answers.py:1069`). | A new owner for each new identity. | The Account exists before the first job. See open question 9. |
| `src/katra/jobs.py:920` | `JobStore.principal(identity)`: returns a Principal with an owner ID. It holds no account and no role. | One owner ID for each Principal. | Return the linked Account, or add a separate account read. |
| `src/katra/sql_store.py:221` | The `principals` table. It holds issuer, `sub`, owner ID and creation time (ADR 0064). | One owner ID for each Principal. | An account table holds the owner ID and the role. A Principal links to an account (#2405, decision 4′). |
| `src/katra/api.py:568` | `require_identity`: verifies the token and refuses the reserved local issuer (`api.py:596`). | The token's Principal. | No new check. The Principal then resolves to an Account. |
| `webapp/main.py:994` | The web app's `JobAnswers` takes `ceiling=1`. `check_bounds` counts only the jobs of the record's owner (`src/katra/jobs.py:1287`). | One owner, so one job runs at a time in the install. | The ceiling then holds for each account. See open question 5. |

## 2. Web app routes (30 rows)

All routes are in `webapp/main.py`. Each write route checks `_cross_origin`
first (`webapp/main.py:1490`). No route checks a login.

| Location | What it reads or writes | Owner it assumes now | What it must check with more than one account | Candidate permission |
|---|---|---|---|---|
| `main.py:1717` `GET /` | Renders the form page. The framework picker lists every carried framework (`main.py:1742`). It shows the store note (`main.py:1756`). | No owner. It shows facts of the Deployment. | A session exists. The picker lists only the frameworks in the role's framework list (#2405, decision 9). | `work.create` |
| `main.py:1720` `GET /` with no Deployment | Serves the diagnostic page. It names the vendor and which required variables are set. `/files` and `/controls` serve it too. | No owner. | A session exists. Only a role that may read the Deployment Settings sees the detail. See open question 6. | `settings.read` |
| `main.py:1762` `GET /settings` | Reads `settings.env` and the process environment through `settings_view` (`webapp/settings_view.py:198`). It shows each Deployment Setting and whether each key file exists. | No owner. The values apply to the whole install. | The role holds the read permission. See open question 6. | `settings.read` |
| `main.py:1779` `POST /settings` | Writes `settings.env` and new key files (`webapp/settings_save.py:388`, `settings_save.py:242`), and swaps the cell. The log line names the keys and no actor (`main.py:1817`). | No owner. The operator changes the install. | The role holds the change permission. The service writes an audit record that names the account and the keys. A member never reaches this route. | `settings.change` |
| `main.py:1828` `POST /settings/rows` | Reads the process environment with unsaved changes applied. It writes nothing. | No owner. | The same as `GET /settings`. | `settings.read` |
| `main.py:1842` `GET /example` | Reads the sample description file. | No owner. | A session exists. | none |
| `main.py:1847` `GET /files` | Renders the Files page with the install's limits. | No owner. | A session exists. | `files.read_own` |
| `main.py:1877` `GET /workspace/files` | Reads `store.principal(OPERATOR)` (`main.py:1880`), then `owned_files`. | `OPERATOR`. | List the files of the caller's account. Another account's list needs `files.read_any` with an audit record. | `files.read_own` |
| `main.py:1884` `POST /workspace/files` | Reads `store.principal(OPERATOR)` and makes a new Principal where none exists (`main.py:1913`). `add_file` stores the file and the new Principal. | `OPERATOR`. The first upload creates the owner. | The file takes the owner ID of the caller's account. No upload creates an account. | `files.change_own` |
| `main.py:1939` `DELETE /workspace/files/{file_id}` | Reads `store.principal(OPERATOR)` (`main.py:1947`), then `delete_file(file_id, owner_id)`. | `OPERATOR`. | Owner, or `files.change_any` with an audit record. | `files.change_own` |
| `main.py:1954` `GET /controls` | Renders the Controls page with the install's limits. | No owner. | A session exists. | `controls.read_own` |
| `main.py:1977` `GET /workspace/controls` | Reads `store.principal(OPERATOR)` (`main.py:1981`), then `list_controls`. The form page reads this list too (`webapp/static/form_controls.js:180`). | `OPERATOR`. | List the Controls of the caller's account. Another account's list needs `controls.read_any` with an audit record. | `controls.read_own` |
| `main.py:2001` `POST /workspace/controls` | Reads `store.principal(OPERATOR)` and makes a new Principal where none exists (`main.py:2011`). `add_control` stores the Control and the new Principal. | `OPERATOR`. The first save creates the owner. | The Control takes the owner ID of the caller's account. No save creates an account. | `controls.change_own` |
| `main.py:2051` `PUT /workspace/controls/{control_id}` | Reads the Control under `OPERATOR` (`main.py:2063`), then `replace_control`. The new version keeps `stored.owner_id`. | `OPERATOR`. | Owner, or `controls.change_any` with an audit record. The new version keeps the owner of the stored Control. | `controls.change_own` |
| `main.py:2105` `DELETE /workspace/controls/{control_id}` | Reads `store.principal(OPERATOR)` (`main.py:2113`), then `delete_control`. | `OPERATOR`. | Owner, or `controls.change_any` with an audit record. | `controls.change_own` |
| `main.py:2120` `GET /workspace/controls/{id}/evidence/{evidence_id}` | Reads the Control and the evidence text under `OPERATOR` (`main.py:2130`). It returns the text as a file. | `OPERATOR`. | Owner, or `controls.read_any` with an audit record. | `controls.read_own` |
| `main.py:2155` `POST /workspace/controls/{control_id}/aliases` | Reads the Control under `OPERATOR` (`main.py:2174`), then `replace_control` with one more alias. The form page calls it (`form_controls.js:369`). | `OPERATOR`. | Owner, or `controls.change_any` with an audit record. | `controls.change_own` |
| `main.py:2217` `GET /workspace/runs` | `Workspace.snapshots` lists each job of `OPERATOR` (`main.py:600`). The form page fills its recent list and its "Reuse answers from" list from it. | `OPERATOR`. | List the jobs of the caller's account. An administrator sees the own list by default (#2405, decision 8). Another account's list needs `work.read_any` with an audit record. | `work.read_own` |
| `main.py:2222` `GET /workspace/runs/{run_id}` | `Workspace.owned` checks the job under `OPERATOR`. The route then reads the job that resumes it, its sources, its Controls and its questions under `record.owner_id`. | `OPERATOR` for the first check. The job's owner after it. | Owner, or `work.read_any` with an audit record. The later reads already use the job's owner. | `work.read_own` |
| `main.py:2307` `DELETE /workspace/runs/{run_id}` | `Workspace.analysis` (`main.py:2316`) finds the jobs of the analysis among the jobs of `OPERATOR`. Each delete goes through `audited_delete` with the cause `owner` (`main.py:2323`). | `OPERATOR`. | Owner, or `work.delete_any` with an audit record. The group comes from the jobs of the job's owner. The delete log names the account that deleted. See open question 7. | `work.delete_own` |
| `main.py:2339` `POST /workspace/runs/{run_id}/stop` | `Workspace.analysis` (`main.py:2347`), then `Workspace.stop`. | `OPERATOR`. | Owner, or `work.change_any` with an audit record. | `work.change_own` |
| `main.py:2355` `PUT /workspace/runs/{run_id}/title` | `Workspace.analysis` (`main.py:2372`), then `set_title` on each job. | `OPERATOR`. | Owner, or `work.change_any` with an audit record. | `work.change_own` |
| `main.py:2379` `POST /analyze` | `make_room` (`main.py:2411`) deletes the oldest jobs of `OPERATOR`. `answers.submit(OPERATOR, ...)` (`main.py:2412`) reads the named Owner Files, Controls and the earlier job of `answers_from` under `OPERATOR`. | `OPERATOR`. | The role holds `work.create`. Each selected framework is in the role's framework list. The new job, its Owner Files, its Controls and its earlier job all belong to the caller's account. | `work.create` |
| `main.py:2430` `POST /answer/{run_id}` | Reads the owner ID of `OPERATOR` (`main.py:2457`). `answers.answer` saves answers or a draft, or starts a Resumed Job under the parent's owner (`src/katra/job_answers.py:847`). `make_room` (`main.py:2462`) deletes jobs of `OPERATOR`. | `OPERATOR`. | Owner, or `work.change_any` with an audit record. See open question 3 for the owner of the new job. | `work.change_own` |
| `main.py:2481` `POST /amend/{run_id}` | Reads the owner ID of `OPERATOR` (`main.py:2496`). `answers.amend` starts a new job under the parent's owner (`job_answers.py:918`). `make_room` (`main.py:2497`) deletes jobs of `OPERATOR`. | `OPERATOR`. | Owner, or `work.change_any` with an audit record. See open question 3. | `work.change_own` |
| `main.py:2507` `GET /events/{run_id}` | `Workspace.envelope` checks the job under `OPERATOR` (`main.py:2517`). The stream then reads events by job ID alone (`main.py:2793`), and the questions under `record.owner_id`. | `OPERATOR` for the check. | Owner, or `work.read_any` with an audit record, before the first frame. | `work.read_own` |
| `main.py:2549` `GET /report/{run_id}` | `report_of` (`main.py:2533`) reads the report under `OPERATOR` (`main.py:2541`). It reads the parent job under `OPERATOR` (`main.py:2562`) and the parent's report under the job's owner (`main.py:2569`). The page shows the report changes from them (`main.py:1211`). | `OPERATOR`. | Owner, or `work.read_any` with an audit record. The parent read uses the job's owner, not the caller's. Now an administrator gets no report changes for another account's follow-up. | `work.read_own` |
| `main.py:2580` `GET /report/{run_id}/export.md` | `report_of`, then the Markdown export. | `OPERATOR`. | Owner, or `work.read_any` with an audit record. | `work.read_own` |
| `main.py:2598` `GET /report/{run_id}/export.json` | `report_of`, then the JSON export. | `OPERATOR`. | Owner, or `work.read_any` with an audit record. | `work.read_own` |
| `main.py:2614` `GET /report/{run_id}/export.csv` | `report_of`, then the CSV export. | `OPERATOR`. | Owner, or `work.read_any` with an audit record. | `work.read_own` |
| `main.py:2629` `POST /correct/{run_id}` | Reads the owner ID of `OPERATOR` (`main.py:2644`). `answers.correct` writes the corrections beside the report. | `OPERATOR`. | Owner, or `work.change_any` with an audit record. | `work.change_own` |

`_refusal_words` (`main.py:2719`) reads a job under `OPERATOR` (`main.py:2734`)
only for the label of a question in an error message. The `/answer` and
`/correct` routes call it, so it takes the owner of their check.

## 3. `/v1` routes that already take the owner from the Principal (11 rows)

These routes need no new owner logic. With accounts, `require_owner` returns
the owner ID of the linked Account, and the `work.*_any` path is the one
addition.

| Location | What it reads or writes | Owner it uses now | What it must check with more than one account | Candidate permission |
|---|---|---|---|---|
| `src/katra/api.py:600` `require_owner` | `JobAnswers.owner_id(identity, job_id)`. Each job route below depends on it. | The token's Principal. | Return the Account's owner ID. Add the `work.*_any` path here or in the one authorization module. | none |
| `api.py:922` `POST /v1/jobs` | `JobAnswers.submit(identity, ...)`. It passes no Owner Files and no Controls. | The token's Principal. | The role holds `work.create`. Each selected framework is in the role's framework list. | `work.create` |
| `api.py:951` `POST /v1/jobs/{job_id}/answers` | `JobAnswers.answer` under the owner. | The token's Principal. | Owner, or `work.change_any` with an audit record. | `work.change_own` |
| `api.py:985` `GET /v1/jobs/{job_id}` | `JobAnswers.owned`. | The token's Principal. | Owner, or `work.read_any` with an audit record. | `work.read_own` |
| `api.py:996` `DELETE /v1/jobs/{job_id}` | `audited_delete` with the cause `owner`. | The token's Principal. | Owner, or `work.delete_any` with an audit record. | `work.delete_own` |
| `api.py:1029` `GET /v1/jobs/{job_id}/report` | `_servable_report` (`api.py:501`) reads the report under the owner. | The token's Principal. | Owner, or `work.read_any` with an audit record. | `work.read_own` |
| `api.py:1035` `GET /v1/jobs/{job_id}/changes` | Reads the job, its resumption, the parent and both reports under one owner ID. | The token's Principal. | Owner, or `work.read_any` with an audit record. The parent read uses the job's owner. | `work.read_own` |
| `api.py:1081` `POST /v1/jobs/{job_id}/amendments` | `JobAnswers.amend` under the owner. | The token's Principal. | Owner, or `work.change_any` with an audit record. | `work.change_own` |
| `api.py:1107` `POST /v1/jobs/{job_id}/corrections` | `JobAnswers.correct` under the owner. | The token's Principal. | Owner, or `work.change_any` with an audit record. | `work.change_own` |
| `api.py:1136` `GET /v1/jobs/{job_id}/questions` | `JobAnswers.questions` under the owner. | The token's Principal. | Owner, or `work.read_any` with an audit record. | `work.read_own` |
| `api.py:1150` `GET /v1/jobs/{job_id}/events` | `JobAnswers.envelope`, then `event_frames` by job ID. It counts streams for each owner (`api.py:1156`). | The token's Principal. | Owner, or `work.read_any` with an audit record. Decide whose stream count an administrator's stream takes. | `work.read_own` |

## 4. Workspace and `JobAnswers` calls (17 rows)

`Workspace` is in `webapp/main.py`. `JobAnswers` is in
`src/katra/job_answers.py`.

| Location | What it reads or writes | Owner it assumes now | What it must check with more than one account |
|---|---|---|---|
| `main.py:571` `Workspace.owner_id` | `answers.owner_id(OPERATOR, job_id)`. `owned`, `envelope` and `parsable` (`main.py:577`, `584`, `592`) call it. | `OPERATOR`. | Take the caller's account. For the `work.*_any` path, take the owner of the job. |
| `main.py:600` `Workspace.jobs` | `held_owner_id(OPERATOR)`, then `store.owned_jobs`. | `OPERATOR`. | List the jobs of one named account. |
| `main.py:608` `Workspace.make_room` | Lists the jobs of `OPERATOR`. It deletes the oldest ended jobs past `MAX_RUNS` (`main.py:366`) with the cause `workspace` (`main.py:644`). | `OPERATOR`. | Delete only jobs of the account that the new job counts against. See open questions 3 and 4. |
| `main.py:648` `Workspace.parent_of` | `store.resumption(record.id, record.owner_id)`. | The job's owner. | No change. It already follows the job's owner. |
| `main.py:661` `Workspace.workspace_id` | `store.owned(parent, current.owner_id)` up the parent chain. | The job's owner. | No change. |
| `main.py:674` `Workspace.analysis` | `Workspace.owned`, then a filter of `Workspace.jobs` (the jobs of `OPERATOR`). | `OPERATOR`. | Filter the jobs of the job's owner, not the jobs of the caller. Else an administrator gets an empty group for another account's job. |
| `main.py:687` `Workspace.snapshots` and `main.py:703` `snapshot` | Group `Workspace.jobs` by analysis. `snapshot` reads the related jobs from `Workspace.jobs` too. | `OPERATOR`. | Group the jobs of the account that the list shows. |
| `job_answers.py:502` `JobAnswers.owned` | `store.owned(job_id, owner_id)`. Its docstring calls it "the one check of a requested job ID". | The owner ID that the caller passes. | A candidate seat for "owner, or the permission". #2405 puts that rule in one authorization module. |
| `job_answers.py:558` `JobAnswers.answerable` | Reads sources, Controls, checkpoint, `resumed_by`, report and resumption under one owner ID. | The owner ID that the caller passes. | Pass the job's owner after the authorization check. |
| `job_answers.py:627` `JobAnswers.submit` | Takes an identity. It reads Owner Files, Controls and the earlier job under that identity, then admits the job. | The identity's Principal. | Take the caller's account and its role's framework list. See open question 10. |
| `job_answers.py:698` `owner_file_sources` | `store.principal(identity)` (`job_answers.py:723`), then `file_text` for each named file. | The identity's Principal. | The files belong to the account that owns the new job. |
| `job_answers.py:741` `control_copies` | `store.principal(identity)` (`job_answers.py:757`), `list_controls`, then `read_evidence`. | The identity's Principal. | The Controls belong to the account that owns the new job. |
| `job_answers.py:935` `carried_from` | `parsable(job_id, owner_id)` (`job_answers.py:952`) for the earlier job of `answers_from`. | The submitter's owner. | The earlier job belongs to the account that owns the new job. |
| `job_answers.py:782` `JobAnswers.answer` | Saves answers or a draft under the owner, or starts a Resumed Job with `owner_id=owner_id` (`job_answers.py:847`). | The parent's owner. | See open question 3. |
| `job_answers.py:892` `JobAnswers.amend` | Starts an amended job with `owner_id=owner_id` (`job_answers.py:918`). | The parent's owner. | See open question 3. |
| `job_answers.py:958` `JobAnswers.correct` | `save_corrections` under the owner. | The parent's owner. | No new rule past the route's check. |
| `job_answers.py:1037` `JobAnswers.admit` | `store.reserve` checks the ceiling, the rate and the token budget for the record's owner. The refusal log names the owner ID (`job_answers.py:1073`). | The record's owner. | See open questions 3 and 5. |

## 5. Store calls (14 rows)

The protocol is `JobStore` in `src/katra/jobs.py`. Each owner-keyed read
answers `None` for the job of another owner, so an ID tells nothing about
another owner.

| Location | What it reads or writes | Owner it assumes now | What it must check with more than one account |
|---|---|---|---|
| `jobs.py:911` `reserve(record, principal=...)` | Inserts the job and, on a first submission, the Principal. | The record's owner. | Stop the Principal insert here if the Account exists first. See open question 9. |
| `jobs.py:922` `get(job_id)` | Reads the full record by ID alone. Only `execute_job` and `_store_outcome` call it (`jobs.py:2265`, `jobs.py:2175`). | No owner. | No route calls it. Keep it out of the routes. See open question 8. |
| `jobs.py:924` `owned(job_id, owner_id)` | Reads the envelope where the owner matches. | The owner ID that the caller passes. | The `work.*_any` path needs the job's owner ID first. See open question 8. |
| `jobs.py:935` to `jobs.py:952` `sources`, `controls`, `report_json`, `report`, `checkpoint`, `resumption`, `resumed_by` | Read one part of an owned job. | The owner ID that the caller passes. | Pass the job's owner after the authorization check. |
| `jobs.py:954` `events_after(job_id, seen)` | Reads events by job ID alone. `main.py:2793` and `api.py:1150` call it after an owner check. | No owner. | Keep the owner check before each call. |
| `jobs.py:958` `save(record)` | Writes a record by its ID. Only the run writes through it. | No owner. | No route calls it. |
| `jobs.py:969` to `jobs.py:1008` `save_answers`, `save_corrections`, `save_draft`, `set_title`, `set_continue_refusal` | Write one part of an owned job. | The owner ID that the caller passes. | Pass the job's owner after the authorization check. |
| `jobs.py:1016` `owned_jobs(owner_id)` | Lists the jobs of one owner. | The owner ID that the caller passes. | A list of another account's jobs needs `work.read_any`. |
| `jobs.py:1022` `delete(job_id, owner_id)` | Deletes an owned job and keeps its usage row. | The owner ID that the caller passes. | Pass the job's owner after the check. |
| `jobs.py:1061` `add_file(file, principal=...)` | Inserts an Owner File and, on a first upload, the Principal. | The file's owner. | Stop the Principal insert here if the Account exists first. |
| `jobs.py:1082` to `jobs.py:1097` `owned_files`, `file_text`, `delete_file` | Read or delete the Owner Files of one owner. | The owner ID that the caller passes. | Pass the file's owner after the check. |
| `jobs.py:1105` `add_control(control, principal=...)` | Inserts a Control and, on a first save, the Principal. It refuses a Control ID that the store holds for any owner. | The Control's owner. | Stop the Principal insert here if the Account exists first. |
| `jobs.py:1129` to `jobs.py:1168` `list_controls`, `get_control`, `replace_control`, `delete_control`, `read_evidence` | Read, replace or delete the Controls of one owner. `replace_control` takes the owner from `control.owner_id`. | The owner ID that the caller passes. | Pass the Control's owner after the check. |
| `jobs.py:1039` to `jobs.py:1057` `expired`, `sweep_orphans`, `fail_in_flight` | Read or change the jobs of every owner. | Every owner. The service acts. | No account check. Only background work calls them. |

## 6. Pages (12 rows)

| Location | What it shows or sends | Owner it assumes now | What it must check with more than one account |
|---|---|---|---|
| `webapp/sidebar.html:2` | Links to New analysis, Analyses, Files and Controls. | One operator. | Show a link only where the role holds its permission. |
| `webapp/sidebar.html:3` | Links to Settings. | One operator who changes the install. | Show the link only where the role holds `settings.read`. |
| `webapp/workspace.html:15` and `webapp/static/workspace.js:429` | The recent analyses: the first five jobs from `/workspace/runs`. | `OPERATOR`. | The caller's account's jobs. |
| `webapp/workspace.html:33` | The framework picker. `main.py:1742` fills it from every carried framework. | Every carried framework. | Only the frameworks in the role's framework list. |
| `webapp/workspace.html:37` and `workspace.js:436` | "Reuse answers from": every job from `/workspace/runs`. | `OPERATOR`. | Only jobs of the account that owns the new job. |
| `webapp/workspace.html:51` and `workspace.js:172` | The Analyses library, with delete, stop and rename (`workspace.js:104`, `118`, `140`). | `OPERATOR`. | The caller's account's jobs by default. Each action needs its permission. |
| `webapp/static/first_run.js:174` | The Owner Files on the form, from `/workspace/files`. | `OPERATOR`. | The caller's account's files. |
| `webapp/static/form_controls.js:180` | The Controls on the form, from `/workspace/controls`. | `OPERATOR`. | The caller's account's Controls. |
| `webapp/files.html` and `webapp/static/files.js:85` | The Files page: list, upload, delete (`files.js:157`, `191`). | `OPERATOR`. | The caller's account's files. |
| `webapp/controls.html` and `webapp/static/controls.js:781` | The Controls page: list, save, delete, evidence (`controls.js:597`, `859`, `490`). | `OPERATOR`. | The caller's account's Controls. |
| `webapp/settings.html` and `webapp/static/settings.js:545` | The Settings page and its save. | One operator who changes the install. | Show the save only where the role holds `settings.change`. |
| `webapp/report_view.html:497` and `webapp/static/report_view.js:1046`, `1146` | The report page: corrections, answers and draft, links to the parent and the Resumed Job (`report_view.js:1443`). | `OPERATOR`. | Show a write action only where the role holds `work.change_own` or `work.change_any`. Each link opens a job that the caller may read. |

## 7. Background work (7 rows)

| Location | What it reads or writes | Owner it assumes now | What it must check with more than one account |
|---|---|---|---|
| `main.py:466` `Workspace.start` and `main.py:483` `_run` | Runs an admitted job with `execute_job`, which reads the job by ID (`src/katra/jobs.py:2265`). | The job's owner. The service acts. | No account check. |
| `main.py:500` `Workspace._continue` | Continues a job at its pause under `record.owner_id` (`main.py:507`). It calls `make_room` (`main.py:506`), which deletes jobs of `OPERATOR`. It writes the refusal under the job's owner (`main.py:518`). | The job's owner, but `make_room` takes `OPERATOR`. | `make_room` takes the job's owner. |
| `main.py:557` `Workspace.stop` | Stops the runs of named job IDs in this process. | No owner. The caller passes owned IDs. | The route's check comes first. |
| `src/katra/store_backends.py:264` `expire_jobs` | Deletes each ended job past the retention period, for every owner, with the cause `retention`. | Every owner. | No account check. Retention is a Deployment Setting. |
| `store_backends.py:296` `remove_orphans` | Deletes each object that no job row names. | Every owner. | No account check. |
| `store_backends.py:359` restart scan | `fail_in_flight` fails each queued or running job at startup. | Every owner. | No account check. |
| `store_backends.py:193` `audited_delete` | Writes the one delete log line: job ID, owner ID, cause, count. `DeleteCause` is `owner`, `retention` or `workspace` (`store_backends.py:190`). | The job's owner. | Name the account that deleted where it is not the owner. See open question 7. |

## Out of scope

`webapp/review.py`, `webapp/sitting.py` and `webapp/offline_sitting.py` are
eval tools for the maintainer. They read the corpus and the vote ledger, not
the job store, and they bind to loopback. `src/katra/engine.py:375` keeps its
own Principals in memory and has no job store.

## Most important findings

1. **No web app route checks a login.** All 30 routes take the owner from the
   constant `OPERATOR`. Each route must take the caller's account.
2. **The workspace helpers list the caller's jobs, not the job owner's jobs.**
   `Workspace.analysis`, `snapshots` and `make_room` filter the jobs of
   `OPERATOR`. So an administrator's delete, stop or rename of another
   account's analysis finds an empty group. `make_room` deletes the oldest
   jobs of the caller, also when the new job belongs to another account.
3. **The report page reads the parent job under the caller.**
   `main.py:2562` reads the parent under `OPERATOR`. An administrator who
   reads another account's follow-up gets no report changes.
4. **The store cannot find the owner of a job ID.** Each owner-keyed read
   answers `None` for another owner, and `get` loads the whole record. The
   `work.*_any` path needs a read of the owner by job ID.
5. **A Deployment Setting write has no actor.** `POST /settings` checks only
   the page origin, and its log line names the keys and no account.

## Open questions for a later ticket

1. Does the web app session and the `/v1` token resolve to one account
   table in one store, so that a person's web work and API work share one
   owner ID?
2. Are Owner Files and Controls "work" under `work.read_any`, or do they take
   their own `files.*_any` and `controls.*_any` permissions? May an
   administrator download another account's evidence text?
3. An administrator answers, amends or corrects another account's job. The
   code gives the new job the parent's owner (`job_answers.py:847`, `918`).
   Whose ceiling, budget and workspace bound does that new job count against?
4. Is the workspace bound of 20 jobs (`main.py:366`) for each account or for
   the install?
5. The web app runs one job at a time in each owner (`main.py:994`). With
   more than one account, more than one job runs at the same time. Does the
   install need a ceiling across accounts too?
6. May a member read the Settings page and the diagnostic page? They show
   the vendor, the models and which key files exist, but no secret.
7. Does an administrator's delete get its own `DeleteCause`, or does the
   audit record name the account?
8. Which read gives the authorization module the owner of a job ID: a new
   store method, or `get`?
9. What creates an Account: the first login, or an administrator? Which role
   does a new account get, and how does an install get its first
   administrator? Today the first job, file or Control creates a Principal.
10. May an administrator submit a job that names another account's Owner
    Files, Controls or earlier job? Today `submit` reads them under the
    submitter's identity only.
11. A member answers an older job whose frameworks the role's list no longer
    holds. Does the answer start the Resumed Job?
12. Where does an audit record live: a store table, a log line, or both?
