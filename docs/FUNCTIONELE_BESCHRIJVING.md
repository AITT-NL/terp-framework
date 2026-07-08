# Terp — Complete functionele beschrijving

> **Terp** ("Trusted Enterprise Reinforced Platform" — *"Build on high ground"*) is een
> secure-by-default, agent-vriendelijk applicatieplatform. Dit document beschrijft de
> volledige functionaliteit van het framework. Bronnen van waarheid:
> [AGENTIC_PLATFORM_DESIGN.md](../AGENTIC_PLATFORM_DESIGN.md) en de ADR's in
> [docs/decisions/](decisions/).

---

## 1. Doel en visie

Terp lost één kernprobleem op: **hoe laat je ontwikkelteams — en hun coding agents —
snel businessfunctionaliteit bouwen zonder dat de codebase wegdrijft van het veilige
pad.**

De aanpak:

- Een **onderhouden, geversioneerde core** (`terp-core`) die als dependency wordt
  geconsumeerd — nooit geforkt of bewerkt door de klant.
- **Opt-in capabilities** (auth, users, tenancy, audit, …) die de klant à la carte
  aanzet.
- **Modules**: de businesscode van de klant — het *enige* bewerkbare oppervlak.
- Een **enforcement harness** (`terp-arch`) die als dependency meereist, zodat de
  klant de regels wél draait maar niet kan verzwakken.
- Een **frontend-contract** zodat meerdere frontend-stacks (React eerst, later
  Svelte) tegen dezelfde backend in pariteit onderhouden kunnen worden.

### Kerndoelen

1. Een ontwikkelaar (of agent) levert een nieuwe, veilige CRUD-module in **< 1 uur**:
   alleen een model, schemas, een dunne router en een manifest van ~6 regels.
2. Een vergeten beveiligingsstap **faalt gesloten** (geweigerd / boot niet), nooit open.
3. De klant kan de core niet bewerken en de harness niet verzwakken.
4. Core-internals kunnen refactoren zonder één klantmodule te breken.
5. Dezelfde backend bedient producten met **verschillende tenancy-modellen**.
6. Twee of meer frontend-stacks blijven aantoonbaar in pariteit.
7. Agents hebben **volledige broncode-zichtbaarheid** van de core, zonder mutatierechten.

### Expliciete non-goals

- Het backend-framework (FastAPI + SQLModel/SQLAlchemy + Pydantic) is **niet**
  verwisselbaar — dat *is* de verkochte opinie.
- Geen runtime micro-frontends / module federation; modules zijn build-time.
- Geen no-code builder; doelgroep is professionele ontwikkelaars met agents.

---

## 2. Architectuur in lagen

| Laag | Root | Inhoud | Mag importeren |
|---|---|---|---|
| **0 Kernel** | `terp.core` | basisklassen, config, security, db, errors, discovery, `ModuleSpec`/`Policy`, `create_app` | niets boven zichzelf |
| **1 Capabilities** | `terp.capabilities.*` | cross-cutting features: auth, identity, users, access, tenancy, audit, eventbus, … | core + strikt lagere capabilities |
| **2 Foundation** (optioneel) | `app/foundation/*` | gedeelde domeinankers | core, capabilities |
| **3 Modules** | `app/modules/*` | leaf-businessdomeinen (klant-eigendom) | core, capabilities, foundation — **nooit elkaar** |

Aanvullende onderdelen:

- **Harness** (`terp.arch`) — de build-time fitness-suite, geleverd als dependency.
- **CLI** (`terp`) — scaffolding, inspectie, migraties, documentatie (zie §9).
- **Frontend-pakketten** — `@terp/contract`, `@terp/react-core`,
  `@terp/eslint-boundaries`, `@terp/conformance`.

### De drie koppelnaden

1. **Modules ↔ core**: uitsluitend via het gepubliceerde publieke API-oppervlak van
   `terp.core`; `terp.core._internal` en sibling-modules zijn import-verboden
   (afgedwongen door fitness-tests).
2. **Backend ↔ frontend**: uitsluitend via het OpenAPI-contract + het
   frontend-contract — dit maakt de frontend verwisselbaar.
3. **Backend-framework**: bewust vast (FastAPI/SQLModel-opinie).

