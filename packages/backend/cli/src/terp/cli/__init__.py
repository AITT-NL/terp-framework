"""terp.cli — the ``terp`` command-line tool."""

from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import re
import sys
from collections.abc import Callable, Sequence

from terp.core import ControlPlane, CorsPolicy, ModuleSpec

from terp.cli.access import (
    build_access_graph_for_app,
    render_access,
    render_access_graph,
)
from terp.cli.apidocs import api_docs
from terp.cli.capabilities import render_capabilities
from terp.cli.dev import dev_plan, run_dev_command
from terp.cli.docker import run_docker_dev_command
from terp.cli.fmt import changed_python_files, run_fmt_command
from terp.cli.leases import reap_leases_command, render_leases
from terp.cli.jobs import (
    render_jobs,
    run_job_command,
    run_scheduler_command,
    run_worker_command,
)
from terp.cli.openapi import _load_app, export_openapi
from terp.cli.routes import run_routes_command
from terp.cli.profiles import DEFAULT_PROFILE, profile_names
from terp.cli.scaffold import new_module, new_module_message
from terp.cli.schema import (
    build_schema_graph,
    import_declared_models,
    render_schema_graph,
    scan_declared_table_models,
)
from terp.cli.seed import run_seed_command
from terp.cli.grants import (
    grant_add_command,
    grant_list_command,
    grant_revoke_command,
)
from terp.cli.service_accounts import create_service_account_command
from terp.cli.users import create_user_command
from terp.cli.verify import profile_ids, run_verify_command, verify_manifest

