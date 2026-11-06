# 0204 — A statistic is declared on the service, like a filter

- **Status:** Accepted on 2026-11-06 by the owner, who answered the three review questions as
  recommended (decision 5, decision 6, the zone database). Built in 0.37.0 (unreleased). An
  independent review of the proposed record before the build found that it leaked personal data
  through filters, missed Core reads and froze a context-dependent answer in a cache. It also
  found claims the code did not support. Each finding is either fixed below or recorded as an
  open gap with its follow-up (see *What the review changed*).
- **Date:** 2026-11-06.
- **Relates:** [ADR 0017](0017-non-overridable-scope-predicate-and-registry.md) (the row scope
  every read composes, and the `reads_use_base_query` rule that warns about a read that skips
  it), [ADR 0171](0171-the-admin-hub-is-a-dashboard-of-the-administration.md) (the one
  framework-owned aggregate, hand-written in `terp-cap-audit`, which this seam replaces),
  [ADR 0190](0190-a-field-declares-itself-personal.md) (personal data, which a statistic must
  not hand back one person at a time), [ADR 0203](0203-the-rules-belong-to-the-framework-and-only-the-contracts-are-neutral.md)
  (the rules move into this framework, which decides where this record's catalog corrections
  land), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) and
  [ADR 0084](0084-runtime-applicability-classification.md) (the two layers, and the
  classification that records them), the platform-reach open items (R6).

## Decision

A service declares what may be counted and summed, and by what, the way it already declares
what may be filtered and sorted: `measures`, `dimensions` and `time_buckets` beside
`filterable` and `sortable`. `BaseService.aggregate` composes the request on `base_query()` as a
subquery and answers with one page of groups. Each group is one combination of the requested
dimensions, with its figures and, for a window with a step, its series over the calendar days,
weeks or months of a time zone, empty steps counting zero. A route takes a capped
`StatisticsQueryDep` and returns `Page[Service.statistics_model()]`, a response typed by the
declarations.

Everything undeclared is refused, as an undeclared filter is. The page, the series and the two
together are each capped, and refused rather than clamped. Personal data never leaves one person
at a time:
- a grouping, a time bucket, or a `sum`, `avg`, `min` or `max` over a field declared personal is
  refused when the class is defined;
- a statistic is never narrowed by a filter over a personal field.

The audit capability's activity read is the first consumer.

The runtime half was mostly there, and this record says so. Since 0.36.0 the request session
scopes every ORM read, aggregates included. What it could not scope is a SELECT that reads a
scoped table through Core, and that is now refused at execution.

## Context

A statistics screen counts and sums over the same tables its lists read: invoices per month,
open cases per status, revenue per region. A list has a sanctioned path. A statistic had none.

What a module writes is the natural spelling,
`select(Invoice.status, func.count()).group_by(Invoice.status)`. On a model with a soft-delete
or tenant trait, `reads_use_base_query` flags it, because the rule walks the whole `select(...)`
chain and cannot know whether the scope survived. The remedy it named, "build on
`base_query()`", had no aggregate form. The way to satisfy it was
`select(func.count(q.c.status)).select_from(q)` over `q = self.base_query().subquery()`, which
is what `BaseService._paginate` does for its own total. That is scoped and it passes the rule.
But every column becomes a string lookup on `q.c`, nothing types the result, and every module
writing it rediscovers three things on its own:

- **Time buckets are hard to get right.** ADR 0171 records it: a calendar day is the viewer's
  day, not UTC's, and a day that daylight saving shortens keeps its real length.
- **A grouping has no bound.** Grouping by a column with ten thousand values returns ten
  thousand rows. Every list endpoint paginates; a hand-written statistic does not, and nothing
  asks it to.
- **A statistic can undo the personal-data declaration.** Counting invoices *per email address*
  hands back a value per person, the thing ADR 0190 keeps out of the log, the audit trail and
  events. So does a `sum` over a group of one, and so does a count filtered by an address, one
  character at a time.