### Monorepo-indeling

```text
packages/backend/core           terp-core    → import terp.core            (kernel)
packages/backend/arch           terp-arch    → import terp.arch            (harness)
packages/backend/cli            terp-cli     → `terp`-commando
packages/backend/capabilities   terp-cap-*   → import terp.capabilities.*
packages/backend/migrations     terp-migrations (migratie-orkestratie)
packages/frontend/contract      @terp/contract       (client + tokens + manifest-types)
packages/frontend/react-core    @terp/react-core     (eerste stack: React)
packages/frontend/eslint-boundaries  @terp/eslint-boundaries
packages/frontend/conformance   @terp/conformance    (Playwright-pariteitssuite)
apps/example                    neutrale voorbeeldapp (dogfood)
template/                       copier-skelet (CI, AGENTS.md)
vendor/terp-core                read-only spiegel voor agent-zichtbaarheid
```

---

## 3. Het authoring-model: hoe een module wordt gebouwd

### 3.1 `ModuleSpec` — het volledige extensie-oppervlak

Een module publiceert precies één manifest; dat is de hele publieke extensie-API:

```python
# app/modules/billing/module.py
from terp.core import ModuleSpec, Policy

module = ModuleSpec(
    name="billing",
    router=router,                   # auto-gemount op /api/v1/billing
    services=[InvoiceService],       # geregistreerd voor DI
    requires=["users"],              # capability-afhankelijkheden; gecheckt bij boot
    events=["invoice.paid"],         # gedeclareerd op de event bus
    policy=Policy.default(),         # authenticated; mutaties vereisen EDITOR+
    tenant_scoped=True,              # rijen per tenant geïsoleerd by construction
)
```

**Discovery** (bestandssysteem voor in-repo modules, entry points voor installeerbare
capabilities) verzamelt elke `ModuleSpec` en bedraadt routers, DI, modellen (voor
migraties), events en navigatie — zonder centrale registratie of edits aan `main.py`.

### 3.2 Basisklassen

- **`BaseTable`** — `id` (UUID), `created_at`, `updated_at`, `version` (optimistic
  concurrency). Deze velden worden nooit opnieuw gedeclareerd.
- **`BaseSchema` / `BaseUpdateSchema`** — DTO-basis; update-schema's vereisen
  `version` (OCC).
- **`BaseService[Model, Create, Update]`** — CRUD, paginering, eager-loading-hooks
  en het **geauditeerde write-chokepoint**: de service bezit de commit, de
  write-scope is re-entrant (geneste writes voegen zich bij dezelfde atomaire,
  geauditeerde transactie-eenheid).

### 3.3 Declaratieve model-traits (opt-in mixins)

| Trait | Functie |
|---|---|
| `SoftDeleteMixin` | Soft-delete, automatisch gehonoreerd in elke query — geen handmatige scope-filters |
| `TenantScopedMixin` | Membership-isolatie per tenant, op sessieniveau geïnjecteerd |
| Actor-stamping | `created_by` / `updated_by` automatisch gestempeld vanuit de request-actor |
| `OwnedMixin` | Per-rij schrijfautorisatie: `owner_id` wordt gestempeld bij create; elke update/delete wordt per rij geautoriseerd (niet-eigenaar ⇒ 403). Handmatige `owner_id`-checks zijn verboden (regel `no_manual_ownership_checks`) |
| Lifecycle-eventmap | Declaratief events emitteren op create/update/delete |

### 3.4 Canonieke modulevorm

Elke module volgt dezelfde vorm (afgedwongen door de regel `canonical_module_shape`):
`module.py` (manifest), `models.py`, `schemas.py`, `service.py`, `router.py`,
`migrations/`. Voor standaard-CRUD bestaat de fabriek **`build_crud_router`** die een
complete, beleids-conforme router genereert.

---

## 4. Secure-by-default: het beveiligingsmodel

**Principe:** wie niets bijzonders doet, krijgt een veilig resultaat. Elke onveilige
actie vereist een expliciete, greppable, gebudgetteerde opt-out. Elk controle-punt is
**tweelaags**: een fail-closed **runtime-control** (de echte bescherming) *én* een
build-time **fitness-test** (die de omissie vangt). De test is nooit de enige controle.