_GUIDE_TOPICS: dict[str, str] = {
    "module": """\
Add a module (the "10-minute module")

1) models.py   table model (inherit BaseTable; never redeclare id/created_at/version)
     from terp.core import BaseTable
     from sqlmodel import Field
     class Invoice(BaseTable, table=True):
         number: str = Field(max_length=50, index=True, unique=True)
         amount_cents: int

2) schemas.py  DTOs (cap every input string; the Read DTO is what the API returns)
     from terp.core import BaseSchema, BaseUpdateSchema
     class InvoiceCreate(BaseSchema):
         number: str = Field(max_length=50)
         amount_cents: int
     class InvoiceUpdate(BaseUpdateSchema):   # `version` is required (optimistic concurrency)
         amount_cents: int | None = None
     class InvoiceRead(BaseSchema):           # NOT the table model
         id: uuid.UUID; number: str; amount_cents: int; version: int

3) service.py  business logic (CRUD is inherited and audited)
     from terp.core import BaseService
     class InvoiceService(BaseService[Invoice, InvoiceCreate, InvoiceUpdate]):
         model = Invoice

4) router.py   thin HTTP layer (convert rows to the Read DTO)
     @router.post("/", response_model=InvoiceRead, status_code=201)
     def create_invoice(payload: InvoiceCreate, session: SessionDep) -> InvoiceRead:
         return InvoiceRead.model_validate(_service.create(session, payload))

5) module.py   the manifest
     module = ModuleSpec(name="invoices", router=router, policy=Policy.default())

6) MOUNT IT. A module nobody mounts serves no routes, and nothing fails: the gate is
   happy, the tests are happy, and the endpoints are simply not there. Import it in the
   composition root and add it to the list `create_app` is given:

     # app/main.py
     from app.modules.invoices.module import module as invoices
     create_app([..., invoices], ...)

Then the codegen chain, in this order — each step reads what the one before it wrote:

     terp migrate make invoices    # the table's migration
     terp openapi                  # the backend contract
     npm --prefix frontend run generate    # the typed client, from that contract
     terp routes                   # the checked route table (ADR 0092)
     terp check                    # the architecture gate

`terp verify` runs the drift halves of that chain and names the command to re-run when
something is stale, so it is the one to reach for if you are unsure what is out of date.
Policy.default() = authenticated; read VIEWER, write EDITOR.
""",
    "dependencies": """\
One module needs another (declared edges)

Modules are independent by default: an import of a sibling is refused. When a real
dependency exists, DECLARE it — do not hand-roll dependency inversion.

1) Name the sibling in the DEPENDING module's manifest:
     # app/modules/catalogs/module.py
     module = ModuleSpec(
         name="catalogs",
         router=router,
         policy=Policy.default(),
         requires=("connections",),   # <- the edge, in the manifest a reader consults
     )

2) Now import its published surface:
     from app.modules.connections.service import ConnectionProfileService

Three limits, each enforced:

- DECLARED. An undeclared sibling import fails `no_cross_module_imports`. The point
  is not to make coupling hard, it is to make coupling VISIBLE.
- PUBLIC SURFACE ONLY. An edge grants models / schemas / service / events. Never the
  dependency's router (that couples two modules through HTTP shapes and lets an
  in-process call walk past the policy guarding those routes) and never an
  underscore-prefixed internal. Import a named surface, not the bare package.
- ONE-WAY. The declared graph must be acyclic — `terp check` reports the cycle and
  the app refuses to boot on one. A cycle means the two modules are really one.

When NOT to declare an edge:

- You only need to REACT to the other module -> subscribe to its event
  (`terp guide events`). An event keeps the direction one-way and the coupling loose.
- BOTH directions want an edge -> the shared concept belongs in a third module that
  both depend on. Inverting one direction by hand (a Protocol plus a global registry
  plus a composition-root adapter) is the same coupling with more moving parts and
  module-global mutable state; declare the edge or extract the concept.
- The dependency is a capability (audit, files, users) -> that is not a module edge.
  `requires=("audit",)` still means "must be installed"; capabilities are importable
  by every module already.

Check it: `terp check`  |  See the declared edges: `terp inspect control-plane`
""",
    "service": """\
Services (BaseService)

- Subclass BaseService[Model, Create, Update] and set `model`. You get
  create/update/delete/get/list — all audited, OCC-checked and scope-honored.
- `get` raises NotFoundError; `find` returns Model | None through the SAME row scope.
  Use `find` when absence is one input among several — a validator collecting every
  finding, a pre-flight report — instead of try/except around `get`:
      snapshot = self._snapshots.find(session, snapshot_id)   # None is an answer
- A bespoke mutation must route through self._save(...) / self._remove(...) (never a
  raw session write), so it stays audited.
- Add an always-on read filter by overriding business_filters() — it returns
  conditions and CANNOT drop soft-delete / tenant scope:
      def business_filters(self):
          return (Invoice.status == "open",)
- A per-call filter/sort (a query parameter) is DECLARED, not hand-written. Name the
  allowed columns on the service and pass the values through — an undeclared field is
  refused (400), and the caller sends values, never operators:
      class InvoiceService(BaseService[Invoice, InvoiceCreate, InvoiceUpdate]):
          model = Invoice
          filterable = (FilterField("status", Invoice.status),
                        FilterField("q", Invoice.title, op="contains"))
          sortable = (SortField("due_on", Invoice.due_on),)
          default_sort = ("-due_on",)
      # route: status: str | None = None  ->  typed, and it shows up in OpenAPI
      rows, total = service.list(session, skip=..., limit=..., filters={"status": status},
                                 sort=sort)
  None values are dropped, so an absent optional parameter needs no branching. Filters
  compose ON TOP of base_query(), so row scope and business_filters() still apply —
  they cannot widen a read. Don't write a list() override to do this by hand.
- On a large table, prefer keyset pagination: a route takes CursorPaginationDep and
  returns CursorPage[ReadDTO] from self.list_by_cursor(session, pagination=...) —
  no OFFSET scan, and the exact COUNT runs only when the caller asks
  (include_total=true).
- EVERY read (search, "my items", reports) builds on base_query() — never a raw
  select(Model) and never session.get(Model, id). A scope-trait model
  (SoftDeleteMixin/TenantScopedMixin) read via a bare select() or a primary-key
  get() drops soft-delete/tenant scope (cross-tenant leak); the gate's
  reads_use_base_query rule forbids both, and the request session re-scopes the
  user-facing read methods (exec/scalars/scalar/get) as a backstop. Read a single
  row with self.get(session, id) — NOT session.get(Model, id).
- Soft-delete: mix SoftDeleteMixin into the model; delete() soft-deletes and reads
  exclude it automatically. Never write deleted_at by hand. Never override base_query.
- Provenance is automatic: compose ActorStampedMixin and BaseService fills
  created_by_id / modified_by_id from the request actor on every write — never set them
  by hand (the no_manual_actor_stamping rule forbids it). A Read DTO may still expose
  them to surface "who created / last changed this".
- A table nothing may change after insert (a ledger row, an immutable revision, a
  snapshot) DECLARES it — immutability that lives in "we didn't mount an update route"
  evaporates the day someone mounts one:
      class SyncRevisionService(BaseService[SyncRevision, ..., ...]):
          model = SyncRevision
          append_only = True
  update() / delete() and any bespoke _save of an existing row then fail closed with a
  uniform 409, at the write chokepoint, whatever the route surface looks like.
- A JSON column takes a typed value object with no extra annotation: the write
  chokepoint dumps exactly the JSON-backed fields in pydantic's json mode, so a UUID /
  datetime / Enum inside the document is encoded rather than dying at flush with
  "Object of type UUID is not JSON serializable". Non-JSON columns still receive their
  native Python value.
- Dropping to raw SQL? Keep the text(...) argument a STATIC literal and pass data
  through bound parameters — a dynamically built statement (f-string, concatenation,
  .format, %, or a variable) is refused by the no_dynamic_sql rule (SQL injection):
      session.exec(text("SELECT ... WHERE status = :status"), {"status": status})
- A pure validator that needs a fact from ANOTHER module's table does not get a
  session of its own. Keep the validator pure — it takes facts, not a database — and
  let the calling service look the fact up before it runs. Thread the dependency in
  the constructor, once, rather than reaching for a session mid-validation:
      class SyncService(BaseService[Sync, SyncCreate, SyncUpdate]):
          model = Sync
          def __init__(self, *, operations: OperationSnapshotService) -> None:
              self._operations = operations
          def publish(self, session, sync):
              vocabulary = self._operations.current(session)     # the fact
              run_invariants(sync, vocabulary=vocabulary)        # still pure
  The sibling service is a declared edge (ModuleSpec(requires=...)), so the dependency
  is visible in the manifest. A validator that opened its own session would be
  unreviewable, untestable without a database, and outside the write chokepoint.
""",
    "policy": """\
Authorization (Policy)

- Every ModuleSpec carries a Policy (deny-by-default):
      Policy.default()                      authenticated; read VIEWER, write EDITOR
      Policy(read=VIEWER, write=ADMIN)       typed roles (terp.core: VIEWER/EDITOR/ADMIN)
      Policy.public(reason="health probe")   the ONLY way to drop authentication
- Fine-grained permissions need a per-subject GRANT, not just a role:
      Policy(write=Permission("invoices.approve", min_role=EDITOR))
  Wire create_app(..., permission_enforcer=terp.capabilities.access.enforce_permission)
  or boot fails closed. Grant via the access capability; the caller must clear the
  min_role floor AND hold the grant.
- Route-level extra check: dependencies=[Depends(require_permission("invoices.approve"))].
- Authority is always a typed object (Role / Permission), never a bare string.
- Choosing between a role and a permission, and the grant lifecycle: `terp guide permissions`.
""",
    "permissions": """\
Permissions — when to add one, and how it reaches a subject

WHEN A PERMISSION IS THE RIGHT ANSWER
- The role ladder answers "how much of this app may you touch?" - VIEWER < EDITOR
  < ADMIN, coarse and comparable. A permission answers "may you do this ONE thing?"
  and is not comparable to anything.
- Add a permission when the authority is NARROWER than a role and does not belong
  on the ladder: an integration that may export invoices but must not edit them; a
  finance user who may approve but is not an app admin.
- Do NOT add a permission for something every EDITOR should be able to do - that is
  the role, and a permission held by everyone is a checkbox nobody reads.
- Do NOT model a role as three permissions. The ladder exists so authority stays
  comparable; a bag of permissions cannot answer "is this account privileged?".

DECLARE IT
      from terp.core import EDITOR, Permission
      APPROVE = Permission("invoices.approve", min_role=EDITOR)
  min_role is a FLOOR, not a shortcut: the caller must clear it AND hold the grant.
  Both checks are real - the floor stops a grant from smuggling authority to a
  subject the app never intended to trust that far.
- Enforce it on the module (Policy(write=APPROVE)) or on one route
  (dependencies=[Depends(require_permission("invoices.approve"))]).
- Wire the enforcer once, or the app refuses to boot (fail closed - a Permission
  requirement with nothing to enforce it would silently pass):
      create_app(..., permission_enforcer=terp.capabilities.access.enforce_permission)

GRANT IT
      terp grant add ops@acme.test invoices.approve
      terp grant add nightly-sync invoices.export     # a service account, by name
      terp grant list ops@acme.test                   # "why can it do that?"
      terp grant revoke ops@acme.test invoices.approve
  A subject is named the way you name it - a user email, a service-account name, or
  a subject UUID. An unknown permission is refused WITH the app's catalog printed,
  because a grant of a string the app never checks is a silent no-op, not a lenient
  grant. Grants are stored per subject id with no foreign key, which is what lets a
  user, a service account and a group all be granted the same way; a group grant
  reaches every member (`terp guide access`).
- Mind the floor: granting a permission to a subject BELOW its min_role stores a row
  that the rank check will shadow. `terp grant add` warns when it sees this.
- See the whole declared catalog and every module's policy:
      terp inspect control-plane --app app.main:build

THE FAILURE MODE THIS EXISTS TO PREVENT
  An integration needs one narrow capability, granting looks like work, so someone
  makes it an admin "for now". Least privilege loses to a ten-second workaround. If
  you catch yourself widening a role to unblock one call, that call wants a
  permission - and the grant is one command (ADR 0089).
""",
    "access": """\
The access model (three layers) — profiles + the access graph

- Effective access is exactly three composable layers, each an existing primitive:
      1. module access    ModuleSpec.policy — may this principal enter the module?
      2. endpoint access  the route's read/write requirement (mutating verb => write),
                          plus route-level require_permission(...) dependencies
      3. data visibility  model traits — which rows are readable / mutable?
                          OwnedMixin (write gate), TenantScopedMixin (read filter +
                          stamped writes), register_scope_predicate / object-authz
- Pick a PERMISSION PROFILE instead of hand-assembling the layers:
      terp new module invoices --profile <name>
      shared          read VIEWER, write EDITOR (Policy.default())
      role-gated      read VIEWER, write ADMIN
      owner-private   + OwnedMixin: only a row's owner may update/delete
      tenant-private  + TenantScopedMixin + TenantScopedService: rows isolated per tenant
      tenant-owner    tenant isolation + the per-row owner write gate
  A profile is a preset, never a mechanism: it only decides which primitives the
  scaffold composes, so the output is ordinary gate-checked Terp code you own.
- SEE the whole graph — who can reach which module, endpoint, and rows:
      uv run terp inspect access --app app.main:build --app-root . --format json
  The --app form reports the WHOLE composed surface — client modules AND every
  discovered capability router (users / groups / audit / files / …) plus the kernel
  health routes — reconciled against app.openapi() so a mounted route can never hide
  (any that is not covered is listed under omitted_routes, fail-visible). Use
  --object/--module instead to inspect a focused, hand-passed subset.
  One document: roles, permissions, every endpoint's method/path/requirement, each
  declared service's model traits (owned / tenant-scoped / soft-delete), read scope,
  write authority, and warnings (e.g. OwnedMixin gates writes only). `--format json`
  is the stable Studio contract; declare services=(InvoiceService,) on the ModuleSpec
  so the data layer is visualizable — an undeclared data layer is a warning.
- Narrowing authority below a role, and getting a permission to a subject:
  `terp guide permissions` (declare it, enforce it, `terp grant add`).
""",
    "soft-delete": """\
Recoverable deletes (SoftDeleteMixin)

- Compose the trait into the model and the framework owns BOTH halves — a module
  writes no soft-delete code, and the gate refuses it if you try:
      from terp.core import BaseTable, SoftDeleteMixin
      class Connection(BaseTable, SoftDeleteMixin, table=True):
          name: str = Field(max_length=200)
- WRITE: BaseService.delete stamps deleted_at at the audited chokepoint instead of
  issuing a DELETE. The route is unchanged (still 204, still 404 afterwards) and the
  audit record still reads DELETED — at the boundary the row IS gone. Rows that point
  at it (a run log, a snapshot) keep their referent, which is the point of the trait.
- READ: apply_row_scope adds `deleted_at IS NULL` to every read of the model. It is
  composed by base_query AND re-applied by the request session to a bare
  select(model), so the filter is not something you can forget. Never write the
  predicate yourself (no_manual_scope_filtering refuses it); narrow further with
  business_filters(), never by overriding base_query.
- UNIQUENESS is the one thing the trait cannot decide for you. A plain unique column
  lets a deleted row hold its value forever, so "prod-erp" could never be recreated.
  Declare a partial unique index — for EVERY dialect you run on, because a
  Postgres-only predicate compiles to a FULL unique index on SQLite and silently
  restores the trap (no_unique_columns_on_soft_delete_models enforces both halves):
      __table_args__ = (
          Index("uq_connection_name_live", "name", unique=True,
                postgresql_where=text("deleted_at IS NULL"),
                sqlite_where=text("deleted_at IS NULL")),
      )
  A duplicate among the live rows then surfaces as the uniform 409 ConflictError, the
  same as any other integrity conflict — you do not map it.
- UNDELETE is not sanctioned yet: BaseService has delete but no restore, and writing
  your own would mean touching deleted_at, which the gate refuses. Today the trait
  preserves the row and the history that cites it; bringing one back is an operator
  action, not an app one.
""",
    "package-boundaries": """\
Boundaries for a second top-level package (an ungated worker)

- The shape: an app whose work cannot run under the gate — a legacy-DB connector, a
  device, a non-Python runtime — keeps a SECOND top-level package beside `app/`, and the
  two must not import each other. `terp check` scans `app/` for Terp's own rules; it
  deliberately does not own generic import-graph checks, because a graph contract is
  exactly what a generic tool already does better (and terp.arch would then be a second,
  weaker copy).
- So declare the graph with import-linter, which the platform itself uses for its own
  layer-0 keystone. In the app's pyproject.toml:
      [tool.importlinter]
      root_packages = ["app", "engine"]

      [[tool.importlinter.contracts]]
      name = "the engine never imports app (it runs outside the gate)"
      type = "forbidden"
      source_modules = ["engine"]
      forbidden_modules = ["app"]

      [[tool.importlinter.contracts]]
      name = "app never imports the engine (the control plane records, never executes)"
      type = "forbidden"
      source_modules = ["app"]
      forbidden_modules = ["engine"]

      [[tool.importlinter.contracts]]
      name = "plugins are reached only through the registry"
      type = "forbidden"
      source_modules = ["engine"]
      forbidden_modules = ["engine.plugins"]
      ignore_imports = ["engine.registry -> engine.plugins.*"]
  `terp verify` runs it for you: the `package-boundaries` check fires whenever
  `[tool.importlinter]` is present, so declaring contracts is the whole adoption step and
  there is no second command to remember. That replaces a hand-rolled AST scan per
  boundary, and it fails with the offending import chain rather than a file:line you have
  to trace. Install the linter alongside the contracts (`uv add --dev import-linter`) —
  declared-but-not-installed is a red, not a skip, because a boundary nothing can check is
  not a boundary.
- What terp.arch still owns, because these are Terp semantics and not graph shape:
  `no_dynamic_sql` (SQL must be a static, reviewable literal — the containment check an
  app would otherwise hand-roll), `no_raw_outbound_http`, `no_adhoc_background_runtime`,
  and every rule about BaseService / ModuleSpec / schemas. Run it on `app/` only: the
  second package is not a Terp app, and scanning it would report rules it cannot satisfy.
- The worker's own gate is one command, and both halves are in it:
      uv run terp verify             # Terp rules over app/, then the declared
                                     # package graph over both
- Sharing types across the boundary: neither package may import the other, but BOTH may
  import a third. A `contracts/` package of frozen value objects (with `max_length` caps
  declared, so the app half satisfies the input-schema rule) is one declaration and two
  consumers — rather than twin modules pinned against drift by a test.
- Reaching the app over HTTP is the sanctioned direction: the worker holds a service
  account credential (`terp service-accounts create`), so its writes pass the same guard,
  the same audit trail and the same actor stamping as anyone's. Give it a lease
  (`terp guide leases`) so a claim it takes and dies on is recoverable.
""",
    "ownership": """\
Object-level (per-row) authorization (OwnedMixin)

- A Policy gates a whole route (every editor may edit every row). To restrict a write
  to the row's OWNER, compose OwnedMixin into the model — never hand-roll an owner_id
  check (the no_manual_ownership_checks rule forbids it):
      from terp.core import BaseTable, OwnedMixin
      class Journal(BaseTable, OwnedMixin, table=True):
          title: str = Field(max_length=200)
- BaseService stamps owner_id to the request actor on create, then authorizes every
  update / delete of that row at the audited chokepoint: a non-owner write fails closed
  with 403, with no code in your service. owner_id is stripped from inbound payloads, so
  a client can never seize ownership through the request body.
- For a richer policy than "owner only" (team membership, a shared-with ACL), register
  an object-authz predicate — the write-side seam — so a capability contributes per-row
  authority without the kernel importing it (predicates compose fail-closed, AND):
      from terp.core import register_object_authz_predicate
      register_object_authz_predicate(my_predicate)  # (model, entity, actor, action) -> bool
- Ownership is the WRITE gate only; read visibility is the separate register_scope_predicate
  seam (ADR 0017) — an OwnedMixin row stays readable by a non-owner unless you also restrict
  reads. An owner-keyed read filter necessarily references the managed owner_id, so (like the
  tenancy capability's tenant filter) it belongs in a governed predicate carrying a justified
  `# arch-allow-no_manual_ownership_checks`; a built-in owner-read filter is planned sugar.
  Endpoint authority (Policy), row-read visibility (register_scope_predicate) and row-write
  authority (OwnedMixin) are the three composable layers.
""",
    "leases": """\
Leases: expiring, fenced custody of work (leases capability)

- The problem: a worker flips a row to `claimed` (or opens a `running` run) and is then
  killed. The row stays taken forever, and nothing distinguishes "still working" from
  "died an hour ago" - the only recovery is a hand-written UPDATE. The mirror-image need,
  "at most one active run per pipeline", is the same missing primitive.
- A lease is a named resource + an opaque holder + an expiry + a monotonic epoch fence:
      from terp.core import LeaseResource, hold_lease
      resource = LeaseResource.for_row(run)              # ("sync_run", "<uuid>")
      resource = LeaseResource("pipeline", str(pk))      # a domain mutex, not a row
- Wire the durable store, or nothing is taken. There is deliberately NO in-process
  default: a per-process lease would let two replicas hold one resource.
      from terp.capabilities.leases import DatabaseLeaseStore, module as leases_module
      create_app([..., leases_module], lease_store=DatabaseLeaseStore(),
                 require_durable_leases=settings.is_production)
- Take the lease inside the service's own write, so claim-the-row and take-the-lease
  commit together - and a refusal leaves the row untouched instead of stuck in `claimed`:
      class RequestService(BaseService[RunRequest, ...]):
          def _after_write(self, session, entity, action):
              if entity.status == CLAIMED:
                  hold_lease(session, LeaseResource.for_row(entity),
                             holder=self.worker_id, ttl_seconds=60)
  hold_lease raises LeaseHeldError (409) when it is taken; acquire_lease returns None
  instead, for a worker that would rather try the next candidate.
- Heartbeat from inside the work loop. The guard writes only past the lease's half-life,
  and RAISES LeaseLostError if it was taken over - losing a lease means a successor may
  already be doing this work, so stopping is the only safe answer:
      with hold_lease(session, resource, holder=me, ttl_seconds=60) as guard:
          for record in records:
              guard.heartbeat()
- Expiry frees the RESOURCE; only your domain can put the ROW back. Register the recovery
  once, per resource kind, and make it idempotent (reaping is at-least-once):
      from terp.core import register_lease_reaper
      register_lease_reaper("run_request", requeue_stale_request)
  A kind with no reaper is simply released - the right answer for a pure mutex.
- Then actually run the reaper, or nothing is recovered. Put the declared job on a cron
  (several times per shortest TTL) and/or run it by hand:
      lease_reap_schedule(cron="*/5 * * * *", purge_idle_seconds=86400)
      terp leases reap --purge-idle-seconds 86400
      terp leases list --expired          # what is stuck, and who was holding it
- Never hand-roll lease columns on your own table (locked_by / locked_until /
  heartbeat_at / lease_expires_at). The no_manual_lease_columns rule refuses them: a
  hand-rolled lease has no fence, so a paused worker writes over its successor.
""",
    "tenancy": """\
Multi-tenant rows (tenancy capability)

- Mix TenantScopedMixin into the model and give it a TenantScopedService. Importing
  the mixin registers the tenant row predicate, so EVERY read of that model is
  filtered to the current tenant automatically and create stamps tenant_id; a missing
  tenant context fails closed (reads empty, writes raise).
      class Doc(BaseTable, TenantScopedMixin, table=True): ...
      class DocService(TenantScopedService[Doc, DocCreate, DocUpdate]): model = Doc
- Never filter tenant_id by hand — the framework owns the predicate (the gate forbids it).
- The current tenant comes from the request (TenantMiddleware binds the JWT `tenant`
  claim); in tests use tenant_context(tenant_id).
- Wire it through the create_app middleware seam — never add_middleware (the gate
  forbids it):
      from starlette.middleware import Middleware
      from terp.capabilities.auth import tenant_from_bearer
      create_app(specs, principal_provider=get_principal,
                 middleware=[Middleware(TenantMiddleware, resolve_tenant=tenant_from_bearer)])
  Sign the tenant into the token at login with
  build_login_module(authenticate, tenant_resolver=...).
""",
    "passwords": """\
Password strength (PasswordPolicy, Tier-B)

- Provisioning and resets enforce the app's PasswordPolicy at the users-service
  credential boundary: a weak password is refused with a typed 422 (code weak_password,
  the uniform envelope), the max_length cap stays the separate DoS guard.
- The safe default is 12+ chars, 2+ character classes, and a common-password denylist
  (length over forced complexity, NIST-aligned). Tier-B: override the VALUES, not shape:
      from terp.core import PasswordPolicy, ControlPlane
      control_plane = ControlPlane(passwords=PasswordPolicy(min_length=16, min_character_classes=3))
- Relaxing strength is an explicit, justified opt-out and is refused at production boot:
      PasswordPolicy.relaxed(reason="legacy bulk import")
- No terp.arch check applies (no module code shape to police) — enforcement is the
  service chokepoint plus the create_app production fail-fast.
""",
    "events": """\
Domain events (eventbus capability)

- The capability is a separate distribution — nothing below exists until you add it:
      uv add terp-cap-eventbus
  Then import from terp.capabilities.eventbus (EventEmittingService, LifecycleEventMap,
  subscribe, dispatch_in_process).
- Declare typed events in your control plane (never bare strings):
      NOTE_CREATED = EventDefinition("note.created", payload_schema=NoteCreatedPayload)
      event_catalog = EventCatalog([NOTE_CREATED])
- Declare what the module produces in its manifest. The emits list is the module's
  published contract, so the gate refuses an event you emit without naming it here:
      module = ModuleSpec(name="notes", emits=[NOTE_CREATED, NOTE_ARCHIVED])
- Emit declaratively from a service (atomic with the write):
      class NoteService(EventEmittingService[Note, NoteCreate, NoteUpdate]):
          model = Note
          event_map = LifecycleEventMap(created=NOTE_CREATED)
- The map covers "every write of this shape emits this event". When the decision is
  CONDITIONAL — a state transition, one event for some updates and none for others —
  extend the same hook rather than emitting from a router or a task:
      class NoteService(EventEmittingService[Note, NoteCreate, NoteUpdate]):
          model = Note
          event_map = LifecycleEventMap(created=NOTE_CREATED)

          def _after_write(self, session, entity, action) -> None:
              super()._after_write(session, entity, action)
              if action is AuditAction.UPDATED and entity.status == "archived":
                  emit(session, event=NOTE_ARCHIVED, payload=NoteArchivedPayload(id=entity.id))
  _after_write runs inside the write's transaction, so a conditional emit is still
  atomic with the row it describes — which is the whole reason the map lives there.
- Subscribe with @subscribe(NOTE_CREATED). Reference catalog constants only (the gate
  enforces no-drift). Wire create_app(..., event_dispatcher=dispatch_in_process).
- Switching the bus on in a service-level test: the `terp_events` fixture, never a
  direct configure_events (see `terp guide testing`).
""",
    "operations": """\
Route operations (what a route does for the person calling it, ADR 0102)

- Declare typed operations in your control plane (never bare strings or a value built
  inline at the call site):
      NOTES_DELETE = OperationDefinition(id="notes.delete_note", label="Delete a note")
      operation_catalog = OperationCatalog([NOTES_DELETE])
      control_plane = ControlPlane(operations=operation_catalog, ...)
- Apply it to a hand-written route with @operation(...), below the route decorator:
      @router.delete("/{note_id}", status_code=204)
      @operation(NOTES_DELETE)
      def delete_note(note_id: uuid.UUID, session: SessionDep) -> None: ...
- A canonical CRUD factory takes one per generated route instead of a decorator:
      router = build_crud_router(
          NoteService(), read_schema=NoteRead, create_schema=NoteCreate,
          update_schema=NoteUpdate, delete_operation=NOTES_DELETE,
      )
- What it does NOT change: authorization. A route's requirement still comes from its
  module's Policy and any route-level permission dependency — the same promise
  read_only makes. Declaring what a route does narrows nothing about who may call it.
- Coverage is the app's own choice, on OperationCatalog(coverage=...): OFF (default,
  nothing required), WARN (the boot check logs every undeclared route but still boots),
  or STRICT (a mounted route with no declared operation fails the boot). The build-time
  rule (routes_declare_operation) is binary, not three-way: it reports nothing under
  OFF or WARN and only starts requiring a declared operation on every route once the
  app has opted into STRICT — WARN's own signal comes from the boot check's log line,
  not from this rule.
- The label feeds OpenAPI too: a declared operation sets the route's summary and
  operation_id, so a hand-written summary= beside a declared operation is refused (two
  answers to the same promise).
""",
    "testing": """\
Testing a Terp app (process-global runtime isolation)

WHAT YOU MUST STILL DO YOURSELF. The platform UNDOES a runtime; it never INSTALLS the
one your test needs. That distinction is the whole of testing on Terp:
      * whole runtime -> compose the app in a fixture (see apps/example/tests/conftest.py,
        where db_engine + app_db are function-scoped and build() runs per test)
      * only the event bus -> the `terp_events` fixture, which installs a catalog
        (and dispatcher) for the duration of one test:
            terp_events(event_catalog, dispatcher=dispatch_in_process)
        Annotate it `InstallEvents` (exported from terp.core.testing) - it carries
        configure_events' real signature, so a wrong catalog is a type error.
      * only the DURABLE AUDIT SINK -> the `terp_audit` fixture (annotate it
        `InstallAudit`), because the default sink only LOGS:
            from terp.capabilities.audit import persist_audit
            terp_audit(AuditPolicy.default(), sink=persist_audit)
        Without it, `select(AuditEvent)` returns [] and an assertion about an empty
        result PASSES - the test reports that audit works and has established only
        that nothing was installed. If a durable-audit assertion is passing suspiciously
        quietly, the sink is the first thing to check.
      * asserting on what was written to a FAKE/bare session -> `terp_default_runtime`,
        which states the baseline instead of assuming it. Without it a composed app's
        durable audit sink quietly adds audit rows to the session under assertion.
Deleting a conftest that INSTALLS something is not part of adopting the plugin.

WHAT YOU GET FOR FREE. terp-core ships a pytest plugin (terp.core.testing, registered
under pytest11) whose autouse fixture SNAPSHOTS every runtime before a test and
RESTORES it after. No conftest.py line, no opt-in. Without it a suite goes
order-dependent: green together, red alone - the sharpest failure mode there is,
because the green is the wrong answer.

THE SIX SEAMS. create_app installs six process globals per app; in a test process they
outlive the app that installed them. Restored automatically -- but installed by you:

      seam         what create_app installs        who installs it in a test
      audit        audit policy + durable sink     compose the app, or `terp_audit`
      events       event catalog + dispatcher      compose the app, or `terp_events`
      jobs         job catalog + queue             compose the app
      scheduling   schedule catalog                compose the app
      passwords    password policy                 compose the app, else the default
      secrets      the decrypt call site           compose the app (a secrets capability)

STRICT MODE. Restoring is faithful, which is also its blind spot: a runtime installed
BEFORE the first test (a stray `import app.main` at collection time, a module-scope
create_app()) is part of the snapshot, so it is restored before every test and covers
every test equally - green together, red alone, with nothing having leaked. Strict mode
follows the snapshot with a RESET, so every test starts from the platform baseline and
a test that only ever passed on ambient state fails where it stands:
      [tool.pytest.ini_options]
      terp_strict_isolation = true          # or: pytest --terp-strict-isolation
New projects start with it on, and the framework runs its own suites that way. Switching
it on in an existing suite can turn a green red - that red is the finding, not the
regression: the test was reading a runtime it never installed. Install it explicitly;
never re-order the suite.

AND READ THE GREEN HONESTLY. Strict mode resets BEFORE fixtures run, so it can only see
installs that happen before the suite. An autouse fixture that installs a runtime for a
whole package is invisible to it - every test gets a bus it never asked for, and strict
mode agrees with you every time. So: a green strict run does NOT mean your installs are
precise, only that none of them happen before the suite. Ask the other half instead:
      uv run pytest --terp-report-runtime-installs
which reports, per seam, the tests that installed it. Read the SHAPE of the answer: one or
two ids under a seam is a test installing what it needs; every id in a package under one
seam is a fixture installing it for them. Then make that installer NAMED and non-autouse,
and let the tests that emit request it. The ones that then fail were the ones being carried.

TWO FIXTURES, ONE SEAM. A seam holds one runtime, so the last install wins - and pytest
decides "last" from the FIXTURE GRAPH, not from the order of your test's parameters. A tap
that installs a recording dispatcher after the catalog fixture must DEPEND on it:
      @pytest.fixture
      def emitted(events_runtime: None, terp_events: InstallEvents) -> list[object]:
          ...
Getting it the wrong way round is silent: the tap installs first, the catalog fixture
overwrites it, and the recorder simply records nothing.
""",
    "jobs": """\
Background jobs (terp.core.enqueue + JobCatalog)

- Declare typed jobs in your control plane (never bare strings), with a payload SCHEMA
  (cap its strings) and a handler resolved BY NAME:
      class SyncPullPayload(BaseSchema):
          source: str = Field(max_length=100)
      def pull(ctx: JobContext, payload: SyncPullPayload) -> None:
          MyService().create(ctx.session, ...)     # writes are audited + actor/tenant-stamped
      SYNC_PULL = JobDefinition(name="sync.customers.pull",
                                payload_schema=SyncPullPayload, handler=pull)
      job_catalog = JobCatalog([SYNC_PULL])        # rejects duplicate names
  Put the catalog on the control plane (ControlPlane(jobs=job_catalog)) and list it on the
  module (ModuleSpec(jobs=[SYNC_PULL])) so boot validates it. Reference catalog constants
  only - the jobs_reference_catalog rule forbids a bare string or inline JobDefinition(...).
- Enqueue through the typed chokepoint (never a raw queue), which rejects an unregistered
  or shadowed job:
      enqueue(session, job=SYNC_PULL, payload=SyncPullPayload(source="crm"),
              idempotency_key="customers-2026-06-29")
  A handler chains follow-up work the same way: enqueue(ctx.session, job=..., payload=...).
- Pass IDS, not entities - the payload must round-trip JSON (model_dump(mode="json")).
  Delivery is at-least-once, so make handlers idempotent (the idempotency_key + your own
  unique keys). Never read ambient request state in a handler - there is none in a worker;
  use ctx.session / ctx.actor_id / ctx.tenant_id, all re-bound from the envelope.
- The default InProcessJobQueue runs the handler inline in its own audited unit (dev /
  single-process). A user-less job runs as the control-plane system actor
  (ControlPlane(job_system_actor_id=...)), so its writes are never unstamped. For real
  off-request execution + durability, wire a durable adapter and require it at boot:
      create_app(specs, ..., job_queue=<durable>, require_durable_jobs=settings.is_production)
- The system actor CANNOT update or delete a user's OwnedMixin row. It remains a
  different actor from the owner. The built-in owner gate and registered object-authz
  predicates compose fail-closed (AND). Predicates can narrow authority but never grant
  an override. Cross-owner maintenance requires a reviewed maintenance-authority
  capability. If none is installed, stop and report the missing capability — never
  remove OwnedMixin or author a destructive owner-column migration.
- Trigger a scheduled job from any cron / k8s CronJob / systemd or cloud timer:
      terp jobs run sync.customers.pull --payload '{"source": "crm"}'
  Inspect the declared jobs:  terp jobs list   /   terp inspect jobs.
- Declare a schedule (ScheduleDefinition: a cron + a catalog JobDefinition) on the control
  plane (ControlPlane(schedules=ScheduleCatalog([...]))); boot validates each schedule's job
  against the JobCatalog. Run schedules in-process with `terp jobs scheduler` (APScheduler;
  needs terp-cap-scheduler-apscheduler) or via Celery beat — each cron tick enqueues through
  the same typed seam, so a scheduled job stays audited + system-actor stamped.
""",
    "outbox": """\
Durable post-commit delivery (outbox capability)

- The problem it solves: an in-process dispatcher runs the side effect AFTER the commit,
  outside the transaction - so a crash between the two loses it, and a rollback after it
  already fired published a lie. The outbox writes the INTENT to a table in the SAME
  transaction as the row, and a separate worker delivers it afterwards.
- terp-cap-outbox is a LIBRARY capability: it ships no router and nothing auto-mounts.
  You swap the two seams at the composition root:
      create_app(specs, ..., job_queue=OutboxJobQueue(),
                 event_dispatcher=outbox_event_dispatcher)
  It ships its own migrations, so add the dependency and run `terp migrate` before
  switching the seams over.
- Nothing in a module changes. You still enqueue(session, job=..., payload=...) and
  still emit events through the catalog; the seam is swapped once, centrally, so a
  module never knows whether delivery is in-process or durable.
- A custom side effect joins the same atomic unit through the service's _after_write
  hook (which runs inside the write transaction, before the commit):
      def _after_write(self, session, entity, *, action):
          enqueue(session, job=RUN_START, payload=RunStartPayload(run_id=entity.id))
- Run the relay as its own process (not inside the API container):
      terp jobs worker
  It leases rows (claim_id + locked_until, SKIP LOCKED), delivers AT LEAST ONCE, retries
  with exponential backoff, and dead-letters once max_attempts is exhausted. Every
  handler must therefore be safe to run twice - see `terp guide idempotency`.
- In production, refuse to boot on the in-process default:
      create_app(..., job_queue=OutboxJobQueue(),
                 require_durable_jobs=get_settings().is_production)
""",
    "idempotency": """\
Idempotency (the Idempotency-Key header, terp.core.idempotency)

- Already wired: create_app installs the idempotency middleware for every unsafe method
  (POST/PUT/PATCH/DELETE). There is nothing to decorate and no per-route opt-in - the
  CLIENT opts in per request by sending a header:
      Idempotency-Key: <client-generated unique key>
  A request without the header behaves exactly as it did before.
- The semantics, all typed envelopes:
      first call                -> executes; the response is stored under the key
      retry, same body          -> the stored response is replayed
                                   (response header idempotency-replayed: true)
      same key, different body  -> 422 idempotency_key_mismatch
      still executing           -> 409 idempotency_in_flight   (Retry-After: 1)
      malformed key             -> 400 invalid_idempotency_key
      store unavailable         -> 503 idempotency_unavailable (fail closed - never a
                                   second write)
- Use it wherever a retry must not create a second row: starting a run, submitting a
  payment, POSTing a snapshot from a worker that retries on a network error. Document
  the header on those routes so the caller actually sends one.
- The default InMemoryIdempotencyStore is PER PROCESS - correct for dev and a single
  replica, useless across replicas. A multi-replica deployment needs a shared store, and
  should refuse to boot without one:
      create_app(..., idempotency_store=RedisIdempotencyStore(...),
                 require_shared_idempotency_store=get_settings().is_production)
  Only a store that marks itself shared (mark_shared_idempotency_store) satisfies the
  guard, so a load-balanced deployment cannot silently lose the guarantee.
  Until you opt in, a production boot logs a WARNING saying idempotency is deduplicated
  per worker - the property is stated where you can read it before scaling, because
  after scaling the only symptom is duplicate rows with nothing to connect them to.
- Background work carries its own key: enqueue(..., idempotency_key="customers-2026-06-29").
  Job delivery is at-least-once, so a handler must ALSO be safe to run twice on its own -
  a natural unique constraint in the database is the strongest form of that.
""",
    "realtime": """\
Realtime push (realtime capability)

- Install terp-cap-realtime; it is a routed capability, so discovery mounts it:
      create_app(specs, discover_capabilities=True,
                 capability_names=(..., "realtime"))
- Declare every channel ONCE at import time, with a typed outbound model and the
  authorization it demands - never a bare topic string:
      class RunProgress(BaseModel):
          run_id: uuid.UUID
          state: str = Field(max_length=32)
          done: int = Field(ge=0)
      RUN_PROGRESS = register_channel(
          RealtimeChannel("runs.progress", RunProgress, requirement=Roles.VIEWER))
  RealtimeChannel(name, outbound_model, mode="sse"|"websocket", requirement=...,
                  inbound_requirement=..., inbound_model=..., on_message=...,
                  audience=principal_audience | global_audience). The default audience is
  the principal, so a message reaches only the user you address it to.
- Publish from a service, an _after_write hook, or a job handler; the payload is
  validated against the channel's outbound_model:
      await publish(RUN_PROGRESS, RunProgress(...), audience=str(principal.id))
- Wire the runtime seams once at the composition root:
      configure_realtime(permission_enforcer=..., principal_validator=...,
                         message_session_provider=...)
  configure_broker / configure_ticket_store replace the in-memory defaults when you run
  more than one replica (the in-memory ones are per process).
- Transport is TICKET-based, never a token in a URL: the client POSTs
  /api/v1/realtime/tickets, receives a one-use short-lived ticket, then connects to
  /api/v1/realtime/sse/<channel>?ticket=... (or /ws/<channel> in websocket mode). The
  channel's requirement is enforced when the ticket is minted.
- Frontend: useRealtimeChannel({ channel: "runs.progress", validate }) from
  @terpjs/react-core performs the whole dance. Never hand-roll EventSource or WebSocket -
  the boundary lint refuses both.
- Inbound (websocket) messages are size-capped, validated against inbound_model, gated by
  inbound_requirement, and handled by on_message with a real session - so a client message
  goes through the same audited service path as an HTTP write.
""",
    "files": """\
File objects (files capability, ADR 0056/0057)

- Upload/download/list/rename/delete ride the admin-only discovered router at
  /api/v1/files; File composes OwnedMixin, so rename/delete are owner-gated centrally.
- Bytes live behind the StorageBackend port (put/open/delete, streamed via file-like
  objects) in a NAMED-PROFILE registry;
  metadata (name, type, size, sha256, storage_key, storage_profile) lives in the platform
  DB. storage_key/storage_profile never leave the boundary (FileRead omits both).
- Any provider is an adapter subclass (local ships; S3/Azure/NAS are each a
  StorageBackend). Register each store once at the composition root:
      register_storage_backend("azure-invoices", AzureBlobStorage(container="invoices"))
      register_storage_backend("azure-hr", AzureBlobStorage(container="hr"))
  Keep credentials in settings / sealed config — never in module code.
- Pick the store per module (subclass default) or per call — never from a client:
      class InvoiceFileService(FileService):
          storage_profile = "azure-invoices"
      service.store(session, filename=..., content_type=..., source=..., profile="azure-hr")
  Resolution is FAIL-CLOSED: an unknown profile raises (UnknownStorageProfileError)
  before any byte lands; load/remove always resolve the store the ROW itself names.
- Uploads stream (never fully buffered) under a 25 MiB default cap; the files spec
  declares its own request-body allowance so the kernel's global max_request_bytes
  (1 MiB default) is lifted for /api/v1/files ONLY (ADR 0067). Retune per deployment
  with two composition-root lines (the request allowance must exceed the stored cap
  by multipart framing headroom):
      configure_upload_limit(100 * 1024 * 1024)
      create_app(..., request_size_overrides={"files": 100 * 1024 * 1024 + 65536})
- Content types are allowed by default (descriptive metadata); a deployment narrows
  uploads to an allowlist with one composition-root line — enforced in the service
  chokepoint (typed 415, before any byte lands), so no upload path can bypass it:
      configure_allowed_content_types(["application/pdf", "image/*"])
- Referencing a file from your own model? Declare it — never a bare uuid column (the
  no_raw_file_references rule enforces this on table models):
      class Invoice(BaseTable, table=True):
          attachment_file_id: uuid.UUID | None = FileRef()
  Serve it THROUGH your own already-authorized row (serve-through delegation): load the
  invoice via your own service (its policy + row scope decide visibility), then
      row, data = FileService().load_for(session, invoice, "attachment_file_id")
  load_for fail-closes on an undeclared reference; /api/v1/files itself stays ADMIN-only.
""",
    "capability": """\
Using capabilities

- Capabilities are opt-in packages (terp-cap-*). Every scaffolded app already has the
  BASE PROFILE — auth, identity, users, groups, access, audit — so authentication,
  accounts, group membership, permission checks and the audit trail are wired before you
  write anything. Install the others you need.
- SEE WHAT EXISTS BEFORE YOU BUILD IT:
      terp inspect capabilities
  lists every maintained capability, whether this app already has it, the exact
  `uv add` line and the composition-root wiring it expects. Durable delivery, realtime
  push, tenancy, files, webhooks, scheduling and shared multi-replica state are all
  already solved — hand-rolling one of them is a defect, not a shortcut.
- A routed capability self-registers: create_app(specs, discover_capabilities=True)
  mounts it at /api/v1/<name> via its entry point — no composition-root edit.
- A library capability (tenancy, eventbus) ships no router; you import and wire it
  (a mixin/service, a dispatcher) where needed.
- Compose the app once:
      create_app(specs, principal_provider=..., control_plane=...,
                 audit_sink=persist_audit, event_dispatcher=dispatch_in_process,
                 permission_enforcer=enforce_permission, discover_capabilities=True)
- You can always drop to native FastAPI/SQLModel — the same gate rules still apply.
- Outbound HTTP is a capability concern, never a module concern: importing httpx /
  requests / urllib.request / urllib3 / aiohttp in a module is refused by the
  no_raw_outbound_http rule — SSRF protection, egress allowlists and timeout policy
  belong behind one declared capability, not scattered per call site.
- Credentials never live in module source: a credential-shaped assignment (password,
  api_key, token, ...) to a string literal — or a recognizable secret-token literal
  anywhere — is refused by the no_hardcoded_credentials rule. Wire secrets through
  settings / sealed config (ADR 0055), never source.
""",    "migrations": """\
Database migrations (terp migrate)

- Each table-owning package (capability or app module) owns an INDEPENDENT, linear
  Alembic history with its own alembic_version_<label> table - no shared graph and no
  CROSS-package merges. Terp discovers them; you never hand-write env.py.
- Author a revision after changing a model (autogenerated, scoped to that package so
  it never proposes another package's tables):
      terp migrate make <label> -m "add invoice.status"   # <label> e.g. invoices
  Autogenerate DIFFS A LIVE DATABASE AT HEAD, so it needs two things the default
  environment does not give you: a database that outlives the process (the settings
  default is in-memory SQLite) and one that is already at head (a fresh file database
  is behind). Both, in one paste, with a throwaway file you delete afterwards:
      DATABASE_URL="sqlite:///./.migrate-scratch.db" terp migrate upgrade
      DATABASE_URL="sqlite:///./.migrate-scratch.db" terp migrate make <label>
  (PowerShell: $env:DATABASE_URL='sqlite:///./.migrate-scratch.db')
  Point it at your real Postgres URL instead when the revision must diff against real
  schema, or pass --no-autogenerate to author an empty revision by hand.
  Cross-module / cross-package foreign keys just work: every package's models are
  imported so an FK target (a sibling module, or identity_user) resolves at make time,
  and upgrade is ordered by FK dependencies so a referenced table is always created
  before the table that references it - regardless of label ordering. (A cross-package
  FK *cycle* cannot be ordered and fails closed; break it with a nullable FK populated
  in a later migration.)
- Apply / inspect / roll back across every package:
      terp migrate upgrade                 # each package to head (run on deploy)
      terp migrate upgrade --sql > release.sql   # render DBA-reviewable offline SQL
                                           # instead (nothing connects; flat layout)
      terp migrate status                  # current-vs-head per package
      terp migrate downgrade               # every package back to base (or -N)
      terp migrate downgrade --label notes --revision <rev>   # one package only
  A concrete revision is package-specific, so the all-package downgrade takes only
  base or a relative -N; pass --label to roll one package to any of its own revisions.
- Two developers branched the same package? Resolve the within-package divergence:
      terp migrate heads                   # more than one head = diverged
      terp migrate merge <label> -m "merge"
- Destructive DDL (drop table/column or alter-column type changes) is refused by
  `terp check` unless the operation carries `# arch-allow-no-destructive-migrations:
  <reason>` on (or immediately above) its line, budgeted by the escape-hatch ratchet.
- MOVING A MODEL TO ANOTHER MODULE is the one edit that looks free and is not. Just
  moving the class emits NO ddl at all - the losing package stops owning the table so
  its scoped autogenerate cannot propose a drop, and the gaining package diffs against
  a database where the table already exists so it proposes no create. Your database
  keeps upgrading; CI and staging stay green. Then the NEXT ordinary change to that
  model (an added column) is authored into the gaining package's INDEPENDENT history,
  which - with no foreign key between the two packages - a fresh install may run
  BEFORE the history that creates the table: "no such table", months later, in a new
  environment, blamed on an innocent add_column. Terp refuses the split at `terp
  migrate make` and in the build-time guard. Move a table properly, expand/contract:
      1. Give the new module its own model with its own __tablename__;
         `terp migrate make <new>` creates it.
      2. Copy the rows in that same release (a data migration, or a backfill job),
         and write to both tables while the old one still has readers.
      3. In a LATER release, once nothing reads the old table, drop it - with
         `# arch-allow-no-destructive-migrations: <reason>` and a human reviewer.
  Step 3 stays human-reviewed on purpose: dropping a populated table is a genuine,
  irreversible risk, and the one place where a second pair of eyes is worth the
  friction. If the model is simply in the wrong module and holds no data you care
  about, the cheap fix is to move the class BACK and rename the module instead.
  Already shipped the move and planning the expand/contract for a later release? The
  owning package's models.py may carry `# arch-allow-table-ownership-is-not-split:
  <reason>`, counted by the escape-hatch budget like any other opt-out.
- Adopt Terp on an EXISTING database (built by create_all or by hand) without dropping
  data - baseline each history at head, then only genuinely new migrations apply:
      terp migrate stamp                   # records head, runs no DDL
- Want physical per-module separation on PostgreSQL (each package's tables in its own
  schema, the groundwork for per-schema GRANTs)? Set DB_SCHEMA_LAYOUT=per-module for a
  fresh database, or move an existing flat one in place (idempotent, data moves with
  the tables, version tables stay put):
      terp migrate adopt-schemas           # one-time; ADR 0070
- Least-privilege runtime (ADR 0071): migrate as the owning role, run the app as a
  separate login that holds ONLY DML - the database itself then refuses DDL and
  (per-module) any tampering with migration state. Provision the login yourself, then:
      terp migrate grant-runtime <role>    # idempotent; run after upgrade/adopt
  Run it as the role that runs `terp migrate` - or pass --owner-role <role> so the
  ALTER DEFAULT PRIVILEGES it emits covers tables that future upgrades create.
  Module-to-module DML is deliberately NOT database-blocked (one runtime role spans
  every write schema; audit/outbox ride the business write's single session).
- Operate safely: run `terp migrate upgrade` ONCE per deploy (e.g. a release job), not
  on every replica - it takes no lock, so concurrent runs race. The boot guard below is
  read-only and safe on every replica. The migration engine is built from DATABASE_URL,
  so put URL-expressible options (e.g. sslmode) there.
- Run from your app root so app/ is importable (app modules ship their history in
  app/modules/<name>/migrations/; a capability declares a terp.migrations entry point).
- Make upgrading non-optional: wire the fail-closed boot guard so the app refuses to
  start against a stale schema (a deploy that skipped the upgrade fails loudly). Pass an
  app_root so it guards your app modules too, not only capabilities:
      from functools import partial
      from pathlib import Path
      from terp.migrations import assert_migrations_current
      create_app(specs, ..., migration_check=partial(
          assert_migrations_current, app_root=Path(__file__).parent))
  Gate it on production if local dev builds the schema with create_all / SQLite.
- Test the REAL migration path (not only create_all) so a model change with no
  migration fails CI, not production:
      from terp.migrations import upgrade, assert_migrations_match_models
      upgrade(db_url, app_root); assert_migrations_match_models(db_url, app_root)
""",
    "frontend": """\
Frontend module screens (@terpjs/react-core)

- A module's frontend slot is frontend/src/modules/<name>/ with a module.tsx manifest;
  everything composes the token-styled @terpjs/react-core surface. The full catalog (with
  per-export "Use" guidance) is the @terpjs/react-core README; each export also carries
  JSDoc, so your editor shows the same guidance inline.
- The boundary lint (@terpjs/eslint-boundaries) refuses, fail-closed:
    raw <button>/<input>/<select>/<textarea>   ->  Button / Input / Select / Textarea
    raw <table>                                ->  DataView          (terp guide dataview)
    raw <dialog>                               ->  ConfirmDialog
    raw <form>                                 ->  Stack as="form"   (terp guide forms)
    raw fetch / XMLHttpRequest                 ->  useTerpClient() + unwrap (typed client)
    WebSocket / EventSource / sendBeacon       ->  the generated client (one egress path)
    style={} / className / module stylesheets  ->  layout via Stack/DetailList; design tokens
    <a href="/...">                            ->  the router's Link (role-aware, no reload)
    deep imports (@terpjs/*/src, @terpjs/*/dist)   ->  import from the package root only
- Frontend security defaults (each its own lint rule, same error-only footing):
  dangerouslySetInnerHTML and DOM HTML-injection sinks (innerHTML/outerHTML/
  insertAdjacentHTML/document.write) are refused — render text, or Markdown from
  @terpjs/react-core for rich text; eval() / new Function() are refused; javascript:
  URLs in href/src are refused; a static target="_blank" link needs rel="noopener".
- Every routed view renders a page archetype (Page / OverviewPage / DetailPage / HubPage);
  buildAppRouter refuses an unframed view at runtime, fail closed. An app can ratchet
  further with an opt-in slot-typed layout contract (terp guide layouts).
- Route paths and params are CHECKED, from generated types (ADR 0092). The router is built
  at runtime from the manifests, so nothing type-checks a path or a param name until you
  generate the table from those manifests:
      uv run terp routes            -> writes the committed frontend/src/routes.gen.d.ts
  Then read and navigate through the checked seams:
      const { recordId } = useRouteParams("/records/:recordId");   // exact, per route
      const recordId = useRouteParam("recordId");                  // one param
      navigate({ to: "/records/:recordId", params: { recordId } }); // useTerpNavigate()
  Paths use the manifest spelling (":id", not "$id"). Regenerate after changing a manifest
  route — `terp verify` refuses a stale table (the routes-drift check) and names the
  command. A path that is not a plain string literal is refused, with its file and line:
  a partial table would turn a real path into a type error.
- User-facing text props are UiText (a plain string, or {id, message} for localization).
- Data always flows through the generated client: useTerpClient() (typed from the backend
  OpenAPI export) and unwrap(...) which throws a typed ApiError carrying code/status.
- The one governed opt-out is a justified `// terp-allow-<rule>: <reason>` marker whose
  counts must exactly match the app's checked-in escape-hatch-budget.json (a ratchet).
- Run the lint locally: npm --prefix frontend run lint (part of the gate).
""",
    "dataview": """\
Data collections (DataView)

- DataView is the single sanctioned surface for data collections — a raw <table> is
  refused by the boundary lint. It gives search, sorting, pagination, column management,
  selection + batch actions, row actions, expandable rows, and persisted view
  preferences, driven by a repository port.
- Client-side (small collections — rows already in memory). The repository owns row
  identity and value access; the component never reads a field itself:
      const repo = useMemo(
        () =>
          new InMemoryDataViewRepository(rows, {
            getRowId: (r) => r.id,
            getValue: (r, col) => r[col as keyof Row],
            searchFields: ["title", "status"],
          }),
        [rows],
      );
      <DataView repository={repo} columns={columns} viewId="notes.list" />
- Server-side (large collections — let the backend paginate/sort/filter):
      const repo = useMemo(() => new HttpDataViewRepository({...}), [client]);
  and keep query state in the URL with useServerDataView.
- Columns declare {id, header, accessor?, cell?, enableSorting?, meta?} — `id` is the
  column key the repository's getValue receives, `accessor` reads the value and `cell`
  renders it; header text is UiText. There is no `keyField` prop: row identity is
  `getRowId` on the repository. Row actions and batch actions are declared as data
  (the component renders the token-styled controls).
- Persist per-user view preferences via the ViewStateRepository seam
  (LocalStorageViewStateRepository for the browser; InMemoryViewStateRepository in tests).
- For a simple titled CRUD list (no tables), ResourceList over useResource is the
  lighter standard screen; reach for DataView when the collection needs table powers.
""",
    "forms": """\
Forms (react-core primitives)

- Raw <form>/<input>/<select>/<textarea>/<button> are refused by the boundary lint;
  compose the token-styled primitives instead:
      <Stack as="form" onSubmit={submit}>
        <Field label="Number" error={errors.number}>
          <Input value={number} onChange={...} maxLength={50} />
        </Field>
        <Field label="Status">
          <Select value={status} onChange={...}>...</Select>
        </Field>
        <Button type="submit" variant="primary">Save</Button>
      </Stack>
- Field wraps label + control + hint/error for one field; Stack (vertical by default)
  is the layout — never style={} / className / a module stylesheet.
- Submit through the typed client: const client = useTerpClient();
  await unwrap(client.POST("/api/v1/invoices/", { body })); a failure throws ApiError
  ({code, status, requestId}) — map codes to copy with useErrorMessage, show transient
  success/failure with useToast(), and confirm destructive actions with ConfirmDialog.
- Updates carry the row's `version` (optimistic concurrency): send the version you
  read; a 409 version_conflict means reload-and-retry, surfaced via ErrorState copy.
- Mirror the backend's input caps client-side (maxLength on Input matching the schema's
  Field(max_length=...)) so users see the limit before the 422 does.
""",
    "theming": """\
Theming and branding (design tokens, palettes, the brand mark)

- EVERY style is a design token. The react-core primitives paint from CSS custom
  properties shipped by @terpjs/contract (tokens.css), which is why the boundary lint
  refuses `style={}`, `className` and module stylesheets: a module that painted itself
  would not follow the palette. Modules never need theme-specific code.
- THE SHIPPED PALETTES, plus "system":
      light  dark  midnight  twilight  contrast
  `contrast` is a high-contrast light set. The active one is `data-theme` on <html>;
  the shell header's theme toggle offers all five plus "system" (follow the viewer's
  own platform preference) and persists the choice. `system` resolves to the dark set
  when the platform asks for dark.
- TO CHANGE HOW YOUR APP LOOKS, redefine tokens in `frontend/src/theme.css`. It is
  imported immediately after tokens.css and therefore wins the cascade. Declare only
  what you are changing; everything else falls back to the framework's value.

      :root { --color-brand-primary: #2563eb; }
      [data-theme="dark"] { --color-brand-primary: #60a5fa; }

  Per palette, use that palette's selector. A token with no palette selector is
  declared in `:root` and governs every palette at once — which is what you want for
  spacing, corners and typography, and usually not what you want for a colour.
- TO SHIP ON A PALETTE OTHER THAN light, name it in the layout declaration — never by
  restyling one palette to imitate another:

      frontend/layout-contract.json -> { "defaultTheme": "midnight" }

  Legal values are the five above plus "system". Passing `defaultTheme` as a bootstrap
  option as well is refused (terp guide layouts).
- THE BRAND MARK is a path, not JSX. Put the file in `frontend/public/` (Vite serves
  that directory at the site root) and declare it:

      "shell": { "brand": { "logo": "/logo.svg", "logoDark": "/logo-dark.svg" } }

  `logoDark` is picked automatically under a dark palette — most company logos have
  fixed colours and cannot survive one, and several of the shipped palettes are dark.
  The shell sizes the mark itself, in a box of `--shell-brand-size`; move that token in
  theme.css rather than scaling the image. An app that wants an inline SVG or a
  component can still pass the `logo` bootstrap option instead — declaring both is
  refused. The browser TAB mark is separate and cannot be declared: a browser reads it
  from `index.html` before any app code runs, so edit the <link rel="icon"> there.
- WHICH TOKENS EXIST is published, not guessed: @terpjs/contract ships
  tokens.manifest.json (every token, its category, its per-palette values, and whether
  a palette may vary it). Spacing, corners, typography, motion and z-index are
  theme-INVARIANT by design — declare them once in `:root`. An app whose spacing
  changed when someone switched palette is not what anyone means by a theme.
- CONTRAST is measurable, so measure it: @terpjs/contract carries a WCAG contrast suite
  over the shipped palettes. If you override a foreground or a background, check the
  pairing rather than trusting the eye.
""",
    "layouts": """\
Layout contracts (slot-typed layouts, ADR 0079)

- A layout contract is an OPT-IN ratchet above the page archetypes: not just "every
  routed view is framed", but "this archetype's body holds only these components".
  It is enforced two-layer and fail-closed, and every failure message tells you the
  contract, the slot, what was found, what is allowed, and the concrete fix — let it
  guide you.
- Opt in ONCE, in the file. `frontend/layout-contract.json` is the app's layout
  DECLARATION: the `terp/layout-contract` lint rule finds it on disk and `main.tsx`
  imports it, so one line governs both halves.

      frontend/layout-contract.json          -> { "contract": "standard" }

  Declaring the same fact in code as well — `renderTerpApp({ layoutContract: "..." })`
  — is REFUSED when the router composes, by name:

      frontend/layout-contract.json and the bootstrap options both declare "contract"
      (file: "standard", code: "standard"). Declare each in one place: the file is what
      a tool can read and rewrite, so prefer it and drop the option.

  (This recipe used to say "keep them in sync". It was the last copy of an instruction
  to maintain a duplicate, and the duplicate is now a startup error.)
  No config = no checks (fully backwards compatible; an existing app can switch later
  and fix screens by following the enforcement messages).
- The same file carries the rest of the app's declared shape, each key optional and each
  refused as a duplicate if it is also passed as a bootstrap option:
      defaultTheme            the palette the app opens on (terp guide theming)
      shell.density           "comfortable" | "compact"
      shell.navPlacement      "sidebar" | "header"
      shell.contentWidth      "full" | "measured"
      shell.brand             { "logo": "/logo.svg", "logoDark": "/logo-dark.svg" }
                              -- paths under frontend/public/, served from the site root
      shell.navGroups         [ { "id": "work", "label": "Workspace", "order": 1 } ]
                              -- label "" renders the group with no heading; a module's
                                 manifest names the group it belongs to
  A value off its enum, an unknown key, and a fact declared twice are three separate
  refusals, each naming the file, the key and the legal alternatives. The vocabulary is
  published as JSON at @terpjs/react-core/layout.manifest.json, so a tool (or an agent)
  can read what is legal instead of guessing.
- The "standard" contract governs the body slot of each archetype:
      HubPage      -> HubCard only (a card grid landing)
      OverviewPage -> DataView / ResourceList / ModuleNav / Stack / Card / Divider /
                      Text + the framework states (EmptyState / ErrorState /
                      LoadingState / Alert) and ConfirmDialog
      DetailPage   -> DetailList / Stack / Grid / Tabs / ModuleNav / DataView / Card /
                      Divider / Text + the same framework states and ConfirmDialog
  Grid is a DETAIL-body component and not an overview one, deliberately: an overview
  body is a data collection, and a grid of summary cards is a hub — which has its own
  archetype. Heading is admitted nowhere: a heading in a governed body must OWN its
  section, and Card (boxed, or variant="plain" for no chrome) is how a section is
  owned; a bare heading with siblings after it is a grouping the check cannot see.
  The plain Page stays unconstrained — it is the sanctioned home for a bespoke screen.
  Only the slot's DIRECT children are governed: an allowed container's own subtree
  (a Card's body, a Stack's rows) is yours to compose — nesting content inside an
  allowed component is sanctioned composition, not an escape.
- Enforcement (never lint-only):
      build time  -> the terp/layout-contract ESLint rule checks the static JSX
                     children of each governed archetype (npm --prefix frontend run lint)
      runtime     -> the archetypes verify the rendered DOM children (each sanctioned
                     component stamps a data-terp marker) and refuse the view, fail
                     closed — so dynamic children a linter cannot see are still governed.
- The one opt-out is the governed escape hatch: a justified
  `// terp-allow-layout-contract: <reason>` marker on the violating line, counted
  against the app's checked-in escape-hatch-budget.json (a ratchet). A recurring
  legitimate need should become a contract allowance, not an opt-out.
""",
    "environment": """\
Runtime environment variables: the two seams, and which one wins

TWO SEAMS, ONE DIRECTION OF PRECEDENCE

  .app.env   the variables the app DECLARES in environment.schema.json. Studio renders
             exactly the declared keys into this file, per environment; the compose
             profiles forward it (`env_file:`). This is how app configuration reaches
             production. Locally: `cp .app.env.example .app.env`.

  .env       compose's own file, read automatically from the project directory. It feeds
             the `${...}` interpolations in docker-compose.yml -- the platform's wiring
             (SECRET_KEY, API_PORT, WEB_PORT) and values only the host resolves.
             Gitignored; the developer's alone.

Compose resolves `environment:` OVER `env_file:`. A variable named in BOTH a compose
`environment:` block and .app.env is therefore supplied by .env, and the .app.env copy is
discarded -- silently, in every environment. This is not merely a stale-override risk:

    environment:
      FOO: ${FOO:-}        # with no .env at all, FOO is set to "" -- and still wins

so there is no configuration in which the declared value arrives. A literal
(`FOO: http://api:8000`) discards it just as completely.

  Rule: ONE OWNER PER VARIABLE. Either the app declares it (.app.env is its seam, and it
  must not appear in any `environment:` block), or compose owns it (and it must not be
  declared). `terp verify --only env-seams` fails the gate on the overlap, naming the
  variable, the file, and the services -- no Docker daemon needed, it reads the two files.

HOST vs CONTAINER vs BROWSER

An address is resolved by exactly one party, and one value cannot be right for two. This
is NOT derivable from the variable's name or type, so the manifest records it:

    "MY_API_BASE_URL": { "type": "string", "resolvedBy": "container" }

  container   a service on the compose network dials it -> use the SERVICE NAME
              (http://api:8000). A loopback address here is the container ITSELF: the
              classic failure is setting the host value (127.0.0.1:8000), which is right
              for a CLI run from your shell, and watching every one-shot exit 1 with
              "Connection refused" from inside the network.
  host        your shell dials it, outside the network -> http://127.0.0.1:8000
  browser     the user's browser is sent there -> a host address. OIDC_REDIRECT_URI is
              the canonical case, and the reason it is legitimately a .env forward rather
              than a declaration: the IdP redirects a BROWSER, so localhost is correct.

`env-seams` refuses a "resolvedBy": "container" variable whose value is a loopback host.

THE MANIFEST'S OWN SHAPE (Studio fails closed on the WHOLE file)

Studio's reader refuses the entire manifest on the first defect -- every declared
variable, the app's secrets included, then disappears from the environment form and is
never rendered into .app.env. One over-long `description` costs the app its whole
configuration, so `env-seams` checks the shape first and reports every defect at once:

  - `"type": "object"`, `properties` an object, `required` a list of declared names.
  - at most 50 variables.
  - names match ^[A-Z][A-Z0-9_]{0,63}$; platform-owned names and VITE_* are refused.
  - type/title/description/format/group/resolvedBy are STRINGS OF AT MOST 500 CHARACTERS.
    This is the one an authoring agent walks into: a description that explains the
    variable well is easily longer than that. Write the long version in AGENTS.md or the
    code, and keep the manifest's to a sentence or two.
  - resolvedBy is one of host | container | browser.
  - enum is a list of at most 50 strings of at most 200 characters each.

Unknown fields are dropped rather than refused, so anything outside that set is not
carried to Studio -- do not encode meaning in one.

WHEN A FEATURE ADDS A VARIABLE

1. Declare it in environment.schema.json (UPPER_SNAKE; `"format": "secret"` for tokens,
   passwords, API keys and client secrets; `"resolvedBy"` for addresses).
2. Do NOT add it to a compose `environment:` block -- that would kill the declaration.
3. Add a workbench value to .app.env.example, so the inner loop runs the deployed seam.
4. `terp verify --only env-seams`.

Never write a secret value into the manifest, .env.example, .app.env.example, source,
tests, prompts or logs. Platform-owned names (SECRET_KEY, POSTGRES_PASSWORD, DATABASE_URL,
ENVIRONMENT, WEB_PORT, BACKEND_CORS_ORIGINS) are refused in the manifest: they already
have an owner.
""",}

