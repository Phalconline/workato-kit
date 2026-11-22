# Data masking: what stays out of job history

Workato keeps the input and the output of every step of every job, and whoever may read job
history reads them. This page says which steps are masked so that a password, a token or a
stranger's personal data is not among them. It is the convention behind the rule **Sensitive data
stays out of job history** of [AGENTS.md](../../AGENTS.md).

## What Workato fixes

Documented: <https://docs.workato.com/features/data-masking.html> (data masking),
<https://docs.workato.com/security/data-protection/data-retention.html> (data retention) and
<https://docs.workato.com/recipes/jobs.html> (jobs).

| Topic | Fact | Page |
|---|---|---|
| Where | "Mask data" is a switch on one step. A trigger can be masked too. No setting covers a whole recipe, project or connection | data masking |
| What it hides | the input and the output of that step: Workato does not store or show them in job history | data masking |
| Audit log | masked input and output are left out of the activity audit log and of audit log streaming | data masking |
| Repeat a job | the trigger event is still stored, apart from job history, so that a job can be repeated | data masking |
| Jobs tab columns | a job report column cannot read a datapill of a masked step | jobs |
| Retention | job details are kept 30 or 90 days, by plan; a recipe can be set to store no job data at all | data retention |
| Plan | data masking is part of some pricing plans | data masking |

Observed, in the raw recipe JSON: a masked step carries `"mask_data": true` on its block. A mask
is a change to the recipe, so the recipe must be stopped for it (rule **A running recipe is
locked**).

Not in the documentation: whether a later step that is not masked shows a value it received from
a masked one, and who can still see masked data. The rule therefore masks **every** step a
credential passes through.

## What a mask does not cover

A mask hides one step in the job log. It does nothing about what that step sends somewhere else:

- a chat message, an e-mail, a logger step;
- the result a recipe function returns, which shows in the caller's job;
- the `message` of a `catch`. Not verified: whether it quotes the failed request; some APIs echo
  the request in an error body, so treat it as able to carry the credential. Send the error type
  or the HTTP status instead;
- a job report column;
- the trigger event Workato keeps to repeat the job.

## Two kinds of data

| Kind | Rule | Why |
|---|---|---|
| **Credentials**: a password, a passcode, a token, an API key, a client secret | always masked, in the step that creates or reads the value and in every step it is passed to. Never sent where a mask does not reach, unless a person receives it by design, such as a temporary password in an activation e-mail; the recipe doc names that case | a credential in job history works for anyone who can open the job |
| **Personal data of people outside the organization**: a customer, a lead, a website visitor (name, e-mail address, phone, IP address, text they typed) | masked by default. Left readable only when the recipe doc says why | these people never agreed to be read by everyone with access to job history. A written reason makes it a choice, not an accident |

Everything else stays readable unless the workspace decides otherwise: job history is what a
failed job is debugged with. A workspace that masks more, or that names data it keeps readable on
purpose, writes that into the last section of `AGENTS.md`, "Rules of this workspace".

## When it is done

- **A new recipe** gets its masks in the same push as its steps.
- **After an edit**, a new step that carries a credential is masked in the same task.
- **The recipe doc** lists the masked steps in its Configuration section, named by what they do
  and never by number. When a step with personal data of people outside the organization stays
  readable, the doc gives the reason.
- **A mask a person set stays.** Never remove one unless the request says so.
- **Job report columns** show ids and outcomes for a recipe with masked steps, because Workato
  blocks a column that reads a masked step ([job-view.md](job-view.md)).

Masking the trigger of a recipe hides what started each job, and the job report can no longer
show it. For a recipe that receives personal data in its trigger, weigh that against the reason
to keep it readable, and write the choice into the recipe doc.

## What the lint checks

`scripts/lint_recipes.py` reports `UNMASKED_CREDENTIAL`, a warning, for a step without "Mask
data" that carries a credential **by name**: an input field, a request header or parameter with a
value, a datapill, the output a code step declares, or a parameter of a recipe function, named
like a password, a passcode, a secret, an API key, an `Authorization` header or an access token.
It reads names and never a value.

What it cannot see:

- a credential under another name, such as the e-mail step that sends a formatted password;
- a bare `token`: list actions name their paging tokens that way, so it is not reported;
- personal data: no field name tells a customer's e-mail address from a colleague's.

A name such as `requirePassword` or `password_policy` is a setting, not a credential, and is not
reported. The lint finds candidates; whether a recipe is masked right stays a person's review.