### 4.1 Deny-by-default autorisatie

- Het framework — niet de ontwikkelaar — mount elke module-router achter een guard
  afgeleid van `ModuleSpec.policy`. **Geen policy ⇒ app boot niet.**
- `Policy.default()` = geauthenticeerd; mutaties (POST/PUT/PATCH/DELETE) vereisen een
  schrijfrol (EDITOR+), lezen VIEWER+.
- Publieke endpoints vereisen `Policy.public(reason=…)`: op een allowlist met
  justificatie, geteld door het escape-hatch-budget.
- Een safe HTTP-methode (GET/HEAD/OPTIONS) wordt runtime een write geweigerd
  (+ regel `safe_methods_are_read_only`).

### 4.2 De complete autorisatiematrix

| Niveau | Mechanisme | ADR |
|---|---|---|
| **Endpoint** | `Policy` per module; permissies afgedwongen als grant | 0016 |
| **Rij-lezen (zichtbaarheid)** | Niet-overschrijfbaar scope-predicaat + row-scope-registry; sessie herscoped ook `get`/`scalars`/`scalar` | 0017, 0028 |
| **Rij-schrijven (eigenaarschap)** | `OwnedMixin` + object-authz-registry (`register_object_authz_predicate`) | 0029 |

Lees- en schrijfpredicaten zijn bewust gescheiden: het leespredicaat wordt nooit
hergebruikt als mutatiepredicaat.

### 4.3 Tenant-isolatie by construction

- Een sessie-level event injecteert het membership-predicaat op elke query tegen een
  `TenantScoped`-entiteit; een naïeve query levert alleen rijen van de eigen tenant.
- Cross-tenant toegang vereist expliciet `include_all_tenants=True` — greppable en
  geflagd tenzij allowlisted.
- Tenancy is fail-closed gescoped; de *betekenis* van "tenant" komt uit de
  tenancy-capability (§5).

### 4.4 Geen ruwe data over de grens

- Elke route declareert een `response_model`; de serializer weigert een kale
  ORM-instantie. Een `response_model` mag **geen tabelmodel** zijn (ADR 0020).
- Over-posting wordt gestript; `*Read`-DTO's mogen geen gevoelige velden
  (`password`, `hashed_password`, `*secret`, `*token`) serialiseren.
- Secret-getypeerde velden zijn standaard gemaskeerd; `decrypt_config` mag vanaf
  precies één allowlisted endpoint.

### 4.5 Authenticatie-hardening (standaard aan)

- Wachtwoord-hashing: Argon2id (bcrypt-fallback), per-user salt.
- **`PasswordPolicy`** (ADR 0032): standaard 12+ tekens, 2+ tekenklassen,
  common-password-denylist; fail-closed bij de credential-grens (typed 422);
  productie weigert een versoepelde policy te booten; opt-out via
  `PasswordPolicy.relaxed(reason=…)`.
- **`LoginThrottle`** (ADR 0031): per-account lockout tegen credential stuffing
  (typed 429), standaard aan; expliciete `LoginThrottle.disabled(reason=…)`.
- **Token-revocatie** (ADR 0031): een per-user token-epoch (`token_version`) rijdt op
  elk access token; de principal-provider hercontroleert `is_active` én de epoch bij
  elk request. Deactivate / rolwijziging / password-reset / logout bumpt de epoch en
  doodt nog-niet-verlopen tokens mid-sessie.
- **Refresh-token-sessies** (ADR 0054): opaque, roterende refresh token in een
  httpOnly, path-scoped cookie; `/auth/refresh` roteert single-use met
  reuse-detectie; revocatie doodt hele refresh-families. Het access token blijft
  memory-only in de frontend; een page-reload behoudt de sessie zonder bearer tokens
  in web storage.
- Rolmodel-agnostische, tenant-bewuste login (ADR 0022); pluggable SSO (OIDC/SAML).
- **Gedistribueerde throttle-store** (ADR 0036): rate limiter en login-lockout delen
  één pluggable `ThrottleStore`; multi-instance deployments geven één gedeelde
  backend mee; een store-fout faalt gesloten.

### 4.6 Veilige transport- en invoer-defaults