# Topics whose body is generated from a live registry (not a static recipe above).
_GENERATED_TOPICS: tuple[str, ...] = ("changelog", "rules")

_RULE_GUIDE_DETAILS: dict[str, str] = {
     "no_raw_outbound_http": """\
Compliant decision path for outbound HTTP

1. Preserve the requested integration and its external contract. Removing the live
    call, returning static/local data, or moving the client import to an unscanned
    helper only to make the gate green is not a compliant fix.
2. Use a maintained purpose-built capability when its semantics match. For example,
    terp-cap-webhooks owns signed webhook POST delivery; it is not a generic GET client.
3. The maintained Terp capability surface currently has no generic outbound-fetch
    capability for arbitrary HTTP GETs. App modules therefore cannot implement a live
    news/feed fetch through a sanctioned generic API today.
4. When no matching capability exists, stop and report the missing capability. Leave
    the check red until a human approves an escape hatch or the platform supplies a
    reviewed adapter capability. Do not create an app-local helper package merely to
    move the raw client outside the scanner.
5. A new adapter capability must expose a narrow domain API and centrally enforce a
    fixed destination allowlist, HTTPS, SSRF-safe DNS/IP handling, redirect policy,
    bounded timeouts and response sizes, credentials from settings, and egress audit.
    App modules import only that declared capability's public domain seam.
""",
}


