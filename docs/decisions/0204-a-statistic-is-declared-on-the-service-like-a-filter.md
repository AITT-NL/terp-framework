# 0204 — A statistic is declared on the service, like a filter

- **Status:** Proposed (awaiting review). Nothing is built yet: the record comes first, so the
  shape of the seam is agreed before code depends on it.
- **Date:** 2026-11-06.
- **Relates:** [ADR 0017](0017-non-overridable-scope-predicate-and-registry.md) (the row scope
  every read composes, and the `reads_use_base_query` rule that warns about a read that skips
  it), [ADR 0171](0171-the-admin-hub-is-a-dashboard-of-the-administration.md) (the one
  framework-owned aggregate, hand-written in `terp-cap-audit`, which this seam replaces),
  [ADR 0190](0190-a-field-declares-itself-personal.md) (personal data, which a statistic must
  not hand back one person at a time), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  and [ADR 0084](0084-runtime-applicability-classification.md) (the two layers, and the
  classification that records them), the platform-reach open items (R6).

## Decision

A service declares what may be counted and summed, and by what, the way it already declares
what may be filtered and sorted: `measures`, `dimensions` and `time_buckets` beside
`filterable` and `sortable`. One method, `aggregate`, composes the request on `base_query()`
as a subquery and answers with a `Page[AggregateGroup]`: one item per combination of the
requested dimensions, each carrying its measures and, when a time bucket was asked for, its
series over the window, with empty buckets filled with zero. Everything undeclared is refused,
as an undeclared filter is. The page is bounded by a cap the declaration sets, the series by a
bucket cap checked before the query runs. A dimension, a `min` or a `max` over a field declared
personal is refused when the class is defined. The audit capability's activity read moves onto
the seam and is its first consumer.

The runtime half mostly exists already, and this record says so rather than proposing it again.
Since 0.36.0 the request session scopes every ORM read, aggregates included. The one shape it
cannot scope, a read of a scope-trait table through its Core `Table` instead of its mapped
class, is refused at execution.

## Context

A statistics screen counts and sums over the same tables its lists read: invoices per month,
open cases per status, revenue per region. A list has a sanctioned path. A statistic has none.

What a module writes today is the natural spelling,
`select(Invoice.status, func.count()).group_by(Invoice.status)`. On a model with a soft-delete
or tenant trait, `reads_use_base_query` flags it: the rule walks the whole `select(...)` chain.
That is correct, because the rule cannot know whether the scope survived. The remedy it names,
"build on `base_query()`", has no aggregate form. The way to satisfy it is
`select(func.count(q.c.status)).select_from(q)` over `q = self.base_query().subquery()`, which
is what `BaseService._paginate` does for its own total. It is scoped and it passes the rule, but
every column becomes a string lookup on `q.c`, nothing types the result, and every module
writing it rediscovers the same three things on its own:

- **Time buckets are hard to get right.** ADR 0171 records it: a calendar day is the viewer's
  day, not UTC's, and a day that daylight saving shortens keeps its real length. And PostgreSQL
  refuses a `GROUP BY` on an expression that carries bound parameters once they are bound on the
  server, because the select list and the grouping no longer read as one expression. The audit
  read counts its days as one conditional aggregate per day for exactly that reason.
- **A grouping has no bound.** Grouping by a column with ten thousand values returns ten
  thousand rows. Every list endpoint paginates; a hand-written statistic does not, and nothing
  asks it to.
- **A grouping can undo the personal-data declaration.** Counting invoices *per email address*
  hands back a value per person, the thing ADR 0190 keeps out of the log, the audit trail and
  events. A `max(date_of_birth)` over a group of one does the same.

