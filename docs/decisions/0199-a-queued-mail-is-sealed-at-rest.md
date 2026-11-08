# 0199 — A queued mail is sealed at rest

- **Status:** Proposed (awaiting review). Built in 0.36.1: the `mail.queued` sealing domain,
  the sealed `MAIL_SEND` payload and its reader of the plaintext form, `MailSealError`, and
  `terp secrets reseal` walking JSON columns. Held by
  `tests/architecture/test_mail_sealed_at_rest.py` and
  `tests/architecture/test_cli_reseal_json.py`, which runs on SQLite and on PostgreSQL, beside
  `test_mail.py` and `test_cli_reseal.py`.
- **Date:** 2026-11-04. 0182 and 0183 are reserved for other records, and 0184 to 0198 and
  0200 are taken.
- **Relates:** amends [ADR 0150](0150-mail-leaves-through-one-declared-relay.md) (the job's
  payload: the message is sealed, and the `Message-ID` rides beside it); extends
  [ADR 0189](0189-sealing-and-signing-retire-a-key-on-their-own-clocks.md) §5 (the re-seal
  walks JSON columns as well as string columns) and its table of the key's uses, and withdraws
  its consequence that a sealed value nested in a JSON document is not found; closes the
  exposure [ADR 0196](0196-a-person-can-open-prove-recover-and-close-their-own-account.md) §7
  recorded and left to a decision of its own; qualifies
  [ADR 0045](0045-durable-outbox.md) §1 ("its payload never changes": a re-seal changes the
  key a value inside it is sealed under, and nothing it says). Supersedes nothing.

---

## Context

`send_mail` never talks to a relay. It enqueues the `MAIL_SEND` job, and with the durable
outbox wired the job's payload is the JSON `payload` of an `outbox_message` row, committed with
the write the mail is about (ADR 0150). The payload was the message itself: its recipients,
its subject, its text and its `Reply-To`, in plaintext. The outbox is append-only, and nothing
purges a row once it is dispatched (ADR 0045). So every mail an app has sent rested in its
database, readable, for as long as the database and its backups exist.

Most of that is personal data. One part of it is a credential. A self-service mail (ADR 0196)
carries a link whose token works until it is redeemed or expires: an hour for a password reset
by default, up to a day, and a day for a sign-up, up to a week. A reader of the database inside
that window, a leaked backup or a reporting replica included, can redeem the token and take the
account over. ADR 0196 §7 recorded this and left it open, because closing it changes the mail
payload and what `terp secrets reseal` walks.

Everywhere else the platform's posture is that a secret at rest is sealed or digested: sealed
config, webhook signing secrets and TOTP enrolments are values of a `SealingDomain` (ADR 0189),
and an account token is stored only as its keyed digest. The queued mail was the exception.

Sealing it is not enough on its own. `terp secrets reseal` walks string columns. A sealed value
inside a JSON document is invisible to it, and ADR 0189 recorded that as a consequence. After a
rotation its `--check` would report a clean database while a queued mail still needed the old
key, and an operator who then retired the key would dead-letter that mail.

## Decision

### 1. The queued message is one sealed value of a domain of its own

The mail capability builds `SealingDomain("mail.queued", b"terp.mail.queued-message.v1")`. Like
every domain it seals under `SECRET_KEY` alone and opens under `SECRET_KEY`, then each
`SECRET_KEY_DECRYPT_FALLBACKS` entry (ADR 0189 §4), and its label is its own, so a queued mail
opens in no other domain and no other domain's value opens as a mail. It joins the table of
ADR 0189 §1:

| Use | Kind | Key | Through a rotation |
|---|---|---|---|
| Queued mail (`terp-cap-mail`) | encryption at rest | HKDF label `terp.mail.queued-message.v1` | decrypt-only, until re-sealed |

`send_mail` seals the whole message, its recipients, subject, text and `Reply-To`, as the JSON
of its `MailMessage`, into one value. The payload is then:

```json
{"message_id": "<5f0c…@example.test>", "sealed": "enc:v1:gAAAAA…"}
```

The `Message-ID` stays readable. It is the job's idempotency key, which the row's
`idempotency_key` column holds in any case, and it is the identity every retry reuses, so the
worker needs it before anything is opened. It is a random token at the sender's domain and
says nothing of the person.

The job opens the message when it delivers it, in the worker. The in-process queue runs the
same handler on the same payload, so in the inner loop the message is sealed at the send and
opened in the handler too, and the two queues differ only in when the handler runs.

`terp-cap-mail` gains `cryptography` as a direct dependency, as the mfa and webhooks
capabilities declare it. `SECRET_KEY` is in every Terp app's environment already.