def guide_topics() -> tuple[str, ...]:
    """Every ``terp guide`` topic, sorted: the static recipes + the generated ones.

    The single source of truth for the CLI topic ``choices`` *and* the docs-parity
    test, which derives its per-topic coverage from this rather than re-listing topics.
    """
    return tuple(sorted([*_GUIDE_TOPICS, *_GENERATED_TOPICS]))


def guide_choices() -> tuple[str, ...]:
    """Every accepted focused guide name: broad topics plus exact architecture rules."""
    from terp.arch.rules import GUIDE_TOPIC_BY_RULE

    return tuple(sorted({*guide_topics(), *GUIDE_TOPIC_BY_RULE}))


_TOPIC_NAMES = ", ".join(guide_topics())

_GUIDE_OVERVIEW = f"""\
Terp — secure-by-default application platform (authoring guide)

You write small modules; the framework enforces auth, audit, optimistic concurrency,
pagination, input caps and row scoping for you. A green gate (`terp check` /
`uv run pytest`) means your code is compliant — the architecture rules fail closed with
precise, fixable messages, so let them guide you.

Canonical module shape (modules/<name>/):
  models.py    table models (inherit BaseTable)
  schemas.py   request/response DTOs (BaseSchema / BaseUpdateSchema)
  service.py   business logic (subclass BaseService)
  router.py    thin HTTP layer (APIRouter over the service + SessionDep)
  module.py    the ModuleSpec manifest (name + router + Policy)

Golden rules (the gate enforces these — follow them and it stays green):
  1. Table models inherit BaseTable; never redeclare id/created_at/updated_at/version.
  2. Services subclass BaseService; CRUD is inherited. Add read filters via
     business_filters(); never override base_query (it would drop soft-delete/tenant scope).
  3. Every write goes through the service (create/update/delete, or self._save/_remove);
     never call session.add/commit/execute yourself — the audit trail is automatic.
  4. Every module declares a ModuleSpec with a Policy (deny-by-default); a truly public
     route opts in with Policy.public(reason="...").
  5. Routes set response_model to a Read DTO (never the table model); paginate lists (Page[T]).
     A POST that computes and never writes (validate, preview, cost) declares
     @read_only under its route decorator — the gate and the chokepoint then hold it to
     that, instead of it being pure only until someone adds a line.
  6. Cap every input string: Field(max_length=...).
  7. Import only the terp.core public surface + your declared capabilities — never
     terp.core._internal, never a sibling module.

More:  terp guide <topic>   (topics: {_TOPIC_NAMES})
    terp guide <rule>            (the exact rule's remediation and related pattern)
       terp guide rules             (every architecture rule the gate enforces, generated)
       terp --version               (which platform you are on; warns on mixed pins)
       terp guide theming           (palettes, design tokens, the brand mark)
       terp guide changelog         (what changed — read this before and after a bump)
       terp upgrade --check         (is there a newer release for the whole set?)
       terp inspect capabilities    (what the platform offers: installed vs adoptable)
       terp inspect control-plane   (your roles / permissions / module authority map)
       terp inspect access          (the full access graph: modules, endpoints, data traits)
       terp check                   (run the full architecture gate locally)
"""


