# 0177 — Egress is refused at the socket, not only at the import

- **Status:** Accepted and implemented (2026-10-06). `install_egress_guard` in `terp-cap-egress`
  holds every Python socket in the process to the declared egress. Held by
  `tests/architecture/test_egress_guard.py`.
- **Date:** 2026-10-06
- **Relates:** [ADR 0117](0117-the-egress-capability-the-rule-was-already-naming.md) (the egress
  capability and its client), [ADR 0136](0136-a-security-rule-does-not-stop-at-the-module-tree.md)
  (the rule's scope), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (two-layer
  enforcement), [ADR 0084](0084-runtime-applicability-classification.md) (a rule's runtime
  applicability is recorded)

---

## Context

`no_raw_outbound_http` refuses `httpx`, `requests`, `urllib3`, `aiohttp`, `socket` and their
kin in the application's own source, and sends the author to the egress client. The client
holds the declaration for every call made through it: the exact-host allowlist, the SSRF
denylist and the pinned address.

A vendor SDK is a dependency. It builds its own HTTP client inside the process, usually on
`httpx` or `requests`. The rule reads the application's imports, and none of them names that
client. `import vendor_sdk` passes, and installed packages are never scanned. The client is
never asked either. So an SDK's traffic met neither the allowlist nor the denylist. An SDK
whose base URL is a setting an administrator can edit is an SSRF primitive the platform could
not see: point it at `http://169.254.169.254/` and it goes there.

The rule's catalog entry records that its runtime half is not applicable: traffic "cannot be
attributed to an app module from inside the process", and network-level egress policy "is
deployment configuration". The first is true. A connect cannot say which module asked for it.
But the declaration is about the process, not the module. The process declares what it may
reach, and a refusal of everything else needs no attribution at all.

## Decision

**The declaration is held at the socket, for every library in the process.**
`install_egress_guard(EgressGuard(...))` registers a Python audit hook (PEP 578). The hook sees
the events every Python network stack raises on its way out, whichever library raises them.

- **`socket.getaddrinfo`, a name lookup.** A hostname must be declared: a host an
  `EgressPolicy` allows, a host a vendor SDK is declared to reach, or infrastructure. An
  undeclared name is refused before it resolves, so an undeclared destination is never
  contacted and a steerable URL cannot reach an internal name. `localhost` and IP literals pass
  this rule. They name an address, and the next rule holds addresses. A server binding
  `0.0.0.0` looks it up too, and the event does not say whether a lookup is passive.
- **`socket.connect`, `socket.sendto` and `socket.sendmsg`, a connection or a datagram.** An
  address inside the SSRF denylist (private, loopback, link-local, cloud metadata) is refused
  unless it is declared infrastructure. A literal metadata address is refused, and so is a
  private address. So is a declared public name that rebinds to a private address, because the
  connect sees the address it resolved to. A host passed here by name is held to the name rule.

**The declaration says what the deployment runs on.** `EgressGuard` takes `hosts` (exact public
names) and `infrastructure` (the database, Redis, the mail relay, a collector), given as
hostnames, IP literals or CIDR networks. Only infrastructure may sit on a private address.
Infrastructure names are resolved by the guard on the first connect to a private address it
does not recognise, and again at most every five seconds, so a database that moves is found
without a lookup on every connect. `EgressGuard.for_policies(*policies, hosts=..., infrastructure=...)`
builds the guard the declared policies imply. A policy that opens the denylist
(`allow_private_addresses`) has declared sanctioned internal targets, so its hosts join the
infrastructure.

**A refusal is `EgressRefusedError`**, the client's own 502, with
`log_context["control"] = "egress_guard"`. It is deliberately not an `OSError`. A library that
catches `OSError` to wrap or retry a connection failure does not swallow it: it reaches the
caller as itself, and the log names the guard.

**One hook per process, installed once.** An audit hook cannot be removed. The hook reads the
guard in force on every event, and returns at once when there is none or the event is not a
socket event. Installing again replaces the guard. Uninstalling leaves the hook inert. The hook
opts in to tracing (`__cantrace__`) so that coverage and a debugger can see it, because CPython
otherwise pauses tracing inside audit hooks. This changes nothing the hook decides.

**Opt-in, like the shared-store promises.** It is installed in the composition root that the web
process and the worker both run. Nothing changes for an app that does not install it. The
template wires no egress today, so making it a default belongs with a production profile for the
template, not here.

## Consequences

**What it cannot see is named, not assumed.**

- **Native clients.** A client in native code that opens its own sockets (libpq, the gRPC C
  core, librdkafka) raises no Python audit event. Those are infrastructure drivers in practice,
  and the deployment's network policy is their control. The guard does not replace one.
- **A connect by name.** `socket.connect(("name", port))` resolves inside CPython without a
  lookup event. The name is still held to the name rule, but the address it resolves to is not
  checked against the denylist. The common stacks resolve first and connect by address
  (`create_connection`, asyncio, httpx, urllib3), and those are checked.
- **Public addresses.** A connection to a public IP literal passes. The name rule is what holds
  public destinations. A dependency that dials public addresses by literal is beyond what a
  declaration of names can express.

**Verified against real stacks, not only events.** In the suite: a real `getaddrinfo` of an
undeclared name, and a real `connect` to the metadata address, are refused before the network
is touched. Outside the suite, in a container:

- httpx to an undeclared name was refused, and so was httpx to `169.254.169.254`.
- urllib to a private literal was refused.
- httpx to a declared name went through and reached the host.
- An asyncio server bound to `0.0.0.0` answered a client over declared loopback.

**The Terp Standard follows.** `backend/no_raw_outbound_http` records its runtime applicability
as `not-applicable`. Its next release moves it to `required`, with this guard as the reference.
The entry is descriptive, and nothing here waits for it.