- Security-headers (HSTS, X-Frame-Options, X-Content-Type-Options, referrer policy)
  via standaard-middleware; gestructureerde logging (ADR 0005).
- **CORS deny-by-default**; productie boot alleen met een expliciete allowlist.
- Elk `str`-veld in `*Create`/`*Update` vereist `max_length` (DoS-cap).
- **Paginering verplicht** (`Page[T]`) op elk list-endpoint; geen onbegrensde queries.
- ORM-only datatoegang; ruwe/geïnterpoleerde SQL is verboden; guards op
  engine-escape (`connection()`); geen `eval`/`pickle`/naïeve `datetime`.

### 4.7 Productie fail-fast guardrails

In `APP_ENV=production` weigert de app te booten bij: korte/ontbrekende
`SECRET_KEY`, permissieve CORS, debug aan, SQLite, ontbrekende TLS,
default-credentials, in-memory event bus, versoepelde password-policy, of een
principal-provider zonder revocatie-handhaving (`require_token_revocation=True`).

### 4.8 Audit by default

Muterende routes emitteren automatisch een audit-event (wie/wat/wanneer/voor/na) via
de audit-capability (ADR 0007) — traceerbaarheid zonder developer-bedrading; opt-out
is allowlisted. Elke write loopt door het geauditeerde `BaseService`-chokepoint; een
ongeauditeerde write geeft `UnauditedWriteError`.

### 4.9 Supply-chain-hygiëne

Gepinde dependencies + lockfiles, secret scanning, en generieke CI-backstops
(ADR 0033): ruff bandit (`S`-regels), import-linter-contract op de layer-0-grens,
en advisory `pip-audit` + `deptry` — CI-only, zonder de harness te verzwakken.

---

## 5. Capabilities (opt-in, zelf-registrerend)

Capabilities worden als extras geïnstalleerd
(`pip install "terp-core[users,…]"`) en registreren zichzelf via entry points:
router mounten + modellen aan migraties blootstellen zonder edits aan `main.py`.

| Capability | Functie |
|---|---|
| `auth` | Login, JWT (kort access + roterend refresh), logout, lockout, CSRF bij cookie-auth |
| `identity` | Principal-provider, token-validatie, revocatie-seam |
| `users` | Gebruikersbeheer; het geauditeerde chokepoint voor credential-wijzigingen |
| `access` | RBAC: rollen, grants, `can(module, action)` |
| `tenancy` | Pluggable tenancy-strategieën (zie hieronder) |
| `audit` | Auto-emit audit-trail op mutaties |
| `eventbus` | Getypeerde `EventCatalog` + NO-DRIFT `emit` (ADR 0008) |
| `outbox` | Transactionele outbox voor betrouwbare event-aflevering |
| `webhooks` | Uitgaande webhooks |
| `jobs_celery` | Achtergrondtaken (Celery) |
| `scheduler_apscheduler` / `scheduler_celery_beat` | Geplande taken |
| `sync` | Synchronisatie-ondersteuning |

### Tenancy-strategieën

| Strategie | "Tenant" = | Gebruik |
|---|---|---|
| `organization` (default) | `organization_id`; lezen/schrijven binnen tenant per rol | standaardprofiel |
| `single` | geen tenant-predicaat | alleen demo's/tests |
| `company-visibility` | `company_id` + `visibility` (PRIVATE/COMPANY_WIDE) + owner | zichtbaarheidsproducten |
| `scoped` | scoping-kolom (site/regio) met rolpoorten per scope | scoped producten |

Hetzelfde membership-filter bedient alle strategieën; de strategie bezit de eigen
resource-permissies (`can_read` / `can_mutate` gescheiden).

---

## 6. Migraties (ADR 0027)

- Elk tabel-bezittend pakket (capability of app-module) levert zijn **eigen lineaire
  Alembic-historie** binnen het pakket, geïsoleerd via een eigen
  `alembic_version_<label>`-tabel — geen gedeelde multi-branch graaf, dus geen
  merge-migraties of meerdere heads.
- Een Terp-eigen `env.py` (consumenten schrijven er nooit één) ontdekt alle
  historieën; **`terp migrate upgrade`** draait per pakket `upgrade head`, in
  FK-afhankelijkheidsvolgorde.
