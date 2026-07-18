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
from terp.cli.dev import dev_plan, run_dev_command
from terp.cli.docker import run_docker_dev_command
from terp.cli.jobs import (
    render_jobs,
    run_job_command,
    run_scheduler_command,
    run_worker_command,
)
from terp.cli.openapi import _load_app, export_openapi
from terp.cli.profiles import DEFAULT_PROFILE, profile_names
from terp.cli.scaffold import new_module, new_module_message
from terp.cli.schema import (
    build_schema_graph,
    import_declared_models,
    render_schema_graph,
    scan_declared_table_models,
)
from terp.cli.seed import run_seed_command
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

Then run `terp check`. Policy.default() = authenticated; read VIEWER, write EDITOR.
""",
    "service": """\
Services (BaseService)

- Subclass BaseService[Model, Create, Update] and set `model`. You get
  create/update/delete/get/list — all audited, OCC-checked and scope-honored.
- A bespoke mutation must route through self._save(...) / self._remove(...) (never a
  raw session write), so it stays audited.
- Add an always-on read filter by overriding business_filters() — it returns
  conditions and CANNOT drop soft-delete / tenant scope:
      def business_filters(self):
          return (Invoice.status == "open",)
- A per-call filter goes in a custom list() built on base_query():
      def list(self, session, *, skip, limit, status=None):
          q = self.base_query()
          if status is not None:
              q = q.where(Invoice.status == status)
          return self._paginate(session, q, skip=skip, limit=limit)
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
- Dropping to raw SQL? Keep the text(...) argument a STATIC literal and pass data
  through bound parameters — a dynamically built statement (f-string, concatenation,
  .format, %, or a variable) is refused by the no_dynamic_sql rule (SQL injection):
      session.exec(text("SELECT ... WHERE status = :status"), {"status": status})
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

- Declare typed events in your control plane (never bare strings):
      NOTE_CREATED = EventDefinition("note.created", payload_schema=NoteCreatedPayload)
      event_catalog = EventCatalog([NOTE_CREATED])
- Emit declaratively from a service (atomic with the write):
      class NoteService(EventEmittingService[Note, NoteCreate, NoteUpdate]):
          model = Note
          event_map = LifecycleEventMap(created=NOTE_CREATED)
- Subscribe with @subscribe(NOTE_CREATED). Reference catalog constants only (the gate
  enforces no-drift). Wire create_app(..., event_dispatcher=dispatch_in_process).
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
- Trigger a scheduled job from any cron / k8s CronJob / systemd or cloud timer:
      terp jobs run sync.customers.pull --payload '{"source": "crm"}'
  Inspect the declared jobs:  terp jobs list   /   terp inspect jobs.
- Declare a schedule (ScheduleDefinition: a cron + a catalog JobDefinition) on the control
  plane (ControlPlane(schedules=ScheduleCatalog([...]))); boot validates each schedule's job
  against the JobCatalog. Run schedules in-process with `terp jobs scheduler` (APScheduler;
  needs terp-cap-scheduler-apscheduler) or via Celery beat — each cron tick enqueues through
  the same typed seam, so a scheduled job stays audited + system-actor stamped.
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

- Capabilities are opt-in packages (terp-cap-*); the base profile is auth + access +
  identity + users (+ projects). Install the ones you need.
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
Frontend module screens (@terp/react-core)

- A module's frontend slot is frontend/src/modules/<name>/ with a module.tsx manifest;
  everything composes the token-styled @terp/react-core surface. The full catalog (with
  per-export "Use" guidance) is the @terp/react-core README; each export also carries
  JSDoc, so your editor shows the same guidance inline.
- The boundary lint (@terp/eslint-boundaries) refuses, fail-closed:
    raw <button>/<input>/<select>/<textarea>   ->  Button / Input / Select / Textarea
    raw <table>                                ->  DataView          (terp guide dataview)
    raw <dialog>                               ->  ConfirmDialog
    raw <form>                                 ->  Stack as="form"   (terp guide forms)
    raw fetch / XMLHttpRequest                 ->  useTerpClient() + unwrap (typed client)
    WebSocket / EventSource / sendBeacon       ->  the generated client (one egress path)
    style={} / className / module stylesheets  ->  layout via Stack/DetailList; design tokens
    <a href="/...">                            ->  the router's Link (role-aware, no reload)
    deep imports (@terp/*/src, @terp/*/dist)   ->  import from the package root only
- Frontend security defaults (each its own lint rule, same error-only footing):
  dangerouslySetInnerHTML and DOM HTML-injection sinks (innerHTML/outerHTML/
  insertAdjacentHTML/document.write) are refused — render text, or Markdown from
  @terp/react-core for rich text; eval() / new Function() are refused; javascript:
  URLs in href/src are refused; a static target="_blank" link needs rel="noopener".
- Every routed view renders a page archetype (Page / OverviewPage / DetailPage / HubPage);
  buildAppRouter refuses an unframed view at runtime, fail closed. An app can ratchet
  further with an opt-in slot-typed layout contract (terp guide layouts).
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
- Client-side (small collections — rows already in memory):
      const repo = useMemo(() => new InMemoryDataViewRepository(rows), [rows]);
      <DataView repository={repo} columns={columns} keyField="id" />