**The runtime gap is smaller than the open items say.** They were written on 0.34.0, when the
session guard re-scoped only a single-entity `select(model)`. 0.36.0 replaced that with an ORM
execution hook that applies the row scope as loader criteria to every mapped entity a statement
reaches, in its columns, joins, predicates and nested selects. Measured on 0.36.1 against a
soft-deleted row, on SQLite and on PostgreSQL, all of these exclude it:
- a `sum`;
- a `count(Model.id)`;
- `count().select_from(Model)`;
- a `group_by`;
- a count joined through a scoped child;
- an aggregate over a subquery or a CTE of the entity;
- an ORM alias.

What still read it was a SELECT that reaches the table through Core: a column of
`Model.__table__`, `select_from(Model.__table__)`, a Core join or scalar subquery over it, a Core
alias, `table("name")`, literal SQL in a FROM, and the secondary table of a many-to-many. A
many-to-many through a soft-deletable link table still showed a row whose only link was deleted.

## Decisions

### 1. Three declarations, beside `filterable` and `sortable`

```python
class InvoiceService(BaseService[Invoice, InvoiceCreate, InvoiceUpdate]):
    model = Invoice
    filterable = (FilterField("customer_id", Invoice.customer_id),)
    measures = (Measure("invoices"), Measure("revenue", Invoice.amount, op="sum"))
    dimensions = (Dimension("status", Invoice.status),)
    time_buckets = (TimeBucket("issued", Invoice.issued_at, steps=("day", "week", "month")),)
```

- `Measure(name, column=None, op=...)`: `op` is one of `count`, `count_distinct`, `sum`, `avg`,
  `min` and `max`, fixed by the declaration and never sent by a caller. `count` alone takes no
  column.
- `Dimension(name, column)` groups by a column's own values. No expressions: a dimension that
  needs one is a column the model declares, or a database view read through R11.
- `TimeBucket(name, column, steps, max_buckets=366)` windows rows by a timestamp and steps
  through it by calendar.

They live in `terp.core.aggregation`, as filters live in `terp.core.filtering`. A read that is
not a service's (a capability's own table) uses the same seam directly,
`aggregate(session, query, Statistics(...), ...)`, which is how the audit trail uses it.

### 2. Composed on `base_query()` as a subquery, grouped by plain columns

Row scope, soft delete, `business_filters` and the declared filters apply first, inside the
subquery, so an aggregate cannot drop them, as a list cannot. A series joins each row to a small
table of the window's steps, `(i, lo, hi)`, built as a `UNION ALL` of bound instants. The
grouping happens outside, by plain columns.

The review measured three ways to place a row in its step:

| Form | PostgreSQL, 1M rows | SQLite, 200k rows |
|---|---|---|
| A `CASE` with one `WHEN` per step (the proposed record) | 2.1 s | 3.9 s |
| A balanced `CASE` tree (the first build) | 0.59 s | 0.16 s |
| A join to a steps table (built) | 0.125 s | 0.054 s |

Each step's boundary is a local midnight made in the zone and then converted, ADR 0171's rule,
so a short day keeps its length. The review checked every zone through 2026, and each keeps its
real day lengths.

The proposed record also said PostgreSQL refuses a `GROUP BY` over an expression with bound
parameters. That is imprecise. PostgreSQL refuses an expression *built twice*, and one labelled
object groups fine. Grouping by plain columns avoids the question either way.

### 3. The answer is a page of groups, typed by the declarations

```json
{
  "items": [
    {
      "dimensions": {"status": "paid"},
      "measures": {"invoices": 41, "revenue": "18250.00"},
      "series": [{"start": "2026-09-01T00:00:00+02:00", "date": "2026-09-01",
                  "measures": {"invoices": 12, "revenue": "5100.00"}}]
    }
  ],
  "total": 3, "skip": 0, "limit": 20
}
```

There is one item per dimension combination, never one per combination and step. Paging a long
format would cut a chart's line in two. A request with no dimension gets one item, the whole
scope. A request with no step gets `series: null`. `total` counts the groups, so a screen that
asks for the top eight still knows how many there are. That is the audit read's "eight most
changed record types" with nothing special about it.

- **The wire shape is typed.** `Service.statistics_model()` builds the group's model from the
  declarations, once per class: one field per dimension and per measure, each typed by its
  column and its aggregate. A figure the request did not ask for is `null`. So the API contract
  and the generated client know each figure, instead of every service sharing one map of
  unions. `AggregateGroup`, the value `aggregate` returns, stays the untyped carrier.