- Een **fail-closed boot-guard** weigert te starten tegen een schema dat achterloopt
  op de code.
- Driftbewaking: `assert_migrations_match_models` (migraties == modellen) en de regel
  `tables_have_migrations` (een tabelmodel zonder migratie faalt de build).
- Ondersteund: `stamp` / `heads` / `merge` / gelabelde `downgrade`; SQLite-only
  batch-mode; conformance-test install → upgrade → downgrade.

---

## 7. Frontend-contract & multi-stack-strategie

De frontend is een **conformante consument van een contract**, geen vast onderdeel.
Elke stack implementeert hetzelfde stack-agnostische contract:

1. **API-client** — gegenereerd uit de backend-OpenAPI; één bron van waarheid, geen
   drift, geen hand-geschreven fetch.
2. **Design-tokens** — framework-agnostisch (`tokens.json` → CSS-variabelen); één
   thema, meerdere renderers.
3. **Module/route/nav-manifest** — declaratieve beschrijving van het UI-oppervlak per
   module; elke stack levert een dunne adapter (router + sidebar).
4. **Auth/sessie-contract** — `login`, `refresh`, `currentUser`,
   `can(module, action)` met identieke semantiek (token/cookie-afhandeling,
   route-guards, UI-gating op backend-rollen).
5. **Boundary-lint-spec** — de regels (geen cross-module-imports, tokens-only
   styling, geen ruwe `<button>`/`<input>`, geen `dangerouslySetInnerHTML` zonder
   allowlist, routed pages voor formulieren) staan **als data** in
   `@terp/eslint-boundaries`; per stack alleen een parser-adapter.

**De equalizer**: `@terp/conformance` is een stack-agnostische Playwright-suite die
elke stack-core moet halen — zelfde routes, zelfde guards, zelfde
a11y-landmarks, zelfde token-gedreven visuals, zelfde error-envelope-afhandeling.
Een stack toevoegen of upgraden = "maak de conformance-suite groen".

Uitrol: React eerst (definieert het contract by construction); Svelte als
conformance-gedreven port daarna. Elk klantproject **pint één stack**; het platform
onderhoudt er meerdere.

---

## 8. De enforcement-harness (`terp-arch`)

- Geleverd als **geversioneerde dependency**, geparametriseerd over de `app/` (en
  `frontend/`) van de consument — de klant draait de regels maar kan ze niet bewerken.
- Generieke checks gedelegeerd aan onderhouden tools (Tach/import-linter voor
  layering, deptry/pip-audit voor dependencies, ruff voor security); alleen
  domeinspecifieke regels zijn bespoke.
- **Escape-hatch-budget (ratchet)**: het aantal `# arch-allow-*`-markers moet
  overeenkomen met een ingecheckte JSON (bv.
  [apps/example/escape-hatch-budget.json](../apps/example/escape-hatch-budget.json))
  en mag alleen dalen. Nieuwe uitzonderingen vereisen een gejustificeerde
  budget-bump in dezelfde change.
- **"Docs can't lie"** (ADR 0030): `terp guide rules` wordt gegenereerd uit de live
  regel-registry; pariteits-metatests laten de gate falen als een regel, trait of
  capability-seam zonder recept/documentatieregel verschijnt, of als een
  "enforced by `X`"-claim niet meer naar een echte test verwijst.
- Snel (< enkele seconden, AST/statisch, geen app-import) zodat het elke push gate.

### Belangrijkste fitness-regels (selectie)

`routes_declare_policy` · `mutations_require_write_role` ·
`safe_methods_are_read_only` · `list_routes_paginate` ·
`str_fields_have_max_length` · `no_raw_sql` · `no_raw_connection_access` ·
`reads_use_base_query` · `no_manual_ownership_checks` ·
`schemas_exclude_sensitive_fields` · `canonical_module_shape` ·
`tables_have_migrations` · `test_core_boundary` (layer-0 keystone) ·
`test_no_placeholder_namespace` · `test_vendored_core_unmodified`

---

## 9. Agent-ervaring en tooling

### De `terp`-CLI

