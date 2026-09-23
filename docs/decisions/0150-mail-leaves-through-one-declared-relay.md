# 0150 — Mail leaves through one declared relay

- **Status:** Accepted and implemented. `terp-cap-mail` (`terp.capabilities.mail`) ships,
  and `no_raw_outbound_http` refuses `smtplib` and sends the author to it. Held by
  `tests/architecture/test_mail.py` and `tests/architecture/test_arch_harness.py`.
- **Date:** 2026-09-23
- **Relates:** [ADR 0117](0117-the-egress-capability-the-rule-was-already-naming.md) (the
  capability this one is the sibling of, for a different protocol),
  [ADR 0096](0096-typed-seams-cover-the-common-case.md) (a checked seam that does not cover
  the common case is a hole),
  [ADR 0043](0043-jobs-seam-and-typed-enqueue.md) and
  [ADR 0045](0045-durable-outbox.md) (the jobs seam and the durable outbox a send rides),
  [ADR 0128](0128-the-gate-asks-whether-the-app-would-boot-in-production.md) (the
  environment-independent production check both refusals use),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern,
  enforced, escapable by declaration),
  [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md) (why the
  rule change here is a correction of an existing rule and not a new one)

---

## Context

Sending mail is among the first things a business application is asked to do: tell a
customer an order shipped, tell a planner a work order was closed, confirm that an
account exists. The platform had no way to do it, and said so in its own product
material.

That is the smaller half of the problem. The larger half is what an agent does when it is
asked for the feature anyway. `no_raw_outbound_http` refuses `httpx`, `requests`,
`urllib3`, `aiohttp`, `socket`, `urllib.request` and `http.client` — every route to the
network an HTTP call takes — and it did not refuse `smtplib`. So the shape an agent
reaches for first, the standard library's own mail client, passed the gate, and with it
every decision the rule exists to take away from a call site: whether the session is
encrypted, whether the relay's certificate is checked, whether a password crosses the
network in the clear, how long an unresponsive server may hold the caller. `smtplib` gets
every one of them wrong unless its author knows better: the session is unencrypted until
`starttls()` is called, and even then its default context verifies neither the
certificate nor the name; `login()` sends the password in the clear to any server that
advertises AUTH; and there is no timeout at all. Nothing in the tree would have said so.

There is also a correctness trap that is not about security at all. A mail sent from a
request handler does not agree with the write it is about. If the relay is slow, the
request is slow; if it is down, the request fails; and if the mail goes out and the write
then rolls back, a customer has been told about a change that does not exist.

## Decision

**Ship `terp-cap-mail`, and extend `no_raw_outbound_http` to refuse `smtplib` with a
remedy that names it.**

A **library** capability, like `terp-cap-egress`: no router, no table, no auto-discovery
entry point. An application declares its relay in the composition root and registers one
job; a feature calls one function.

```python
configure_mail(mail_settings_from_environment(os.environ))   # app/main.py
job_catalog = JobCatalog([MAIL_SEND])                         # control_plane/jobs.py
send_mail(session, MailMessage(to=[...], subject="...", text="..."))   # in a write
```

### The relay is a declaration

`MailSettings` holds the sender, the relay host and port, how the session is protected and
the account, and reads them from fixed environment variables (`MAIL_FROM`, `SMTP_HOST`,
`SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD`) so every application
configures mail the same way and a deployment tool can name them without reading code.

- **Encrypted by default.** STARTTLS on the submission port, or TLS from the first byte.
  A relay that does not offer STARTTLS is refused — never spoken to in the clear —
  because stripping that one capability line is the entire downgrade attack.
- **Verified, with no switch.** The client context is the standard library's default with
  TLS 1.2 as the floor: certificate and hostname checked. There is no parameter that
  turns verification off, because the call site is where it would be turned off.
- **Credentials only inside the encrypted session**, refused at construction otherwise in
  every environment — not only in production.
- **An unencrypted relay** (`SMTP_SECURITY=none`) exists for the mail catcher a
  development stack runs on its own network, and a production boot refuses it.
- **No relay at all** refuses a production boot; anywhere else it installs a stand-in that
  delivers nothing and logs every message it did not deliver — its subject and recipient
  count, never the address or the body, since development databases are often copies.

Both refusals are decided by `production_problems()`-shaped predicates that do not depend
on the environment they run in (ADR 0128).

### The message is data, validated when it is asked for

`MailMessage` carries recipients, a subject, a plain-text body and an optional
`Reply-To`. The classic failures of mail built from data are header failures, and each is
refused at construction, where the refusal reaches the code that made the mistake:

- a CR, LF or other control character in the subject, or anywhere in an address — the
  header injection that turns a notification into a bulk mail;
- a second address smuggled into one (`a@example.com, b@example.com`), an IP-literal
  domain that skips the recipient's own mail routing, a domain with no dot;
- more than `MAX_RECIPIENTS` recipients. A message to many visible people hands each of
  them everybody's address; the same notice to many people is one send per person.

**There is no per-message sender.** Every message is from `MAIL_FROM`. What a per-message
sender is usually wanted for — a person's reply landing with the right colleague — is
`Reply-To`, and it does not let a feature send mail that claims to come from someone
else. `Auto-Submitted: auto-generated` (RFC 3834) is always set, so an out-of-office
reply does not start a loop.

### A send is a job, so it commits with its write

`send_mail` never talks to a relay. It validates, mints the `Message-ID`, and enqueues the
typed `MAIL_SEND` job on the caller's session. Called from a service's `_after_write`, with
the durable outbox wired, the mail is a row in the same transaction as the business write:
it commits with it or rolls back with it, and `terp jobs worker` delivers it afterwards. A
failed delivery raises, so the outbox retries with backoff and finally dead-letters — where
`terp outbox backlog` already shows an operator work that did not happen. The
`Message-ID` rides the payload, so every retry is recognisably the same message.

With the in-process default queue the job runs inline, and a failing relay fails the
request. That is the loud version of the same failure, in the environment where loud is
wanted, and it needs no worker to try the feature out.

Two relay behaviours are deliberately not failures: a relay that accepted the message for
some recipients and refused others (a retry would send everyone it accepted a second
copy), and a session that ends badly after the message was accepted (the `QUIT` says
nothing about delivery).

### The rule

`smtplib` joins the modules `no_raw_outbound_http` refuses, with its own remedy text
pointing at `terp.capabilities.mail` rather than at `EgressClient`, which cannot speak
SMTP. The capability's own import is the one budgeted opt-out, as `egress` holds for
`httpx`.

This is a correction of an existing rule under ADR 0122 §1, not a new rule. The rule's
own intent is that outbound traffic belongs behind a declared capability; `socket` was
already on its list, so the rule was never only about HTTP. What was missing was the
mail client — and the reason it could not be added before is ADR 0096's: a refusal with
no compliant path is a hole code goes around. It is added now because the path exists.

## Deliberately not in it

- **The SSRF denylist.** Egress applies it because an outbound URL can be *steered* —
  built from data a caller influences. The mail relay cannot be: it is the one host the
  deployment configured, and a recipient decides where a mail ends up, never which server
  this process connects to. What protects the relay is the encrypted session and the
  certificate that proves its name, which is also why an on-premises relay or a
  development catcher on a private network needs no exception.
- **HTML bodies.** An HTML body assembled from data is a second injection surface — a link
  or a form placed in a trusted sender's mail — and it is safe to offer only with an
  auto-escaping renderer the capability does not have. It arrives with a consumer and that
  renderer, not before.
- **Attachments, CC and BCC.** No named consumer; each is a field with no reader today.
  An attachment in particular belongs to the files capability's authorization, not to a
  byte array in a job payload.
- **A delivery log table.** Nothing reads one, and a table of recipient addresses is
  personal data at rest that needs a retention answer before it exists. The outbox row
  already records pending, delivered and dead-lettered.
- **A template toggle.** Mail needs a relay per environment and a worker to be durable,
  which is wiring an application decides — the same line the template already draws for
  webhooks and background jobs. `terp inspect capabilities` and `terp guide mail` are the
  path.

## Consequences

- An application can send mail, and the only way it can is encrypted, verified, from a
  fixed sender, and transactional with the write that caused it.
- **`import smtplib` is now refused everywhere the rule scans**, including a worker or a
  script outside `modules/` (ADR 0136). An application that already sends mail with it
  fails the gate on upgrade; the remedy text names the capability and `terp guide mail`
  gives the wiring. An application whose provider is reachable only through its HTTP API
  keeps the same call sites: `configure_mail(settings, transport=...)` accepts a transport
  built on `terp.capabilities.egress`, declared in the composition root.
- A job catalog that carries `MAIL_SEND` needs `ControlPlane(job_system_actor_id=...)` in
  production, like any other job catalog (ADR 0125).
- `terp-spec`'s entry for `backend/no_raw_outbound_http` lists the refused modules in its
  `reference` text and gains a corpus case for `smtplib`; until that spec release is
  adopted, the framework runs ahead of the published entry, which ADR 0116 permits.
- The new distribution needs its PyPI project registered before the first tag that
  carries it (`docs/RELEASING.md`).