### 2. A payload that no configured key opens is never sent

`MailJobPayload.message()` raises `MailSealError` (500, `mail_seal_unreadable`) when no key
opens the sealed value: one sealed under a key the environment no longer lists, a damaged one,
or one another domain sealed. Fernet authenticates a token under each key it tries, so none of
these opens, and nothing is ever sent from a payload that did not.

Raised inside the job, it fails the delivery like a relay that is down: the outbox retries it on
`MAIL_SEND`'s policy and dead-letters it once the eight attempts are spent, about an hour and a
half of backoff. The worker records the error in `last_error`, where `terp outbox dead-letters`
shows it, and the message names the remedy: list the key `SECRET_KEY` replaced in
`SECRET_KEY_DECRYPT_FALLBACKS` again, and the mail is sent at its next retry while it has
attempts left; then run `terp secrets reseal`, and drop the fallback only once it reports
nothing left. A mail that dead-lettered first stays dead-lettered, because the outbox has no
redrive (ADR 0045). Decision 4 is what keeps an operator from getting there.

### 3. The plaintext form is read through the 0.36 releases, and never written

A row that 0.36.0 or an earlier release queued holds the message's own fields, flat and in
plaintext, beside the `Message-ID`, and it must still deliver. So the payload model reads both
forms, and accepts exactly one of them: a validator refuses a payload that holds both or
neither, and that refusal never repeats what the payload held.

The plaintext form is never written. The payload serializes sealed whichever form it holds, and
the enqueue chokepoint serializes every payload, so a caller that skips `send_mail` and enqueues
`MAIL_SEND` with the message's fields, `terp jobs run mail.message.send` included, queues it
sealed.

The form matters only for a row still pending when a worker of this release first runs, and
such a row is delivered or dead-lettered within one retry budget: eight attempts, about an hour
and a half of backoff. The reader stays through the 0.36 releases and is removed in 0.37.0,
whose upgrade note asks a deployment coming from 0.36.0 or earlier to let `terp outbox backlog`
show nothing pending first.

**Amended in 0.39.0: the reader is removed now.** 0.37.0 and 0.38.0 shipped it with neither the
removal nor the note. From 0.39.0 the worker reads a mail sealed or not at all: a stored row in
the plaintext form fails its job with `MailPlaintextRetiredError` (`mail_plaintext_retired`),
which names the remedy, and retries and dead-letters with nothing sent. The plaintext form stays
an input: a caller that enqueues the message's fields, `terp jobs run mail.message.send`
included, still queues it sealed, since the payload is sealed when it is written. 0.39.0's
upgrade note carries the advice above.

Rows an earlier release already dispatched or dead-lettered are not rewritten. The worker never
reads them again and the re-seal moves sealed values only, so their recipients and text stay in
plaintext until the rows are removed. The tokens in them stop working once the longest link
lifetime has passed since the upgrade, a week at most.

### 4. `terp secrets reseal` walks JSON columns

The re-seal reads every JSON column of every table it reads, mapped or not, `JSONB` and a
reflected `json` included. A row is a candidate when the column's text form holds a string in
the sealed format (`CAST(column AS TEXT) LIKE '%"enc:v1:%'`), and its document is parsed and
walked: every string in the sealed format, a value or a key at any depth, is judged by
`check_sealed_value` exactly as a string column's value is, and tallied under its table and
column like any other. A queued mail is one line of the report, `outbox_message.payload`.

With a write, the values under a fallback are re-sealed in one compare-and-swap per document.
The update matches the document's text form as it was read (`CAST(column AS TEXT) = :read`),
because PostgreSQL's `json` type has no equality operator. A document any writer changed since
the read loses the swap, and every value that would have been re-sealed in it is counted as
changed, for the next run to judge. A document is written back through its column's own type
with only its sealed values replaced, every other key and value as it was read. A document that
does not parse, which SQLite's text storage allows, is counted as one value no key opens, so a
report is never clean while one is there.

Every other guarantee of ADR 0189 §5 holds as it was: one transaction per table; a
compare-and-swap per value, which for a document is per document; nothing else moves, so no
audit record, no `onupdate` column and no version counter; a table with no primary key, or one
the app does not map, read and counted and never written; and a refusal while a migration is
pending.

The re-seal judges a queued mail with the mail capability's domain, which is built when the
capability is imported. Loading the app imports it: an app that sends mail declares its relay
in the composition root with `configure_mail`.

### 5. A re-seal changes the key, never the meaning