| Commando | Functie |
|---|---|
| `terp new module <naam>` | Scaffoldt een canonieke module (map, manifest, passerende test) |
| `terp guide [onderwerp]` | In-repo authoring-gids en recepten (bv. `terp guide ownership`), gegenereerd uit de live registry |
| `terp inspect control-plane` | Authority-maps: welke policies/permissies gelden waar |
| `terp inspect jobs` | Overzicht van geregistreerde jobs |
| `terp migrate …` | Per-pakket migratie-orkestratie (upgrade/downgrade/stamp/heads/merge) |
| `terp jobs run/list/worker/scheduler` | Achtergrondtaken draaien en beheren |
| `terp api-docs` | Genereert `docs/platform-api.md` (publieke API-referentie) |
| `terp openapi` | Exporteert het OpenAPI-contract |

### Zichtbaarheid zonder bewerkbaarheid (ADR 0034)

- **`vendor/terp-core/`**: een read-only, byte-exacte spiegel van de gepackagede
  kernel — de agent heeft monorepo-niveau zicht op de core;
  `test_vendored_core_unmodified` faalt gesloten bij drift.
- Gegenereerde API-docs + `.pyi`-stubs als primaire referentie.
- `AGENTS.md` + `.github/copilot-instructions.md` + per-gebied instructies reizen
  mee in de repo; elke fitness-test geeft een **precieze, fixbare melding**
  ("module billing importeert `terp.core._internal.db`; gebruik
  `terp.core.SessionDep`").

---

## 10. Foutafhandeling, observability & operatie

- **Uniforme error-envelope**: getypeerde `AppError`s met consistente
  serialisatie; frontends handelen de envelope identiek af (conformance-getest).
- **Gestructureerde logging** met `extra=`-emissie; security-middleware standaard.
- **Health/readiness-endpoints** ingebouwd + connection-pool-configuratie (ADR 0024).
- **Middleware-seam**: `create_app(middleware=…)` als eersteklas compositiepunt
  (ADR 0021).
- **Event bus**: getypeerde catalogus; producties vereisen een echte broker
  (in-memory bus weigert in productie).

---

## 11. Packaging, versionering & upgrades

- **Semver per pakket**; het publieke API-oppervlak van `terp.core` is het
  semver-contract. Patch/minor breken nooit modules; een breaking major laat de
  klant-gate falen met een precieze melding.
- Capabilities zijn extras; "stadia" zijn geïnstalleerde capabilities, geen aparte
  repo's.
- `copier update` haalt scaffold-wijzigingen (CI, config, instructies) binnen.
- Frontend-cores per stack geversioneerd, gegate door de conformance-suite.
- Eén platform-monorepo (atomaire contract-evolutie: breaking change + geregenereerde
  client + frontend-cores + conformance in één PR); elk klantproject is een eigen
  monorepo met alleen modules.

---

## 12. Huidige status (per 2026-07)

- **Backend**: `terp-core`-kernel, `terp-arch`-harness, `terp`-CLI en de
  capabilities zijn gebouwd en gegate op **100% line coverage** (721+ tests);
  de complete autorisatiematrix (endpoint / rij-lezen / rij-schrijven) staat.
- **Migraties** (Phase 7), **agent-visibility** (Phase 6) en de **universele
  regelset** (ADR 0037) zijn gereed.
- **Frontend-pakketten** zijn in opbouw; React is de eerste stack.
- **Dogfood**: [apps/example/](../apps/example/) is een neutrale secure-CRUD-app
  (o.a. `notes`, `tasks` en het owner-scoped `journals`) die elke garantie
  end-to-end bewijst en de harness schoon passeert.
- Live tracker: [docs/internal/STATUS.md](internal/STATUS.md).

### De gate draaien

```bash
uv run pytest        # synct de workspace en draait de volledige gate
```

---

## 13. Samenvatting in één zin

**Terp levert een onderhouden kern + opt-in capabilities + een meegeleverde,
onverzwakbare handhavingslaag, zodat het veilige pad het standaardpad is: wie niets
bijzonders doet krijgt een geauthenticeerd, tenant-geïsoleerd, geauditeerd,
gepagineerd en gecontracteerd resultaat — en elke afwijking is expliciet, zichtbaar
en gebudgetteerd.**