**The runtime gap is smaller than the open items say.** They were written on 0.34.0, when the
session guard re-scoped only a single-entity `select(model)` and left every column or aggregate
select alone. 0.36.0 (#201) replaced that with an ORM execution hook. It applies the row scope as
loader criteria to every mapped entity the statement reaches, in its columns, joins, predicates
and nested selects. Measured on 0.36.1 against a soft-deleted row: `select(func.sum(...))`,
`select(func.count(Model.id))`, `select(func.count()).select_from(Model)`, a `group_by`, a count
joined through a scoped child, and an aggregate over a subquery of the entity all exclude it, on
SQLite and on PostgreSQL. What still reads it is a statement that
names no mapped entity at all: `Model.__table__.c.amount`, or `select_from(Model.__table__)`.
The build-time rule sees those, because they still name the model. The runtime does not.

## Decisions

### 1. Three declarations, beside `filterable` and `sortable`

```python
class InvoiceService(BaseService[Invoice, InvoiceCreate, InvoiceUpdate]):
    model = Invoice
    filterable = (FilterField("customer_id", Invoice.customer_id),)
    measures = (
        Measure("invoices", op="count"),
        Measure("revenue", Invoice.amount, op="sum"),
    )
    dimensions = (Dimension("status", Invoice.status),)
    time_buckets = (TimeBucket("issued", Invoice.issued_at, steps=("day", "week", "month")),)
```

- `Measure(name, column=None, op=...)`: `op` is one of `count`, `count_distinct`, `sum`, `avg`,
  `min` and `max`, fixed by the declaration and never sent by a caller. `count` alone takes no
  column.
- `Dimension(name, column)` groups by a column's own value. No expressions: a dimension that
  needs one is a column the model declares, or a database view read through R11.
- `TimeBucket(name, column, steps)` places a timestamp in a calendar step of the caller's time
  zone.

They live in `terp.core.aggregation`, as filters live in `terp.core.filtering`, and the same
fail-closed rule holds: a name the service did not declare is a `ValidationFailedError` (400)
that lists the declared names, and the name is checked before the value.

### 2. One method, composed on `base_query()` as a subquery

```python
page = service.aggregate(
    session,
    measures=["invoices", "revenue"],
    by=["status"],
    bucket=BucketRequest("issued", step="month", start=..., end=..., zone="Europe/Amsterdam"),
    filters={"customer_id": customer_id},
    sort=["-revenue"],
    skip=0,
    limit=20,
)
```

Row scope, soft delete, `business_filters` and the declared filters apply first, inside the
subquery, so the aggregate cannot drop them, as a list cannot. The bucket is a `CASE` over bound
instants, computed inside the subquery as one more column. The grouping happens outside, over the
subquery's columns, so the outer `GROUP BY` names a column and never an expression carrying
parameters, the form ADR 0171 found PostgreSQL refusing. Measured on SQLite and PostgreSQL 16, the
subquery form groups the same way on both. Each bucket boundary is a local midnight made in the
zone and then converted, ADR 0171's rule, so a short day keeps its length on both dialects.

A read that is not a `BaseService`'s, like the audit trail's, uses the same function with its own
query: `aggregate(session, query, declaration, request)`. `BaseService.aggregate` is that call
with `base_query()`.

### 3. The answer is a page of groups, each with its series

```json
{
  "items": [
    {
      "dimensions": {"status": "paid"},
      "measures": {"invoices": 41, "revenue": 18250},
      "series": [{"start": "2026-09-01T00:00:00+02:00", "measures": {"invoices": 12, "revenue": 5100}}]
    }
  ],
  "total": 3
}
```

One item per dimension combination, never one per combination *and* bucket. Paging a long
format would cut a chart's line in two. Without `by`, the page has one item, the whole scope.
Without `bucket`, `series` is `null`. `total` counts the groups, so a screen that asked for the
top eight still knows how many there are. That is the audit read's "eight most changed record
types" with nothing special about it.

The open items name this item `Bucket`. It is `AggregateGroup` here, because a time bucket is
already the other thing called a bucket.

### 4. Two caps, both fail closed

- **The page.** `limit` is bounded by the declaration's `max_groups` (default 100) as well as by
  the platform's page cap, whichever is lower. A larger `limit` is refused, never clamped.
- **The series.** The number of buckets the window and the step imply is computed before the
  query runs. Above the time bucket's `max_buckets` (default 366) it is refused, with the step
  that would fit named in the message.

The open items asked how to bound cardinality: a sampled estimate, a `LIMIT` probe that fails on
overflow, or a declared cap. Paging answers it without an estimate. The groups page like rows,
the count is exact, and only the window, which is the caller's to choose, needs a refusal.

### 5. A statistic never hands back one person's value

A `Dimension` over a field declared with `Personal(...)`, and a `min` or `max` `Measure` over
one, is refused when the class is defined, with the `TypeError` an inert declaration already
raises. A breakdown per person is a list, and a list has a route, a policy and a `Page` of its
own. `count`, `count_distinct`, `sum` and `avg` over a personal field stay allowed: a count of
distinct addresses discloses none of them.

A minimum group size, so that a group of one cannot be read off a filtered count, is **not**
decided here. It is a real threat for a small population, and it is a policy with a number in
it. It needs its own record when an application asks for it.

### 6. The runtime refuses the one read it cannot scope

The ORM execution hook stays as it is. Tests pin the aggregate shapes it scopes (a `sum`, a
`count`, a `group_by`, a join through a scoped child, an aggregate over a subquery of the
entity), so a change to it that loses one fails there.

What it cannot scope is a statement that reaches a scope-trait table through the Core `Table`
alone. The same hook refuses that, fail closed: when a statement's `FROM` contains the table of a
model that carries row scope, and no mapped entity for that table is present to take the
criteria, it raises before execution. That is a programming error, a 500 with the reason in the
log, like an unaudited write. A framework path that legitimately reads a scoped table through
Core is the case to find while building this. It runs on a session the guard does not hand out,
or it is rewritten on the mapped class.

## What does not change

- `filterable`, `sortable` and `list` are untouched; the aggregate reuses `filterable` for its
  narrowing, so one declaration governs both reads.
- No query language and no pivot builder. The open items refused them, with a database view and
  a read-only model as the answer for a report the declarations cannot express.
- No rollup tables. ADR 0171 weighed one for the audit trail and declined it, and nothing here
  changes that weighing.
- No new catalog rule. `reads_use_base_query` keeps flagging a hand-built aggregate over a
  scope-trait model. Its remedy names the seam, and its catalog prose is corrected: the runtime
  backstop now scopes every ORM read, not only single-entity ones.

## Two-layer enforcement

| | Build time | Runtime |
|---|---|---|
| A hand-built aggregate drops the row scope | `reads_use_base_query` (existing; remedy gains the seam) | the ORM execution hook (exists since 0.36.0; now pinned by tests) and the Core-table refusal (decision 6, new) |
| A caller groups or counts by something undeclared | none needed: the names are data | `ValidationFailedError` at resolution, before the query |
| A statistic hands back a person's value | none: the marker is runtime metadata | `TypeError` at class definition |
| A statistic grows without bound | none | the two caps, refused before or by the query |

`reads_use_base_query` stays `runtime.applicability: required`. Only its rationale is rewritten.

## Consequences

- A statistics screen has a sanctioned path: declare, call, render the page. `DashboardPage`
  and the chart family read `AggregateGroup` series without a reshaping step. Whether the chart
  components accept the shape directly is a frontend question for the build, not this record.
- `terp-cap-audit`'s activity read becomes a declaration and a call. Its per-day counts, its
  previous window and its top eight record types are all one `aggregate` each, and its tests
  carry over unchanged as the seam's first acceptance.
- `terp-core` gains `tzdata` as a dependency, because a zone must resolve the same on every host
  and Windows has no zone database. ADR 0171 made the same choice for `terp-cap-audit`, which
  then no longer needs it on its own.
- A catalog prose patch for `backend/reads_use_base_query` goes to terp-spec, with the
  framework change that makes it true.
- The open items' R6 row moves to done once this is built, and the paragraph correcting the
  draft is replaced with a pointer here.

## Questions for the review

1. Decision 5: is refusing a personal dimension and a personal `min` or `max` at class
   definition the right strength, or should a justified marker allow one?
2. Decision 6: refusing a Core-table read of a scoped table at runtime may find a framework
   path that does it today. Accept the refusal, with that audit as part of the build?
3. `tzdata` in `terp-core`: accept, or keep zone resolution in a capability and give the core
   seam UTC steps only?
