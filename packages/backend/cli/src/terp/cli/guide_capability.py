"""The ``terp guide capability`` topic: using the opt-in capabilities, and composing an app."""

from __future__ import annotations

TOPIC = """\
Using capabilities

- Capabilities are opt-in packages (terp-cap-*). Every scaffolded app already has the
  BASE PROFILE — auth, identity, users, groups, access, audit — so authentication,
  accounts, group membership, permission checks and the audit trail are wired before you
  write anything. Install the others you need.
- WHO IS CALLING, in words a person reads: take `caller: CallerDep` on the route.
      from terp.capabilities.identity import CallerDep
      def pause(name: str, caller: CallerDep, session: SessionDep) -> None:
          service.pause(session, name, decided_by=caller.name)
  `caller.name` is a user's email or a service account's name, read from the live row;
  `caller.id` is the key to store when a record must point at who did it. Never take a
  "decided by" from the request body (it is whatever the client says), and never build
  an IdentityService inside a module to look the caller up.
- SEE WHAT EXISTS BEFORE YOU BUILD IT:
      terp inspect capabilities
  lists every maintained capability, whether this app already has it, the exact
  `uv add` line and the composition-root wiring it expects. For a capability you
  ALREADY have it also prints `not used here`: wiring points the package exports and
  your source never mentions. That line exists because an installed capability looks
  finished -- so a seam it grows in a later release is invisible from inside the
  project, and at a release every day or two nobody reads the changelog delta. Most
  of what it lists are alternatives you correctly did not take; it is information,
  not a finding. Durable delivery, realtime
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
  httpx2 / requests / urllib.request / urllib3 / aiohttp in a module is refused by the
  no_raw_outbound_http rule — SSRF protection, egress allowlists and timeout policy
  belong behind one declared capability, not scattered per call site. That capability
  is `terp-cap-egress`, and it is a declaration rather than a client you configure at
  the call site:
      from terp.capabilities.egress import EgressClient, EgressPolicy
      rates = EgressClient(EgressPolicy(
          allowed_hosts=("api.exchange.example",),   # EXACT hosts; empty permits nothing
          timeout_seconds=5.0,                       # no per-call override, on purpose
      ))
      body = rates.get("https://api.exchange.example/v1/rates").content
  Every resolved address is checked against the SSRF denylist and the connection is
  PINNED to the one that passed (so a rebind between the check and the connect cannot
  land on a private address), redirects are never followed, and every attempt —
  refusals included — reaches the optional `observer=` hook, which is where metering
  and egress auditing attach. A sanctioned internal target is a declared
  `allow_private_addresses=True`, visible in the composition root, never a quiet
  exception inside the client.
- A vendor SDK builds its own HTTP client, so neither the rule (it reads YOUR imports)
  nor EgressClient sees its traffic. Hold the whole process to the declaration at the
  socket, in the composition root the web process and the worker both run:
      install_egress_guard(EgressGuard.for_policies(
          rates_policy,                              # every EgressPolicy you declared
          hosts=("api.vendor.example",),             # what an SDK calls, by exact name
          infrastructure=("db", "redis", "smtp.relay.internal"),  # names, IPs or CIDRs
      ))
  It holds what goes through Python's socket module on IPv4/IPv6, whichever library
  calls it: a lookup of an undeclared name (getaddrinfo, gethostbyname) is refused
  before it is made, and a connect or datagram into a private / loopback / link-local /
  metadata range is refused unless it is declared infrastructure; a peer given by name
  (localhost too) is resolved and every address held. The refusal is EgressRefusedError
  (502); under an async client it can arrive inside an ExceptionGroup. It cannot see
  uvloop, so it refuses to install beside it and refuses `import uvloop` after it: run
  uvicorn with --loop asyncio (uvicorn[standard] picks uvloop otherwise), and a worker
  or scheduler with asyncio.run. Native drivers that open their own sockets (libpq,
  gRPC's C core) are invisible to it and a public IP literal passes; the deployment's
  network policy holds those. Built for Linux: on Windows asyncio's socketpair connects
  to loopback, so a new event loop is refused unless loopback is declared.
- Credentials never live in module source: a credential-shaped assignment (password,
  api_key, token, ...) to a string literal — or a recognizable secret-token literal
  anywhere — is refused by the no_hardcoded_credentials rule. Wire secrets through
  settings / sealed config (ADR 0055), never source.
- Sending e-mail is a capability too: `import smtplib` is refused by the same
  no_raw_outbound_http rule, and terp-cap-mail is where it goes — `terp guide mail`.
- THE MODULES AN APP MOUNTS ARE THE SAME IN EVERY ENVIRONMENT (ADR 0211). Hand create_app
  every module, always. A module added under a condition is mounted where the condition
  holds and nowhere else, so the app serves routes the access check never saw where it ran:
      # refused (module_list_is_unconditional)
      modules = [login_module, me_module]
      if os.environ.get("OIDC_ISSUER"):
          modules.append(oidc_module)
      # compliant: mounted always, and its routes refuse while nothing is configured
      create_app([login_module, me_module, oidc_module], ...)
  A capability whose configuration is per environment is built in every environment and
  answers a typed refusal while it has none: build_oidc_module(providers, resolver,
  allow_no_provider=True) mounts the SSO routes with an empty list, and each answers
  503 sso_not_configured. The settings decide what a mounted route does, never whether
  it exists.
- APP CODE CALLS THE FRAMEWORK AND NEVER REPLACES ITS FUNCTIONS (ADR 0213). A check that
  runs the framework's code is worth what that code is, and one assignment turns it off
  with every other check still green:
      # refused (no_framework_patching)
      import terp.core.authz_surface as surface
      surface.startup_refusal = lambda *args, **kwargs: None
      setattr(routing, "iter_route_contexts", mine)       # fastapi and starlette too
      sys.modules["terp.core.app"] = shim
      mock.patch("terp.core.app.create_app", mine).start()
      settings.ENVIRONMENT = "local"
  Change behaviour through the seam the framework gives for it: a create_app parameter
  (principal_provider=, middleware=, lease_store=), a ModuleSpec and its Policy, a
  registered predicate. In a test, monkeypatch.setattr and mock.patch stay the way to
  replace a function: the rule does not read `tests` directories.
"""