- Server-side (large collections — let the backend paginate/sort/filter):
      const repo = useMemo(() => new HttpDataViewRepository({...}), [client]);
  and keep query state in the URL with useServerDataView.
- Columns declare {key, header, render?}; header text is UiText. Row actions and batch
  actions are declared as data (the component renders the token-styled controls).
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
    "layouts": """\
Layout contracts (slot-typed layouts, ADR 0079)

- A layout contract is an OPT-IN ratchet above the page archetypes: not just "every
  routed view is framed", but "this archetype's body holds only these components".
  It is enforced two-layer and fail-closed, and every failure message tells you the
  contract, the slot, what was found, what is allowed, and the concrete fix — let it
  guide you.
- Opt in (both halves; keep them in sync — the template generates both):
      frontend/layout-contract.json          -> { "contract": "standard" }   (lint half)
      renderTerpApp({ layoutContract: "standard", ... })                     (runtime half)
  No config = no checks (fully backwards compatible; an existing app can switch later
  and fix screens by following the enforcement messages).
- The "standard" contract governs the body slot of each archetype:
      HubPage      -> HubCard only (a card grid landing)
      OverviewPage -> DataView / ResourceList / ModuleNav / Stack + the framework
                      states (EmptyState / ErrorState / LoadingState / Alert) and
                      ConfirmDialog
      DetailPage   -> DetailList / Stack / Tabs / ModuleNav / DataView + the same
                      framework states and ConfirmDialog
  The plain Page stays unconstrained — it is the sanctioned home for a bespoke screen.
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
""",}

# Topics whose body is generated from a live registry (not a static recipe above).
_GENERATED_TOPICS: tuple[str, ...] = ("rules",)

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
  6. Cap every input string: Field(max_length=...).
  7. Import only the terp.core public surface + your declared capabilities — never
     terp.core._internal, never a sibling module.

More:  terp guide <topic>   (topics: {_TOPIC_NAMES})
    terp guide <rule>            (the exact rule's remediation and related pattern)
       terp guide rules             (every architecture rule the gate enforces, generated)
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


def _render_rule_guide(rule_name: str) -> str:
    """Render one rule's exact remediation followed by its broader authoring pattern."""
    from terp.arch.rules import GUIDE_TOPIC_BY_RULE, _ALL_RULES

    topic = GUIDE_TOPIC_BY_RULE[rule_name]
    rules = {
        rule.__name__.removeprefix("check_"): rule
        for rule in _ALL_RULES
    }
    headline = _rule_headline(rules[rule_name]) if rule_name in rules else rule_name
    detail = _RULE_GUIDE_DETAILS.get(
        rule_name,
        "Apply the sanctioned construct in the related authoring pattern below at "
        "the exact file and line from the finding. Preserve existing behavior and "
        "rerun the failing check; do not add an opt-out merely to turn it green.",
    )
    return (
        f"Rule: {rule_name}\n"
        f"{headline}\n\n"
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
    if topic in _GUIDE_TOPICS:
        return _GUIDE_TOPICS[topic]
    return _render_rule_guide(topic)


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

    violations = list(check_app(root, package=package, budget_path=budget_path))
    if budget_path is None:
        violations.extend(ungoverned_marker_violations(root, package=package))
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="terp")
    subcommands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subcommands.add_parser("inspect")
    inspect_subcommands = inspect_parser.add_subparsers(
        dest="inspect_command",
        required=True,
    )
    control_plane_parser = inspect_subcommands.add_parser("control-plane")
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
    jobs_inspect_parser = inspect_subcommands.add_parser("jobs")
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
        help="Output format: text (human) or json (structured, for Studio; default: text)",
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
        help="Output format: text (human) or json (structured, for Studio; default: text)",
    )

    guide_parser = subcommands.add_parser(
        "guide", help="Print the Terp authoring guide (or a recipe for a topic)"
    )
    guide_parser.add_argument(
        "topic",
        nargs="?",
        choices=guide_choices(),
        default=None,
        help="Optional topic or exact architecture rule for a focused recipe",
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

    dev_parser = subcommands.add_parser(
        "dev",
        help="Run the backend + frontend dev servers together (with an OpenAPI preflight)",
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

    check_parser = subcommands.add_parser("check", help="Run the architecture gate locally")
    check_parser.add_argument("--root", default=".", help="App root (default: .)")
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
        help="Dotted module:attribute of the seed callable (default: app.seed:seed)",
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
    if args.command == "guide":
        print(guide(args.topic))
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

        assert_app_clean(args.root, package=args.package, budget_path=args.budget)
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
    parser.error("unknown command")  # pragma: no cover - argparse guards this


__all__ = [
    "api_docs",
    "check_report",
    "check_report_envelope",
    "create_user_command",
    "dev_plan",
    "export_openapi",
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
    "run_job_command",
    "run_scheduler_command",
    "run_seed_command",
    "run_verify_command",
    "run_worker_command",
    "verify_manifest",
]