def _clean_doc(text: str) -> str:
    """Strip RST inline markup (``literals`` and ``:role:`targets```) for plain output."""
    text = re.sub(r":[a-zA-Z]+:`~?(?:[\w.]+\.)?(\w+)`", r"\1", text)
    return text.replace("``", "")


def _rule_headline(rule: Callable[..., object]) -> str:
    """The first line of *rule*'s docstring (its one-line summary), RST-normalized."""
    return _clean_doc(rule.__doc__.strip().splitlines()[0]).strip()


def _render_rules_topic() -> str:
    """Generate the enforced-rules list from the live ``terp.arch`` registry.

    Introspected from ``terp.arch.rules._ALL_RULES`` (each rule's name + its docstring
    headline), so a newly added rule surfaces here automatically — there is no second,
    hand-maintained rule list to drift (ADR 0030). The harness is imported lazily, so
    plain ``terp guide`` / ``terp inspect`` need not load it.
    """
    from terp.arch.rules import _ALL_RULES

    lines = [
        "Architecture rules the gate enforces",
        "",
        "Generated from the live terp-arch registry, so this list is always complete and",
        "current. Each rule is checked by `terp check` / `uv run pytest` and fails closed",
        "with a precise, fixable message naming the file, line, and fix.",
        "",
    ]
    for rule in sorted(_ALL_RULES, key=lambda item: item.__name__):
        lines.append(f"  - {rule.__name__.removeprefix('check_')}")
        lines.append(f"      {_rule_headline(rule)}")
    return "\n".join(lines) + "\n"


def _read_release_notes(
    shipped_dir: pathlib.Path, search_from: pathlib.Path
) -> str | None:
    """The release-notes text: the shipped copy first, the checkout copy second.

    Split out from the topic renderer so both legs are reachable in a test. The
    order matters: *shipped_dir* is the real delivery path for every consumer,
    and the upward walk exists only for the platform's own checkout, where
    terp-core is used from source and no wheel was ever built. If the walk could
    win, a developer here would read notes the installed platform does not carry.
    """
    shipped = shipped_dir / "CHANGELOG.md"
    if shipped.is_file():
        return shipped.read_text(encoding="utf-8")
    for parent in [search_from, *search_from.parents]:
        candidate = parent / "CHANGELOG.md"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return None


