# 0171 — The admin hub is a dashboard of the administration

- **Status:** Accepted and implemented. The activity read is `GET /api/v1/audit/activity`
  (`audit.read_activity`) in `terp-cap-audit`; the status filter is `UsersService.filterable`;
  the hub is `AdminHub` in react-core. Held by `tests/architecture/test_audit_activity.py` (on
  SQLite and PostgreSQL), the example app's `test_audit_api.py` and `test_users_api.py`,
  `admin.test.tsx`, and the workbench's `admin-hub` specimen and computed lane.
- **Date:** 2026-10-04
- **Relates:** [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md) (the dashboard
  archetype, and which screen draws the charts first, left open by its second amendment),
  [ADR 0158](0158-a-quantity-is-shown-one-way.md) (the chart contract),
  [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) (the trail being counted),
  [ADR 0069](0069-verified-database-dialects-and-schema-direction.md) (why a count must read the same on both databases)

---

## Context

ADR 0169 built the charts and left open which packaged screen would draw them first. The owner
chose the admin hub. It was a `HubPage` of four cards, two of which printed a total read from a
one-row page.

Nothing could feed a dashboard. The audit trail had one endpoint, a paginated list, and
counting a page in the browser counts the page, not the trail. The users list could not be
narrowed by status, so "active accounts" had no total either. And no query anywhere grouped
anything by day, on either database.

A proposal put three rendered directions and two data decisions in front of the owner, who took
the recommendation on all three.

## Decision

### 1. The hub is a `DashboardPage`, areas first

The summary band carries the figures:

- the active accounts, as the headline, with the deactivated ones under them;
- the groups;
- the trail's last seven days, with the change against the seven before and a sparkline.

The area cards follow, because getting to an area is still the hub's first job and they stay in
the first screen on a laptop. Then the trail per day for thirty days, drawn against the thirty
before, and the kinds of change as a proportion bar, in the words and tones a record's own
history uses.

The app's area selection still applies. A dropped section loses its card, its figure, its reads
and, for the audit log, its charts.

Of the two directions not taken, one put the activity first and pushed the cards to the foot of
the screen. The other put each figure in the card it belongs to, which gives up the dashboard's
band of figures under the title.

### 2. The trail is counted by the viewer's own calendar days

`GET /api/v1/audit/activity?days=30&time_zone=Europe/Amsterdam` returns:

- the last `days` calendar days of that zone, oldest first and ending today, with a zero for an
  empty day;
- as many days before them, for a comparison;
- the counts per kind of change and per type of record (the eight most changed types) over the
  last `days`, and their total.

It is admin-only, like the list.

A day is the zone's own day. The server makes each local midnight in the zone, converts it to
UTC, and counts every day at once in one query: one conditional aggregate per day, over the
window's index range, comparing the timestamp only with bound instants. That reads the same on
SQLite, where the column holds UTC wall time, and on PostgreSQL. A day that daylight saving
makes 23 or 25 hours long keeps its length.

The days are not grouped. Grouping by an expression that carries bound parameters is refused by
PostgreSQL once the parameters are bound on the server, because the select list and the
grouping no longer read as one expression.

The window is at most 90 days. The zone is an IANA name, refused by its shape (422) before the
zone database is asked, and by the database (400) when it is unknown. `terp-cap-audit` now
depends on `tzdata`, because Windows has no zone database and a name must resolve the same on
every host.

**Alternatives considered:**

- **UTC days,** grouped by `date(created_at)`. Simpler, but a change at 01:30 in Amsterdam would
  count on the day before. On PostgreSQL the day would also follow the session's time zone,
  which nothing in Terp pins.
- **A daily rollup table,** kept up to date on every audited write. The cheapest read, but it
  adds a second write to every audited transaction and a table to keep in step with an
  append-only trail.

### 3. Active accounts are a total under a declared filter

The users list declares `is_active` and `email` as its filters, the fail-closed mechanism every
service has. The hub reads two totals, all accounts and the active ones, the way it read the
users total before.

Moving the email search onto the declared filter made it a literal match. An `_` or a `%` in the
text used to reach `LIKE` unescaped, where both are wildcards.

### 4. A list of cards without figures keeps no figure row

A hub card reserved a row for a figure, and the card had a 10rem floor, so that a bare card
would stay flush with a full one beside it. Under the band's figures every area card is bare,
and each ended in blank space. Where no card in a list carries a figure, the row and the floor
go. A bare card beside a full one keeps both.

## Consequences

- The hub makes four reads, each on its own, so one that fails leaves the others standing; its
  figures keep their dash until they arrive.
- An app's own framework catalog adds eight strings. `adminHubTotal` stays in the catalog
  although the hub no longer reads it: a catalog with a framework string the framework does not
  know is refused, so removing it would refuse every catalog written for 0.31.0.
- The activity read counts only what the trail records. A sign-in writes no audit row of its
  own (a first single-sign-on visit records the account it creates), so the hub says nothing
  about logins.
- A ranking of who changed the most, and a timeline of the latest changes, are left out. The
  trail stores an actor's id and a record's id, not their names, so both would show ids.