ADR 0045 §1 and the outbox model say a row's payload never changes. A re-seal rewrites a sealed
value inside it: a new ciphertext of the same plaintext, under the current key. What the payload
says, the job, its `Message-ID` and its message, is what it said, and the row's status,
attempts, lease and stamps are not touched. A worker that claimed the row before the re-seal
holds the old value, which opens under the fallback the rotation keeps until the re-seal reports
nothing left. The outbox model's docstring now says this.

### 6. The sealed value's cap is derived

`sealed` caps its length at `MAX_SEALED_LENGTH`, 905,983 characters: Fernet's expansion of the
largest plaintext `MailMessage`'s own caps allow. The plaintext is `MAX_RECIPIENTS` addresses
and a `Reply-To` of `MAX_ADDRESS_LENGTH` each, a subject of `MAX_SUBJECT_LENGTH` and a text of
`MAX_TEXT_LENGTH`, every character at its widest in the JSON: six bytes, the `\u00XX` escape of a
control character, which no other character exceeds (UTF-8 takes at most four, a quote or a
backslash two, and the lone surrogate that has no UTF-8 is refused when the message is built).
The JSON around them is measured from the serializer, not counted by hand. A Fernet token is a
version byte, an eight-byte timestamp, a sixteen-byte IV, the PKCS7-padded ciphertext and a
32-byte HMAC, in base64url after the seven-character prefix.

`MAX_ADDRESS_LENGTH` (254) is now a named constant of the mail capability, read by
`parse_address`, by `Reply-To`'s field and by this derivation.

## Two-layer enforcement

- **Runtime, fail closed:** a payload serializes sealed whatever form it was given, so no path
  through the enqueue chokepoint writes the plaintext form; a payload that holds both forms or
  neither is refused when it is read, without repeating what it held; a payload no configured
  key opens raises `MailSealError`, is never sent, and retries and dead-letters; a sealed value
  longer than the derived cap is refused.
- **Tests:** with the outbox wired, the committed row's payload, read as the text its column
  holds, has neither an address, nor the subject, nor the text, nor the token of a self-service
  link in it, while the same probe finds the `Message-ID` there and finds the address in a
  plaintext row; the worker sends byte for byte
  the message that was queued, and a token that rested sealed still redeems; a row queued in the
  plaintext form delivers, and one enqueued in it is written sealed; a mail sealed under a key
  that is now only a decrypt fallback delivers; one under a retired key, a tampered one and one
  another domain sealed are never sent, carry the remedy in `last_error` and dead-letter, and
  listing the retired key again sends the mail at its next retry; the inline queue seals and
  opens the same way; Fernet's expansion is measured against the cipher at every block residue,
  no character takes more than six bytes, and the widest message there can be seals within the
  cap with a bounded slack. On SQLite and PostgreSQL: a queued mail is counted under the
  fallback, re-sealed with the rest of its row's document unmoved, and delivered once the
  fallback is gone; every sealed string in a document is judged at any depth and as a key, in
  a `jsonb` column too, and only those under a fallback are rewritten; a document changed
  between the read and the write is never overwritten; and a JSON column the app does not map is
  counted and never written. A document that does not parse is never reported clean.

No `terp.arch` rule is added: like ADR 0189, this is framework mechanics with no authored
pattern to police, and the spec catalog is unchanged.

## Consequences

- A reader of the database, or of a backup of it, finds no mail's recipients, text or link
  token in the payload of a row queued from this release on. Reading one takes `SECRET_KEY`,
  as every other sealed value does.
- A rotation reaches queued mail: `--check` counts it under the fallback, and the re-seal moves
  it. A queued mail now depends on the key it was sealed under, so retiring that key too early
  fails the mail, loudly: it carries the remedy in `last_error`, retries, and dead-letters where
  an operator looks. The re-seal's count is what keeps it from happening.
- A sealed message is about four thirds of its JSON in length, plus about a hundred characters.
- `MAIL_SEND` stays `RESTRICTED`: its payload is a person's message, sealed or not.
- The token inside a sealed mail is itself a sealed value of the users capability, and the
  re-seal cannot see it. A link mailed before a rotation therefore opens only while the old key
  is in `SECRET_KEY_DECRYPT_FALLBACKS`, as it did before this record: dropping the fallback
  sooner than the longest link lifetime voids the links still out, whatever the re-seal
  reports.

## Open

- **How long the outbox keeps a dispatched row.** Nothing purges one, so a mail's sealed
  message stays as long as the database does, and a row an earlier release dispatched keeps its
  plaintext (decision 3). A retention period for dispatched rows is a decision of its own.
- **Removing the plaintext reader** in 0.37.0 is proposed here; the release that removes it
  carries the upgrade note decision 3 describes.