- **Decimals travel as strings.** A `sum` over a `Numeric` column is a `Decimal`, and JSON
  carries it as a string, so money keeps its cents.
- **A step carries its local `date`.** On the days a zone skips its midnight, `start` reads
  01:00. A client that re-zones `start` can also move it to the previous day, so a label reads
  `date`.
- **The figures can come from different snapshots.** A page takes up to three statements: the
  group count, the page, and its series. Under READ COMMITTED each reads its own snapshot. A
  write between them can make the total and the page disagree by that write. The two never
  disagree on scope.

### 4. Every list, string and figure is capped, and refused rather than clamped

- `StatisticsQueryDep` is a statistics route's query, capped like `PaginationDep`:
  - at most 16 measures, 8 dimensions and 8 sort keys;
  - each name lower snake case and at most 64 characters;
  - a zone of at most 64 characters.

  A window needs its bucket and both dates, and a date given without a bucket is refused.
- A page holds at most the service's `max_groups` (100). A series longer than the bucket's
  `max_buckets` (366) is refused before the query runs, naming a longer step.
- A page's groups times steps must stay within `max_points` (10,000). A hundred groups of a
  year's days would be 36,600 points, megabytes no screen draws.

The open items asked how to bound cardinality: a sampled estimate, a `LIMIT` probe that fails on
overflow, or a declared cap. Paging answers it without an estimate. The groups page like rows,
the count is exact, and only the window, which is the caller's to choose, needs a refusal.

### 5. A statistic never answers for one person's personal data

The owner chose the strongest form, with no opt-out marker. Refused when the class is defined,
with the `TypeError` an inert declaration already raises:
- a `Dimension` over a field declared with `Personal(...)`;
- a `TimeBucket` over such a field, since a bucket of one dates that person;
- a `sum`, `avg`, `min` or `max` over such a field, since over a group of one each is that
  person's value.

`count` and `count_distinct` over a personal field stay allowed: a count of distinct addresses
discloses none of them.

A statistic is also never narrowed by a filter over a personal field. The review showed why: the
users list declares `email` as a `contains` filter, and counts under it recover an address one
character at a time. Such a filter is refused at the request, with a 400. An absent value is no
filter, so a route may still forward the list's filters unbranched. The list keeps its filter.

This guards fields *declared* personal, not every breakdown by person. A dimension over
`customer_id` is a per-customer figure, and whether that is a statistic or a list is the
service's call.

A minimum group size, so that a group of one cannot be read off a narrowed count, is **not**
decided here. It is a real threat for a small population, and it is a policy with a number in
it. It needs its own record when an application asks for it.

### 6. The runtime refuses every SELECT it cannot scope

The ORM execution hook stays, and tests now pin each aggregate shape it scopes, for soft-delete,
tenant and owner scope, on both dialects. Beside it, the same hook refuses a SELECT that reads a
row-scoped table through Core. The rule is judged **per SELECT**, nested ones included:
- **Named:** a scoped table in a SELECT's FROM list must be named by a mapped entity in that
  same SELECT, which is what the loader criteria attach to. A mapped entity elsewhere in the
  statement does not count: a parent's relationship to a child reaches the child's mapper
  without covering a Core join to the child's table.
- **Aliases:** an ORM alias counts when it is named in that SELECT. A Core alias never does.
- **Literal SQL:** a FROM written as literal SQL is refused outright, since nothing can scope
  it.
- **Many-to-many:** one whose secondary table is row-scoped is refused when it loads. Map the
  link as an association object instead.

The refusal is `UnscopedReadError`, a programming error surfacing as a 500 whose log line names
the model and the remedy. Whether a table carries row scope is asked at the moment the read
reaches it, in that read's context. An owner scope with no actor is no scope, and the first read
of the process does not decide for the next. The table-to-model lookup is static and rebuilt only
when a mapper is constructed. A bare `Session`, used for a migration, the CLI or a test, is left
alone. A Core read of a table with no row scope is allowed.

The audit the owner asked for ran the framework's whole suite with the refusal on. No framework
code path reads a row-scoped table through Core on a request session.

## What does not change

- `filterable`, `sortable` and `list` are untouched. A statistic reuses `filterable`, minus its
  personal fields.
- There is no query language and no pivot builder. The open items refused them, with a database
  view and a read-only model as the answer for a report the declarations cannot express.