def _render_changelog_topic() -> str:
    """The platform's release notes, read from the installed ``terp-core``.

    An app cannot judge an upgrade it cannot read about. The notes ship inside
    the wheel (``force-include`` in terp-core's pyproject) precisely so this
    answers **offline, in the app's own checkout** — no repository to clone, no
    index to reach. Until this existed the template's own pyproject pointed at
    "the platform CHANGELOG", a document that shipped nowhere: the one pointer
    the code gave was a dead reference.
    """
    from terp.cli.version import platform_version

    # terp-core is a hard dependency of the CLI, so its location is always known.
    import terp.core

    shipped_dir = pathlib.Path(terp.core.__file__).parent
    text = _read_release_notes(shipped_dir, pathlib.Path(__file__).resolve().parent)
    if text is None:
        return (
            "Release notes are not available in this environment.\n\n"
            "They ship inside the terp-core wheel; an editable or partial install "
            "may not carry them.\nSee the platform repository's CHANGELOG.md.\n"
        )

    version = platform_version()
    # The notes travel with the installed wheel, so they end at the installed
    # version. A reader weighing an upgrade needs the *target's* copy — served by
    # an ephemeral CLI at that version, which never touches this app's pins.
    header = (
        f"Terp release notes (this app is on {version})\n"
        f"These notes end at {version}. For a release this app does not have yet:\n"
        f"  uvx --from terp-cli==<version> terp guide changelog\n"
        if version
        else "Terp release notes\n"
    )
    return header + "\n" + text


def _render_rule_guide(rule_name: str) -> str:
    """Render one rule's exact remediation followed by its broader authoring pattern."""
    from terp.arch.rules import GUIDE_TOPIC_BY_RULE, _ALL_RULES

    topic = GUIDE_TOPIC_BY_RULE[rule_name]
    rules = {
        rule.__name__.removeprefix("check_"): rule
        for rule in _ALL_RULES
    }
    checker = rules.get(rule_name)
    explanation = (
        _clean_doc(checker.__doc__.strip()).strip()
        if checker is not None and checker.__doc__
        else rule_name
    )
    detail = _RULE_GUIDE_DETAILS.get(
        rule_name,
        "Apply the sanctioned construct in the related authoring pattern below at "
        "the exact file and line from the finding. Preserve existing behavior and "
        "rerun the failing check; do not add an opt-out merely to turn it green.",
    )
    return (
        f"Rule: {rule_name}\n"
        f"{explanation}\n\n"
        f"{detail.rstrip()}\n\n"
        f"Related authoring pattern ({topic})\n\n"
        f"{guide(topic)}"
    )


def guide(topic: str | None = None) -> str:
    """Return the Terp authoring guide, or a focused recipe for *topic*.

    The deterministic, in-terminal instruction surface for agents (and humans): an
    agent can run ``terp guide`` without reading the installed package, learn the
    canonical module shape + the golden rules the architecture gate enforces, then
    ``terp guide <topic>`` for a copy-pasteable recipe. The ``rules`` topic is generated
    from the live ``terp.arch`` registry (ADR 0030), so it never drifts.
    """
    if topic is None:
        return _GUIDE_OVERVIEW
    if topic == "rules":
        return _render_rules_topic()
    if topic == "changelog":
        return _render_changelog_topic()
    if topic in _GUIDE_TOPICS:
        return _GUIDE_TOPICS[topic]
    return _render_rule_guide(topic)


def gate_root(root: str | pathlib.Path = ".", *, package: str = "app") -> pathlib.Path:
    """Resolve the directory the architecture gate scans, from a CLI ``--root``.

    The gate's unit of scope is the **app package** — the test harness calls
    ``assert_app_clean("app")``, so ``app/`` is what the rules walk. A CLI ``--root``,
    though, is naturally the *project* root (that is where every other ``terp``
    command runs, and the default is ``.``), which also contains code the gate does
    not govern: a standalone ``engine/``, ``conformance/``, tooling scripts. Scanning
    that made the two entry points to the same gate disagree about scope.

    So ``--root`` accepts either: if it contains the app package, the package dir is
    the scan root; otherwise *root* is already the package dir and is used as-is.
    Both spellings then hold the app to exactly the scope ``uv run pytest`` does.
    """
    path = pathlib.Path(root)
    candidate = path / package
    return candidate if candidate.is_dir() else path


def check_report(
    root: str = ".", *, package: str = "app", budget_path: str | None = None
) -> dict[str, object]:
    """The architecture gate as a structured report (the ``terp check --format json`` body).

    Machine-readable so an agent (or the Studio) never has to parse a prose wall:
    every violation carries its rule, file, line, message, the ``terp guide`` topic
    that teaches the compliant pattern, and a copy-pasteable ``fix`` command. An
    ungoverned ``# arch-allow-*`` marker (the condition ``assert_app_clean`` fails
    closed on) is reported in-band as an ``ungoverned_escape_hatch`` violation.

    ``rules`` is the evaluated-rule inventory: every rule id this run actually held
    the app to. That is the live registry plus the escape-hatch governance half that
    matches the execution mode: with a *budget_path* the budget ratchet ran (and an
    unbudgeted marker is reported as its drift, subsuming the ungoverned condition);
    without one only the ungoverned-marker condition ran — the ratchet is then left
    OUT of the inventory, so a consumer joining verdicts to the Terp Standard catalog
    can never claim ``escape_hatch_budget`` passed on a run that never enforced it
    (fail closed under version skew and configuration alike).
    """
    from terp.arch import check_app, guide_topic_for, ungoverned_marker_violations
    from terp.arch.rules import GUIDE_TOPIC_BY_RULE

    scan_root = gate_root(root, package=package)
    violations = list(check_app(scan_root, package=package, budget_path=budget_path))
    if budget_path is None:
        violations.extend(ungoverned_marker_violations(scan_root, package=package))
    violations.sort(key=lambda violation: (violation.path, violation.line, violation.rule))
    rules = set(GUIDE_TOPIC_BY_RULE)
    if budget_path is None:
        rules.discard("escape_hatch_budget")
    return {
        "ok": not violations,
        "rules": sorted(rules),
        "violation_count": len(violations),
        "violations": [
            {
                "rule": violation.rule,
                # Separator-stable ('/') on every OS: the report is a machine
                # contract consumed by agents and the Studio, not display text.
                "path": violation.path.replace("\\", "/"),
                "line": violation.line,
                "message": violation.message,
                "guide_topic": guide_topic_for(violation.rule),
                "fix": f"terp guide {violation.rule}",
            }
            for violation in violations
        ],
    }


def check_report_envelope(
    root: str = ".", *, package: str = "app", budget_path: str | None = None
) -> dict[str, object]:
    """The architecture gate as a Terp Standard **check report** (``terp check
    --format check-report``).

    The spec's ``app-check-report.schema.json`` shape: one self-describing document a
    consumer joins to the catalog without knowing this toolchain — ``spec_version``
    (the standard the rule ids resolve against), the checker identity, the run
    verdict, the evaluated-rule inventory as **catalog ids** (``backend/<rule>``),
    and findings in the finding format's shape (``fix_hint`` = the ``terp guide``
    recipe). The legacy ``--format json`` report keeps its published shape for
    existing consumers; this is the successor surface driving tools migrate to.
    """
    import importlib.metadata

    from terp.arch import SPEC_VERSION

    report = check_report(root, package=package, budget_path=budget_path)
    try:
        version = importlib.metadata.version("terp-arch")
    except importlib.metadata.PackageNotFoundError:  # a source checkout (the platform repo)
        version = "0"
    findings: list[dict[str, object]] = []
    for violation in report["violations"]:  # type: ignore[union-attr]
        finding: dict[str, object] = {
            "rule": f"backend/{violation['rule']}",
            "path": violation["path"],
            "message": violation["message"],
            "fix_hint": violation["fix"],
        }
        # The spec's line is optional and 1-based ("when the checker can locate
        # it") — a whole-tree condition (budget drift) carries line 0 internally.
        if int(violation["line"]) >= 1:
            finding["line"] = violation["line"]
        findings.append(finding)
    return {
        "terp_check_report": 1,
        "spec_version": SPEC_VERSION,
        "checker": {"tool": "terp-arch", "version": version},
        "ok": report["ok"],
        "rules": [f"backend/{rule}" for rule in report["rules"]],  # type: ignore[union-attr]
        "findings": findings,
        "unattributed": [],
    }


def _mermaid_id(prefix: str, name: str) -> str:
    """A Mermaid-safe node id (``prefix_`` + non-alphanumerics collapsed to ``_``)."""
    return f"{prefix}_{re.sub(r'[^0-9A-Za-z_]', '_', name)}"



def _load_control_plane(dotted: str) -> ControlPlane:
    module_name, _, attr = dotted.partition(":")
    module = importlib.import_module(module_name)
    candidate = getattr(module, attr or "control_plane")
    if not isinstance(candidate, ControlPlane):
        raise SystemExit(
            f"{dotted!r} did not resolve to a terp.core.ControlPlane instance"
        )
    return candidate


def _load_module_spec(dotted: str) -> ModuleSpec:
    module_name, _, attr = dotted.partition(":")
    module = importlib.import_module(module_name)
    candidate = getattr(module, attr or "module")
    if not isinstance(candidate, ModuleSpec):
        raise SystemExit(f"{dotted!r} did not resolve to a terp.core.ModuleSpec instance")
    return candidate