- There are no rollup tables. ADR 0171 weighed one for the audit trail and declined it, and
  nothing here changes that weighing.
- No new catalog rule is added. `reads_use_base_query` keeps flagging a hand-built aggregate
  over a scope-trait model, and its remedy names the seam.
  - The rule's catalog prose said the session re-scopes single-entity reads. It is corrected in
    terp-spec 0.43.0, the last release before ADR 0203 moves the catalog here.
  - The rest of the catalog's corrections move with the rules: the runtime `ref` naming this
    hook, and the build-time gaps below.

## Two-layer enforcement

| | Build time | Runtime |
|---|---|---|
| A hand-built aggregate drops the row scope | `reads_use_base_query`, for models that list `SoftDeleteMixin` or `TenantScopedMixin` directly | the ORM execution hook scopes it |
| A SELECT reads a scoped table through Core | the same rule, where the source names such a model | `UnscopedReadError`, for every row scope, in the read's context |
| A caller groups, counts or filters by something undeclared | none needed: the names are data | `ValidationFailedError` at resolution, before the query |
| A statistic answers for one person | `personal_fields_are_declared` makes sure the field is marked `Personal(...)` | `TypeError` at class definition; a personal filter refused at the request |
| A statistic grows without bound | none | the three caps, refused before the query |

`reads_use_base_query` stays `runtime.applicability: required`.

## Known gaps, recorded

- **The build-time rule sees direct mixins only.** It does not see a model that inherits soft
  delete through a base of its own, or an `OwnedMixin` model. For those, the runtime refusal is
  the only layer. Widening the rule moves with the rules (ADR 0203), where its corpus lands with
  it.
- **SQLite keeps a timestamp's wall time and drops its offset.** A non-UTC instant written to
  SQLite is stored as local time, so every comparison against it is off by the offset, this
  seam's steps included. PostgreSQL stores the instant. The framework stamps every timestamp it
  owns in UTC, so those compare correctly on both. A column type that normalises to UTC when it
  binds removes the caveat for every comparison, not only this one, and is a follow-up of its
  own.
- **Zone rules are the host's where it has them.** `tzdata` is now a dependency of `terp-core`,
  so every IANA name resolves on every host, Windows and a slim container included. But
  `zoneinfo` prefers the host's own zone database when there is one, so two hosts on different
  database releases can disagree about a zone whose rules changed between them.

## What the review changed

The proposed record was reviewed against the code before the build, and the review's findings
are folded in above:
- **Personal data:** decision 5 refuses a personal filter, a time bucket and every
  value-derived figure, not only `min` and `max`.
- **Core reads:** decision 6 judges each SELECT. The first build's whole-statement rule missed a
  Core join, a Core scalar subquery and literal SQL. It also refused a many-to-many through a
  row-scoped link table without saying why.
- **The cache:** the first build cached a context-dependent answer, so an owner-scoped Core read
  passed when the process's first read had no actor. Scope is now asked in the read's own
  context.
- **The step join:** chosen over the proposed `CASE` from the review's measurements.
- **Typing and caps:** the response is typed by the declarations, a step carries its `date`,
  the HTTP query is capped, and groups times steps has a cap of its own.
- **Claims:** these were corrected above:
  - SQLite storage;
  - the PostgreSQL grouping premise;
  - the zone database;
  - the build-time half of the personal-data row;
  - where the catalog corrections land.

## Consequences

- A statistics screen has a sanctioned path: declare, take `StatisticsQueryDep`, return
  `aggregate_page`. Its response is typed in the API contract, and its series feeds
  `DashboardPage`'s charts. Whether the chart components take the shape directly is a frontend
  question, not this record's.
- `terp-cap-audit`'s activity read is three declared aggregates over the trail. Its response is
  unchanged, and its tests pass as they were. The new HTTP shape has its consumer in the
  framework's own tests: a route through `create_app`, its typed page, and its refusals.
- `terp-core` gains `tzdata`, which `terp-cap-audit` no longer declares on its own.
- An app that reads a scoped table through Core on the request session gets `UnscopedReadError`
  where it got unscoped rows, and so does a many-to-many through a row-scoped link table. Both
  are upgrade notes.
- The open items' R6 row moves to done, and the paragraph correcting the draft points here.