def inspect_access(
    dotted: str = "control_plane:control_plane",
    *,
    modules: Sequence[str] = (),
    app: str | None = None,
    app_root: str = ".",
    fmt: str = "text",
) -> str:
    """Return the access graph (text or json).

    With ``app`` (a FastAPI instance or zero-arg factory, e.g. ``app.main:build``) the
    graph covers the WHOLE composed surface — every discovered capability router and the
    kernel routes — reconciled against ``app.openapi()`` so no mounted route can hide.
    Without it, the focused form reports just the hand-passed ``modules``.

    The three-layer view — module policy, per-endpoint requirement, and the data
    layer's row-visibility / write-authority traits — is JSON-first for Studio
    (``terp inspect access --app app.main:build --format json``).
    """
    if app is not None:
        root = str(pathlib.Path(app_root).resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
        return render_access_graph(build_access_graph_for_app(_load_app(app)), fmt)
    plane = _load_control_plane(dotted)
    specs = [_load_module_spec(module) for module in modules]
    return render_access(plane, specs, fmt=fmt)


def inspect_schema(
    *,
    app_root: str = ".",
    package: str = "app",
    fmt: str = "text",
) -> str:
    """Return the schema graph for the app at *app_root* (text or json).

    Loads every declared migration tree's models module (exactly how ``terp
    migrate`` discovers models), projects the shared metadata as attributed
    tables + kernel traits, and reconciles it against an AST source scan so a
    model can never be silently skipped: unowned / non-canonical / unmapped /
    unimported entries are alarmed, never dropped (JSON-first for Studio).
    """
    root = str(pathlib.Path(app_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    # Migration-tree discovery expects the app PACKAGE directory (it scans
    # <package>/modules/<name>), mirroring how `terp migrate` is invoked.
    package_dir = pathlib.Path(app_root) / package
    trees = import_declared_models(
        package_dir if package_dir.is_dir() else None, package=package
    )
    graph = build_schema_graph(
        trees, source_models=scan_declared_table_models(app_root, package=package)
    )
    return render_schema_graph(graph, fmt)


def inspect_control_plane(
    dotted: str = "control_plane:control_plane",
    *,
    modules: Sequence[str] = (),
    fmt: str = "text",
) -> str:
    """Return an authority map for *dotted* control plane (text or mermaid)."""
    plane = _load_control_plane(dotted)
    specs = [_load_module_spec(module) for module in modules]
    if fmt == "mermaid":
        return _render_mermaid(plane, specs)
    if fmt == "json":
        return _render_json(plane, specs)
    return _render_text(plane, specs)


def _render_json(plane: ControlPlane, specs: Sequence[ModuleSpec]) -> str:
    """Render the authority map as JSON — the structured introspection seam for
    external tooling (e.g. Terp Studio) that must not import ``terp.*``."""
    payload = {
        "roles": [
            {"name": role.name, "rank": role.rank}
            for role in sorted(plane.permissions.roles, key=lambda item: item.rank)
        ],
        "permissions": [
            {"name": permission.name, "min_role": permission.min_role.name}
            for permission in sorted(
                plane.permissions.permissions, key=lambda item: item.name
            )
        ],
        "modules": [_module_json(spec) for spec in sorted(specs, key=lambda item: item.name)],
        "events": [
            {
                "name": event.name,
                "visibility": event.visibility.value,
                "payload_schema": event.payload_schema.__name__,
            }
            for event in sorted(plane.events.events, key=lambda item: item.name)
        ],
        "jobs": [
            {
                "name": job.name,
                "queue": job.queue,
                "visibility": job.visibility.value,
                "max_attempts": job.retry.max_attempts,
            }
            for job in sorted(plane.jobs.jobs, key=lambda item: item.name)
        ],
        # Platform policies: the rest of the ControlPlane aggregate. The redact
        # keys are substring markers (never secret values) and the denylist is
        # summarised as a count (its entries are noise, not policy shape).
        "audit": {
            "enabled": plane.audit.enabled,
            "disabled_reason": plane.audit.disabled_reason,
            "retention_days": plane.audit.retention_days,
            "redact_keys": list(plane.audit.redact_keys),
        },
        "passwords": {
            "min_length": plane.passwords.min_length,
            "min_character_classes": plane.passwords.min_character_classes,
            "denylist_size": len(plane.passwords.denylist),
            "relaxed_reason": plane.passwords.relaxed_reason,
        },
        "security": {
            "cors": _cors_json(plane.security.cors),
            "rate_limit": {
                "enabled": plane.security.rate_limit.enabled,
                "requests": plane.security.rate_limit.requests,
                "window_seconds": plane.security.rate_limit.window_seconds,
            },
            "max_request_bytes": plane.security.max_request_bytes,
            "trusted_proxy_hops": plane.security.trusted_proxy_hops,
            "request_id_header": plane.security.request_id_header,
        },
        "schedules": [
            {"name": schedule.name, "cron": schedule.cron, "job": schedule.job.name}
            for schedule in sorted(
                plane.schedules.schedules, key=lambda item: item.name
            )
        ],
        "job_system_actor": plane.job_system_actor_id is not None,
    }
    return json.dumps(payload, indent=2)


def _cors_json(cors: CorsPolicy) -> dict[str, object]:
    """The CORS declaration as one of three explicit modes (never raw fields)."""
    if cors.disabled_reason is not None:
        return {"mode": "disabled", "reason": cors.disabled_reason}
    if cors.allow_origins:
        return {
            "mode": "allow",
            "origins": list(cors.allow_origins),
            "allow_credentials": cors.allow_credentials,
        }
    return {"mode": "deny-all", "configured": cors.configured}


def _module_json(spec: ModuleSpec) -> dict[str, object]:
    policy: dict[str, object] | None = None
    if spec.policy is not None:
        if spec.policy.is_public:
            policy = {"public": True, "public_reason": spec.policy.public_reason}
        else:
            policy = {
                "public": False,
                "read": spec.policy.read_requirement.label,
                "write": spec.policy.write_requirement.label,
            }
    return {
        "name": spec.name,
        "policy": policy,
        "requires": list(spec.requires),
        "emits": [event.name for event in spec.emits],
        "subscribes": [event.name for event in spec.subscribes],
        "jobs": [job.name for job in spec.jobs],
    }


def _render_text(plane: ControlPlane, specs: Sequence[ModuleSpec]) -> str:
    lines = ["Roles"]
    for role in sorted(plane.permissions.roles, key=lambda item: item.rank):
        lines.append(f"  {role.name} ({role.rank})")
    lines.append("")
    lines.append("Permissions")
    if not plane.permissions.permissions:
        lines.append("  <none declared>")
    for permission in sorted(plane.permissions.permissions, key=lambda item: item.name):
        lines.append(f"  {permission.name}  {permission.min_role.name}+")
    lines.append("")
    lines.append("Modules")
    if not specs:
        lines.append("  <none provided>")
    for spec in sorted(specs, key=lambda item: item.name):
        lines.append(f"  {spec.name}  {_policy_label(spec)}")
        if spec.requires:
            lines.append(f"    requires: {', '.join(sorted(spec.requires))}")
    lines.append("")
    lines.append("Audit")
    if plane.audit.enabled:
        retention = (
            f"{plane.audit.retention_days} days"
            if plane.audit.retention_days is not None
            else "unlimited"
        )
        lines.append(
            f"  enabled  retention={retention}  "
            f"redact_keys={len(plane.audit.redact_keys)}"
        )
    else:
        lines.append(f"  DISABLED ({plane.audit.disabled_reason})")
    lines.append("")
    lines.append("Passwords")
    password_line = (
        f"  min_length={plane.passwords.min_length}  "
        f"min_character_classes={plane.passwords.min_character_classes}  "
        f"denylist={len(plane.passwords.denylist)} entries"
    )
    if plane.passwords.relaxed_reason is not None:
        password_line += f"  RELAXED ({plane.passwords.relaxed_reason})"
    lines.append(password_line)
    lines.append("")
    lines.append("Security")
    lines.append(f"  cors {_cors_label(plane.security.cors)}")
    rate_limit = plane.security.rate_limit
    lines.append(
        f"  rate_limit "
        + (
            f"{rate_limit.requests}/{rate_limit.window_seconds}s"
            if rate_limit.enabled
            else "DISABLED"
        )
    )
    lines.append(
        f"  max_request_bytes={plane.security.max_request_bytes}  "
        f"trusted_proxy_hops={plane.security.trusted_proxy_hops}"
    )
    lines.append("")
    lines.append("Schedules")
    if not plane.schedules.schedules:
        lines.append("  <none declared>")
    for schedule in sorted(plane.schedules.schedules, key=lambda item: item.name):
        lines.append(f"  {schedule.name}  {schedule.cron}  -> {schedule.job.name}")
    return "\n".join(lines)


def _cors_label(cors: CorsPolicy) -> str:
    if cors.disabled_reason is not None:
        return f"disabled ({cors.disabled_reason})"
    if cors.allow_origins:
        return "allow " + ", ".join(cors.allow_origins)
    return "deny-all" + ("" if cors.configured else " (unconfigured)")


def _policy_label(spec: ModuleSpec) -> str:
    if spec.policy is None:
        return "policy=<missing>"
    if spec.policy.is_public:
        return f"public ({spec.policy.public_reason})"
    return (
        f"read={spec.policy.read_requirement.label}  "
        f"write={spec.policy.write_requirement.label}"
    )


def _render_mermaid(plane: ControlPlane, specs: Sequence[ModuleSpec]) -> str:
    """Render the authority map as a Mermaid ``flowchart`` for visualization.

    Node ids are sanitized to ``[0-9A-Za-z_]`` and every label is quoted, so
    permission names containing ``.`` / ``:`` (e.g. ``billing.read``) stay valid
    Mermaid rather than breaking the diagram.
    """
    lines = ["flowchart LR"]
    ladder = sorted(plane.permissions.roles, key=lambda item: item.rank)
    lines.append("  subgraph Roles")
    for lower, higher in zip(ladder, ladder[1:]):
        lines.append(
            f'    {_mermaid_id("role", lower.name)}["{lower.name}"]'
            f' --> {_mermaid_id("role", higher.name)}["{higher.name}"]'
        )
    if len(ladder) == 1:
        only = ladder[0]
        lines.append(f'    {_mermaid_id("role", only.name)}["{only.name}"]')
    lines.append("  end")
    for spec in sorted(specs, key=lambda item: item.name):
        module_id = _mermaid_id("module", spec.name)
        lines.append(f'  {module_id}(["{spec.name}"])')
        if spec.policy is not None and not spec.policy.is_public:
            for verb, requirement in (
                ("read", spec.policy.read_requirement),
                ("write", spec.policy.write_requirement),
            ):
                authz_id = _mermaid_id("authz", requirement.label)
                lines.append(
                    f'  {module_id} -- "{verb}:{requirement.name}" '
                    f'--> {authz_id}["{requirement.label}"]'
                )
    return "\n".join(lines)


class _VersionAction(argparse.Action):
    """Print the platform version and exit, before the required subcommand bites.

    ``argparse`` refuses a bare ``terp`` because ``command`` is required, so a
    plain flag would never be reached — an action that exits during parsing is
    what makes ``terp --version`` work at all. Not ``action="version"``: the text
    is computed from the live environment (and may carry a mixed-install
    warning), which the built-in's static string cannot express.
    """

    def __init__(self, option_strings, dest, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):  # type: ignore[no-untyped-def]
        from terp.cli.version import render_version

        print(render_version())
        parser.exit()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="terp")
    parser.add_argument(
        "--version",
        "-V",
        action=_VersionAction,
        help="Show the installed platform version (and flag a mixed install)",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subcommands.add_parser(
        "inspect",
        help="Read this app back: its control plane, jobs, access graph, schema and "
        "capabilities (add --format json for a machine-readable answer)",
    )
    inspect_subcommands = inspect_parser.add_subparsers(
        dest="inspect_command",
        required=True,
    )
    control_plane_parser = inspect_subcommands.add_parser(
        "control-plane",
        help="Roles, permissions and which module each one has authority over",
    )
    control_plane_parser.add_argument(
        "--object",
        default="control_plane:control_plane",
        help="Dotted object to inspect (default: control_plane:control_plane)",
    )
    control_plane_parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="Dotted ModuleSpec to include (may be repeated)",
    )
    control_plane_parser.add_argument(
        "--format",
        choices=("text", "mermaid", "json"),
        default="text",
        help="Output format (default: text)",
    )
    jobs_inspect_parser = inspect_subcommands.add_parser(
        "jobs",
        help="Every declared background job, its schedule and its owning module",
    )
    jobs_inspect_parser.add_argument(
        "--object",
        default="control_plane:control_plane",
        help="Dotted ControlPlane to inspect (default: control_plane:control_plane)",
    )
    access_parser = inspect_subcommands.add_parser(
        "access",
        help="The access graph: module policies, per-endpoint requirements, data traits",
    )
    access_parser.add_argument(
        "--object",
        default="control_plane:control_plane",
        help="Dotted object to inspect (default: control_plane:control_plane)",
    )
    access_parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="Dotted ModuleSpec to include (may be repeated)",
    )
    access_parser.add_argument(
        "--app",
        default=None,
        help="Composed FastAPI app or factory (e.g. app.main:build): report the WHOLE "
        "mounted surface incl. discovered capabilities, reconciled against app.openapi()",
    )
    access_parser.add_argument(
        "--app-root",
        default=".",
        help="Directory placed first on sys.path so --app imports (default: .)",
    )
    access_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format: text (human) or json (structured, for any tool or agent "
        "reading this; default: text)",
    )
    capabilities_parser = inspect_subcommands.add_parser(
        "capabilities",
        help="Every maintained terp-cap-* package: installed here vs available to "
        "adopt, with the `uv add` line and its composition-root wiring",
    )
    capabilities_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format: text (human) or json (structured, for any tool or agent "
        "reading this; default: text)",
    )
    schema_parser = inspect_subcommands.add_parser(
        "schema",
        help="The schema graph: every table with ownership, traits, and fail-visible "
        "alarms for models the framework cannot account for",
    )
    schema_parser.add_argument(
        "--app-root",
        default=".",
        help="Project root put first on sys.path; its modules' migration trees load "
        "(default: .)",
    )
    schema_parser.add_argument(
        "--package",
        default="app",
        help="The app package owning app/modules/<name> trees (default: app)",
    )
    schema_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format: text (human) or json (structured, for any tool or agent "
        "reading this; default: text)",
    )

    guide_parser = subcommands.add_parser(
        "guide", help="Print the Terp authoring guide (or a recipe for a topic)"
    )
    guide_parser.add_argument(
        "topic",
        nargs="?",
        default=None,
        help="Optional topic or exact architecture rule for a focused recipe "
        "(validated on dispatch, so the rule registry stays off the common CLI path)",
    )
    guide_parser.add_argument(
        "--list",
        action="store_true",
        help="List the topics instead of printing a recipe — one per line, or JSON "
        "with --format json. The index, for anything that would rather not parse prose",
    )
    guide_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format for --list: text (one topic per line) or json "
        "(default: text)",
    )

    upgrade_parser = subcommands.add_parser(
        "upgrade",
        help="Check whether a newer Terp release is available for the whole set",
    )
    upgrade_parser.add_argument(
        "--check",
        action="store_true",
        help="Report the available release and the bump recipe (the only mode: "
        "Terp reports, it does not edit your manifests)",
    )

    migrate_parser = subcommands.add_parser(
        "migrate",
        help="Run database migrations (upgrade / downgrade / make / status / check)",
    )
    migrate_parser.add_argument(
        "migrate_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the migration runner (e.g. upgrade --database-url ...)",
    )

    jobs_parser = subcommands.add_parser(
        "jobs", help="Run a background job or list the declared jobs (ADR 0043)"
    )
    jobs_subcommands = jobs_parser.add_subparsers(dest="jobs_command", required=True)
    jobs_run_parser = jobs_subcommands.add_parser(
        "run", help="Enqueue/run one job by name (the external-scheduler trigger)"
    )
    jobs_run_parser.add_argument("name", help="Job name (e.g. sync.customers.pull)")
    jobs_run_parser.add_argument(
        "--payload", default="{}", help="JSON payload for the job (default: {})"
    )
    jobs_run_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app or factory (default: app.main:app)",
    )
    jobs_run_parser.add_argument(
        "--app-root", default=".", help="App root placed first on sys.path (default: .)"
    )
    jobs_list_parser = jobs_subcommands.add_parser(
        "list", help="List the jobs the control plane declares"
    )
    jobs_list_parser.add_argument(
        "--object",
        default="control_plane:control_plane",
        help="Dotted ControlPlane to read (default: control_plane:control_plane)",
    )
    jobs_worker_parser = jobs_subcommands.add_parser(
        "worker", help="Drain the durable outbox: run due jobs/events, retry, dead-letter (ADR 0044)"
    )
    jobs_worker_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app or factory (default: app.main:app)",
    )
    jobs_worker_parser.add_argument(
        "--app-root", default=".", help="App root placed first on sys.path (default: .)"
    )
    jobs_worker_parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Drain at most this many batches, else until the outbox is empty (default: until empty)",
    )
    jobs_worker_parser.add_argument(
        "--batch-size", type=int, default=10, help="Rows leased per claim (default: 10)"
    )
    jobs_worker_parser.add_argument(
        "--lease-seconds",
        type=float,
        default=30.0,
        help="Lease duration before a stalled row may be reclaimed (default: 30)",
    )

    jobs_scheduler_parser = jobs_subcommands.add_parser(
        "scheduler",
        help="Run the in-process scheduler: fire declared schedules on their cron (ADR 0047/0048)",
    )
    jobs_scheduler_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app or factory (default: app.main:app)",
    )
    jobs_scheduler_parser.add_argument(
        "--app-root", default=".", help="App root placed first on sys.path (default: .)"
    )

    leases_parser = subcommands.add_parser(
        "leases",
        help="Inspect held/expired leases and recover a dead worker's claim (ADR 0095)",
    )
    leases_subcommands = leases_parser.add_subparsers(dest="leases_command", required=True)
    leases_list_parser = leases_subcommands.add_parser(
        "list", help="Show what is leased, by whom, until when - and what has lapsed"
    )
    leases_list_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app or factory (default: app.main:app)",
    )
    leases_list_parser.add_argument(
        "--app-root", default=".", help="App root placed first on sys.path (default: .)"
    )
    leases_list_parser.add_argument(
        "--kind", default=None, help="Only this resource kind (e.g. sync_source)"
    )
    leases_list_parser.add_argument(
        "--expired",
        action="store_true",
        help="Only lapsed leases: exactly what the next reap cycle will act on",
    )
    leases_list_parser.add_argument(
        "--limit", type=int, default=50, help="Rows to show (default: 50)"
    )
    leases_reap_parser = leases_subcommands.add_parser(
        "reap",
        help="Run one recovery cycle now: the same bounded, fenced cycle the leases.reap job runs",
    )
    leases_reap_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app or factory (default: app.main:app)",
    )
    leases_reap_parser.add_argument(
        "--app-root", default=".", help="App root placed first on sys.path (default: .)"
    )
    leases_reap_parser.add_argument(
        "--kind", default=None, help="Only recover this resource kind (default: every kind)"
    )
    leases_reap_parser.add_argument(
        "--limit", type=int, default=100, help="Leases recovered per cycle (default: 100)"
    )
    leases_reap_parser.add_argument(
        "--purge-idle-seconds",
        type=float,
        default=None,
        help=(
            "Also delete free lease records idle this long (set it well above your longest "
            "lease TTL; a row-shaped resource leaves one record per row ever processed)"
        ),
    )

    new_parser = subcommands.add_parser("new", help="Scaffold a canonical module")
    new_subcommands = new_parser.add_subparsers(dest="new_command", required=True)
    module_parser = new_subcommands.add_parser(
        "module", help="Scaffold a full-stack module (backend slots + frontend slot)"
    )
    module_parser.add_argument("name", help="Module name (lowercase identifier, e.g. invoices)")
    module_parser.add_argument("--root", default=".", help="App root to scaffold into (default: .)")
    module_parser.add_argument("--package", default="app", help="Module package root (default: app)")
    module_parser.add_argument(
        "--no-frontend",
        action="store_true",
        help="Skip the frontend slot even when a frontend app is present",
    )
    module_parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=profile_names(),
        help="Permission profile the slots compile to (default: %(default)s; "
        "see 'terp guide access')",
    )

    apidocs_parser = subcommands.add_parser(
        "api-docs", help="Generate the public-API reference + .pyi from the live kernel"
    )
    apidocs_parser.add_argument("--out", default="docs", help="Output directory (default: docs)")

    openapi_parser = subcommands.add_parser(
        "openapi", help="Export the app's OpenAPI document (the frontend-contract source)"
    )
    openapi_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app or factory (default: app.main:app)",
    )
    openapi_parser.add_argument(
        "--out", default="openapi.json", help="Output file (default: openapi.json)"
    )
    openapi_parser.add_argument(
        "--app-root", default=".", help="App root placed first on sys.path (default: .)"
    )

    routes_parser = subcommands.add_parser(
        "routes",
        help="Regenerate the frontend's route types from the module manifests (ADR 0092)",
    )
    routes_parser.add_argument(
        "--root", default=".", help="Project root the frontend is resolved against (default: .)"
    )
    routes_parser.add_argument(
        "--frontend-dir", default="frontend", help="Frontend app directory (default: frontend)"
    )
    routes_parser.add_argument(
        "--check",
        action="store_true",
        help="Refuse a stale committed route table instead of rewriting it (the CI shape)",
    )

    dev_parser = subcommands.add_parser(
        "dev",
        help="Run the backend + frontend dev servers together (with the codegen preflight)",
    )
    dev_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app (default: app.main:app)",
    )
    dev_parser.add_argument(
        "--app-root", default=".", help="Project root placed first on sys.path (default: .)"
    )
    dev_parser.add_argument(
        "--frontend-dir", default="frontend", help="Frontend app directory (default: frontend)"
    )
    dev_parser.add_argument(
        "--host", default="127.0.0.1", help="Backend host (default: 127.0.0.1)"
    )
    dev_parser.add_argument(
        "--port", type=int, default=8000, help="Backend port (default: 8000)"
    )
    dev_parser.add_argument(
        "--openapi-out",
        default="openapi.json",
        help="Preflight OpenAPI output path, relative to root (default: openapi.json)",
    )
    dev_parser.add_argument(
        "--no-preflight", action="store_true", help="Skip the OpenAPI preflight export"
    )

    fmt_parser = subcommands.add_parser(
        "fmt", help="Format the Python files this change touched (ruff format)"
    )
    fmt_parser.add_argument("--root", default=".", help="Project root (default: .)")
    fmt_parser.add_argument(
        "--all",
        action="store_true",
        help="Format the whole tree instead of the changed files — churns files this "
        "change never touched, so ask for it deliberately",
    )
    fmt_parser.add_argument(
        "--check",
        action="store_true",
        help="Report what would be reformatted without rewriting anything (the CI shape)",
    )

    check_parser = subcommands.add_parser("check", help="Run the architecture gate locally")
    check_parser.add_argument(
        "--root",
        default=".",
        help="Project root, or the app package itself; the gate scans the app package "
        "(default: .)",
    )
    check_parser.add_argument("--package", default="app", help="App package (default: app)")
    check_parser.add_argument(
        "--budget", default=None, help="Escape-hatch budget JSON (governs # arch-allow markers)"
    )
    check_parser.add_argument(
        "--format",
        choices=("text", "json", "check-report"),
        default="text",
        help="Output format: text (human), json (the legacy structured report), or "
        "check-report (the Terp Standard app-check-report envelope; default: text)",
    )

    verify_parser = subcommands.add_parser(
        "verify",
        help="Run the project's whole verification profile (the one-command gate)",
    )
    verify_parser.add_argument(
        "--profile",
        choices=profile_ids(),
        default="quick",
        help="Which checks run: quick (static enforcement), full (+ tests, AppSec "
        "baseline, build), release (+ docs drift, conformance; default: quick)",
    )
    verify_parser.add_argument("--root", default=".", help="Project root (default: .)")
    verify_parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="CHECK",
        help="Run only the named check(s) of the profile (repeatable) — the seam a "
        "driving tool uses for change-scoped reruns",
    )
    verify_parser.add_argument(
        "--list",
        action="store_true",
        help="Print the profile's check manifest without running anything",
    )
    verify_parser.add_argument(
        "--format",
        choices=("text", "json", "assurance"),
        default="text",
        help="Output format: text (human), json (the terp_verify envelope), or "
        "assurance (the release-assurance claim, assurance-profile.schema.json; "
        "requires --profile release; default: text)",
    )

    user_parser = subcommands.add_parser(
        "user", help="Manage users (e.g. bootstrap the first administrator)"
    )
    user_subcommands = user_parser.add_subparsers(dest="user_command", required=True)
    user_create_parser = user_subcommands.add_parser(
        "create", help="Create (or confirm) a user directly against the app's store"
    )
    user_create_parser.add_argument("email", help="The user's email address")
    user_create_parser.add_argument(
        "--role",
        default="admin",
        help="viewer / editor / admin or an integer rank (default: admin)",
    )
    user_create_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app (default: app.main:app)",
    )
    user_create_parser.add_argument(
        "--app-root", default=".", help="App root placed first on sys.path (default: .)"
    )
    user_create_parser.add_argument(
        "--password-env",
        default="TERP_USER_PASSWORD",
        help="Env var holding the new password; prompts if unset (default: TERP_USER_PASSWORD)",
    )

    sa_parser = subcommands.add_parser(
        "service-account",
        help="Manage machine credentials (so an integration never needs a person's login)",
    )
    sa_subcommands = sa_parser.add_subparsers(dest="service_account_command", required=True)
    sa_create_parser = sa_subcommands.add_parser(
        "create", help="Provision a service account and print its credentials once"
    )
    sa_create_parser.add_argument("name", help="Human-readable name of the integration")
    sa_create_parser.add_argument(
        "--role",
        required=True,
        help="viewer / editor / admin or an integer rank (required: an integration's "
        "authority is chosen, never inherited)",
    )
    sa_create_parser.add_argument(
        "--description", default=None, help="What this credential is for, and who owns it"
    )
    sa_create_parser.add_argument(
        "--expires-in-days",
        type=int,
        default=365,
        help="Days until the credential lapses; 0 means never (default: 365)",
    )
    sa_create_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app (default: app.main:app)",
    )
    sa_create_parser.add_argument(
        "--app-root", default=".", help="App root placed first on sys.path (default: .)"
    )

    grant_parser = subcommands.add_parser(
        "grant",
        help="Assign, list and revoke a subject's permission grants (least privilege "
        "without hand-writing an admin API call)",
    )
    grant_subcommands = grant_parser.add_subparsers(dest="grant_command", required=True)

    _SUBJECT_HELP = (
        "A user email, a service-account name, or a subject UUID"
    )
    for _name, _help in (
        ("add", "Grant a permission to a subject (idempotent, audited)"),
        ("revoke", "Revoke a permission from a subject"),
    ):
        _p = grant_subcommands.add_parser(_name, help=_help)
        _p.add_argument("subject", help=_SUBJECT_HELP)
        _p.add_argument("permission", help="The permission name the app declares")
        _p.add_argument(
            "--app",
            default="app.main:app",
            help="Dotted module:attribute of the FastAPI app (default: app.main:app)",
        )
        _p.add_argument(
            "--app-root", default=".", help="App root placed first on sys.path (default: .)"
        )

    grant_list_parser = grant_subcommands.add_parser(
        "list", help="List every permission a subject holds, including via groups"
    )
    grant_list_parser.add_argument("subject", help=_SUBJECT_HELP)
    grant_list_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app (default: app.main:app)",
    )
    grant_list_parser.add_argument(
        "--app-root", default=".", help="App root placed first on sys.path (default: .)"
    )

    seed_parser = subcommands.add_parser(
        "seed", help="Run the app's seed routine (idempotent demo / bootstrap data; dev only)"
    )
    seed_parser.add_argument(
        "--app",
        default="app.main:app",
        help="Dotted module:attribute of the FastAPI app (default: app.main:app)",
    )
    seed_parser.add_argument(
        "--app-root", default=".", help="App root placed first on sys.path (default: .)"
    )
    seed_parser.add_argument(
        "--seed",
        default="app.seed:seed",
        help=(
            "Dotted module:attribute of the seed callable(session) to run — a stage "
            "selector, not just a location override: point it at any callable the app "
            "exposes (e.g. app.demo:install) to run only that stage "
            "(default: app.seed:seed)"
        ),
    )

    docker_parser = subcommands.add_parser(
        "docker", help="Docker workflows (the Compose dev workbench)"
    )
    docker_subcommands = docker_parser.add_subparsers(dest="docker_command", required=True)
    docker_dev_parser = docker_subcommands.add_parser(
        "dev", help="Run the full-stack workbench via `docker compose watch` (db + api + web)"
    )
    docker_dev_parser.add_argument(
        "--compose-file",
        default="docker-compose.yml",
        help="Compose file, resolved under --root (default: docker-compose.yml)",
    )
    docker_dev_parser.add_argument(
        "--root", default=".", help="Directory the compose file is resolved against (default: .)"
    )
    docker_dev_parser.add_argument(
        "--project-name", default=None, help="Compose project name (default: Compose's own)"
    )

    smoke_parser = subcommands.add_parser(
        "smoke",
        help="Run the workbench's backend boot chain in-process (no Docker daemon)",
    )
    smoke_parser.add_argument(
        "--compose-file",
        default="docker-compose.yml",
        help="Compose file the topology is read from (default: docker-compose.yml)",
    )
    smoke_parser.add_argument(
        "--root", default=".", help="Directory the compose file is resolved against (default: .)"
    )
    smoke_parser.add_argument(
        "--plan",
        action="store_true",
        help="Print the translated chain and exit without running it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Console entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "inspect" and args.inspect_command == "control-plane":
        print(inspect_control_plane(args.object, modules=args.module, fmt=args.format))
        return
    if args.command == "inspect" and args.inspect_command == "jobs":
        print(render_jobs(args.object))
        return
    if args.command == "inspect" and args.inspect_command == "access":
        print(
            inspect_access(
                args.object,
                modules=args.module,
                app=args.app,
                app_root=args.app_root,
                fmt=args.format,
            )
        )
        return
    if args.command == "inspect" and args.inspect_command == "schema":
        print(inspect_schema(app_root=args.app_root, package=args.package, fmt=args.format))
        return
    if args.command == "inspect" and args.inspect_command == "capabilities":
        print(render_capabilities(fmt=args.format))
        return
    if args.command == "guide":
        if args.list:
            # The rule names are deliberately a SEPARATE key rather than folded in with
            # the topics: `terp guide <rule>` accepts both, but a rule is a remediation
            # for one gate finding and a topic is a subject you can learn. A consumer
            # offering "what can I read about?" wants the topics; a consumer resolving a
            # violation already has the rule name and wants only to know it is answerable.
            if args.format == "json":
                print(
                    json.dumps(
                        {"topics": list(guide_topics()), "rules": sorted(set(guide_choices()) - set(guide_topics()))},
                        indent=2,
                    )
                )
            else:
                for topic in guide_topics():
                    print(topic)
            return
        if args.topic is not None and args.topic not in guide_choices():
            raise SystemExit(
                f"terp guide: unknown topic or rule {args.topic!r}; run `terp guide` "
                "for the topic list or `terp guide rules` for every rule name"
            )
        print(guide(args.topic))
        return
    if args.command == "upgrade":
        from terp.cli.version import render_upgrade_check

        if not args.check:
            raise SystemExit(
                "terp upgrade: run `terp upgrade --check`. Terp reports what is "
                "available and how to bump; it does not edit your manifests, because "
                "a lockstep bump spans pyproject.toml and frontend/package.json and "
                "must be reviewed as one change."
            )
        print(render_upgrade_check())
        return
    if args.command == "migrate":
        from terp.migrations import migrate_main

        migrate_main(args.migrate_args)
        return
    if args.command == "jobs" and args.jobs_command == "run":
        print(
            run_job_command(
                args.name, payload=args.payload, app_ref=args.app, app_root=args.app_root
            )
        )
        return
    if args.command == "jobs" and args.jobs_command == "list":
        print(render_jobs(args.object))
        return
    if args.command == "jobs" and args.jobs_command == "worker":
        print(
            run_worker_command(
                app_ref=args.app,
                app_root=args.app_root,
                max_cycles=args.max_cycles,
                batch_size=args.batch_size,
                lease_seconds=args.lease_seconds,
            )
        )
        return
    if args.command == "jobs" and args.jobs_command == "scheduler":
        print(run_scheduler_command(app_ref=args.app, app_root=args.app_root))
        return
    if args.command == "leases" and args.leases_command == "list":
        print(
            render_leases(
                app_ref=args.app,
                app_root=args.app_root,
                kind=args.kind,
                expired_only=args.expired,
                limit=args.limit,
            )
        )
        return
    if args.command == "leases" and args.leases_command == "reap":
        print(
            reap_leases_command(
                app_ref=args.app,
                app_root=args.app_root,
                kind=args.kind,
                limit=args.limit,
                purge_idle_seconds=args.purge_idle_seconds,
            )
        )
        return
    if args.command == "new" and args.new_command == "module":
        paths = new_module(
            args.name,
            root=args.root,
            package=args.package,
            frontend=not args.no_frontend,
            profile=args.profile,
        )
        print(new_module_message(args.name, paths, profile=args.profile))
        return
    if args.command == "api-docs":
        for path in api_docs(args.out):
            print(f"wrote {path}")
        return
    if args.command == "openapi":
        print(f"wrote {export_openapi(args.app, out=args.out, app_root=args.app_root)}")
        return
    if args.command == "routes":
        print(
            run_routes_command(
                root=args.root, frontend_dir=args.frontend_dir, check=args.check
            )
        )
        return
    if args.command == "dev":
        print(
            run_dev_command(
                app_ref=args.app,
                root=args.app_root,
                frontend_dir=args.frontend_dir,
                host=args.host,
                port=args.port,
                openapi_out=args.openapi_out,
                preflight=not args.no_preflight,
            )
        )
        return
    if args.command == "fmt":
        raise SystemExit(
            run_fmt_command(root=args.root, changed=not args.all, check=args.check)
        )
    if args.command == "check":
        if args.format == "check-report":
            payload = check_report_envelope(
                args.root, package=args.package, budget_path=args.budget
            )
            print(json.dumps(payload, indent=2))
            if not payload["ok"]:
                raise SystemExit(1)
            return
        if args.format == "json":
            payload = check_report(args.root, package=args.package, budget_path=args.budget)
            print(json.dumps(payload, indent=2))
            if not payload["ok"]:
                raise SystemExit(1)
            return
        from terp.arch import assert_app_clean

        assert_app_clean(
            gate_root(args.root, package=args.package),
            package=args.package,
            budget_path=args.budget,
        )
        print("terp.arch: app is clean")
        return
    if args.command == "verify":
        raise SystemExit(
            run_verify_command(
                profile=args.profile,
                root=args.root,
                only=args.only,
                list_only=args.list,
                fmt=args.format,
            )
        )
    if args.command == "user" and args.user_command == "create":
        print(
            create_user_command(
                args.email,
                role=args.role,
                app_ref=args.app,
                app_root=args.app_root,
                password_env=args.password_env,
            )
        )
        return
    if args.command == "service-account" and args.service_account_command == "create":
        print(
            create_service_account_command(
                args.name,
                role=args.role,
                description=args.description,
                expires_in_days=args.expires_in_days or None,
                app_ref=args.app,
                app_root=args.app_root,
            )
        )
        return
    if args.command == "grant":
        _commands = {
            "add": grant_add_command,
            "revoke": grant_revoke_command,
        }
        if args.grant_command == "list":
            print(
                grant_list_command(
                    args.subject, app_ref=args.app, app_root=args.app_root
                )
            )
            return
        print(
            _commands[args.grant_command](
                args.subject,
                args.permission,
                app_ref=args.app,
                app_root=args.app_root,
            )
        )
        return
    if args.command == "seed":
        print(run_seed_command(app_ref=args.app, app_root=args.app_root, seed_ref=args.seed))
        return
    if args.command == "docker" and args.docker_command == "dev":
        print(
            run_docker_dev_command(
                compose_file=args.compose_file, root=args.root, project_name=args.project_name
            )
        )
        return
    if args.command == "smoke":
        from terp.cli.smoke import render_smoke_plan, run_smoke_command

        if args.plan:
            print(render_smoke_plan(root=args.root, compose_file=args.compose_file))
            return
        raise SystemExit(run_smoke_command(root=args.root, compose_file=args.compose_file))
    parser.error("unknown command")  # pragma: no cover - argparse guards this


__all__ = [
    "api_docs",
    "check_report",
    "check_report_envelope",
    "changed_python_files",
    "create_service_account_command",
    "create_user_command",
    "grant_add_command",
    "grant_list_command",
    "grant_revoke_command",
    "dev_plan",
    "export_openapi",
    "gate_root",
    "guide",
    "guide_topics",
    "guide_choices",
    "inspect_access",
    "inspect_control_plane",
    "main",
    "new_module",
    "profile_ids",
    "render_jobs",
    "run_dev_command",
    "run_docker_dev_command",
    "run_fmt_command",
    "run_job_command",
    "run_routes_command",
    "run_scheduler_command",
    "run_seed_command",
    "run_verify_command",
    "run_worker_command",
    "verify_manifest",
]
