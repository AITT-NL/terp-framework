# 0177 — Egress is refused at the socket, not only at the import

- **Status:** Accepted and implemented (2026-10-06). `install_egress_guard` in `terp-cap-egress`
  holds the standard library's socket events on IPv4 and IPv6 sockets to the declared egress,
  whichever library raises them, and refuses to install in a process that runs uvloop, which
  raises none. Held by `tests/architecture/test_egress_guard.py`.
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
the events the standard library's `socket` module raises, whichever library calls it, and holds
exactly these:

- **A name lookup: `socket.getaddrinfo` and `socket.gethostbyname`** (the second is raised by
  `gethostbyname` and `gethostbyname_ex`). A hostname must be declared: a host an `EgressPolicy`
  allows, a host a vendor SDK is declared to reach, or infrastructure. An undeclared name is
  refused before these calls look it up, so it does not reach DNS through them. `localhost` and
  IP literals pass this rule: they name an address, and the next rule holds addresses. A server
  binding `0.0.0.0` looks it up too, and the event does not say whether a lookup is passive.
- **A connection or a datagram on an `AF_INET` or `AF_INET6` socket: `socket.connect`** (raised
  by `connect` and `connect_ex`), **`socket.sendto` and `socket.sendmsg`.** An address inside the
  SSRF denylist (private, loopback, link-local, site-local, cloud metadata) is refused unless it
  is declared infrastructure. A literal metadata address is refused, and so is a private address.
  So is a declared public name that rebinds to a private address when the library looked it up
  first and connects by address, because the connect sees the address it resolved to.
- **A peer given by name is resolved by the guard.** CPython resolves the peer of a `connect` or
  `sendto` by name inside the call, with no lookup event. So the guard holds the name to the name
  rule, resolves it itself, and holds every address it names for the socket's family to the
  address rule. `localhost` is no exception at the connect: its loopback addresses are refused
  unless loopback is declared infrastructure. The guard's own lookups, and any socket a custom
  resolver opens, pass straight through, marked per thread, so the guard never re-enters itself.
- **A peer it cannot read is refused.** A host that is neither text nor bytes on an IP socket is
  refused rather than waved through. A socket of another family (`AF_UNIX`, `AF_PACKET`,
  `AF_NETLINK`) has no IP peer and passes.

**The declaration says what the deployment runs on.** `EgressGuard` takes `hosts` (exact public
names, never an address and never with a port) and `infrastructure` (the database, Redis, the
mail relay, a collector), given as hostnames, IP literals or CIDR networks. Every name must be
one the resolver can encode, so a malformed one fails at declaration rather than inside some
later connect. Only infrastructure may sit on a private address. Infrastructure names are
resolved when the guard is installed, again on the first connect to a private address the guard
does not recognise, and after that at most every five seconds, so a database that moves is found
without a lookup on every connect. The window is claimed under a lock and the names resolved
outside it, so a slow DNS server holds up only the connect that asked, and a miss while another
thread resolves is decided on the addresses already known. A resolved name never sanctions a
cloud metadata address (`169.254.169.254`, `fd00:ec2::254`); only an explicit literal or network
can. `EgressGuard.for_policies(*policies, hosts=..., infrastructure=...)` builds the guard the
declared policies imply. A policy that opens the denylist (`allow_private_addresses`) has
declared sanctioned internal targets, so its hosts join the infrastructure.

**A refusal is `EgressRefusedError`**, the client's own 502, with
`log_context["control"] = "egress_guard"`. It is deliberately not an `OSError`. A library that
catches `OSError` to wrap or retry a connection failure does not swallow it, and the log names
the guard. The egress client passes it on as a refusal and records the attempt as refused.

**A process the guard cannot see into is refused, not half-held.** uvloop resolves names and
opens connections inside libuv, which raises no audit event, so every connection made on its
event loop would pass unseen while the declaration read as enforced. `install_egress_guard`
raises `EgressGuardUnsupportedError` when uvloop is imported, is the running loop or is the
event-loop policy, and the hook refuses an `import uvloop` after install. That second half is
the one that matters for a server: uvicorn run as one process imports the application before
it creates its loop, and picks uvloop whenever it is installed (`uvicorn[standard]`). The error
tells the operator to run uvicorn with `--loop asyncio`, and a worker or scheduler that installs
the guard with `asyncio.run`.

**One hook per process, installed once.** An audit hook cannot be removed. The hook reads the
guard in force on every event, and returns at once when there is none or the event is neither a
socket event nor an import. Installing again replaces the guard. Uninstalling leaves the hook
inert. The hook opts in to tracing (`__cantrace__`) so that coverage and a debugger can see it,
because CPython otherwise pauses tracing inside audit hooks. This changes nothing the hook
decides.

**Opt-in, like the shared-store promises.** It is installed in the composition root that the web
process and the worker both run. Nothing changes for an app that does not install it. The
template wires no egress today, so making it a default belongs with a production profile for the
template, not here.

## Consequences

**What it cannot see is named, not assumed.**

- **uvloop, and any event loop written in native code.** uvloop is refused, as above. Another
  event loop written in native code is invisible the same way and must not be used with the
  guard.
- **Native clients.** A client in native code that opens its own sockets (libpq, the gRPC C
  core, librdkafka) raises no Python audit event. Those are infrastructure drivers in practice,
  and the deployment's network policy is their control. The guard does not replace one.
- **A connect by name is resolved before its event.** CPython resolves the name before it raises
  the connect event. An undeclared name given to `connect` or `sendto` therefore reaches DNS
  before the connect is refused, and the guard's own resolution of a declared name can differ
  from the one CPython connects to, which leaves a rebinding window for that call shape alone.
  The common stacks (`create_connection`, asyncio, httpx, urllib3) look up first and connect by
  address, and an address is held exactly.
- **Public addresses.** A connection to a public IP literal passes. The name rule is what holds
  public destinations. A dependency that dials public addresses by literal is beyond what a
  declaration of names can express.
- **Reverse lookups** (`gethostbyaddr`, `getnameinfo`) are not held. `socket.getfqdn()`, which
  `smtplib` calls for its greeting, makes one for the machine's own name.
- **How a refusal arrives.** Under an async client (httpx on anyio) a refused connect can arrive
  inside an `ExceptionGroup`, which the error envelope renders as a 500 rather than the 502.
  And since it is not an `OSError`, the connection-error handling of `create_connection` and
  urllib3 does not close the refused socket either: it is left to the garbage collector, with a
  `ResourceWarning`.
- **Windows.** The `socketpair` fallback that every asyncio event loop uses on Windows connects
  to `127.0.0.1`, so creating an event loop after install is refused there unless loopback is
  declared infrastructure. The production target is Linux, and the guard is built for it.
- **Code in the process.** The guard holds where the process is steered. Code running in it can
  reach the network without the `socket` module at all, and is not what it holds.

**Verified against real stacks, not only events.** In the suite: a real `getaddrinfo` and
`gethostbyname` of an undeclared name, a real `connect` to the metadata address, `http.client`
and `urllib` to the metadata address, the egress client's own transport to an undeclared private
address, and a real `connect` and `sendto` to `localhost` by name are refused before the network
is touched; a resolver that raises socket events of its own does not deadlock the guard. Outside
the suite, in a container:

- httpx to an undeclared name was refused, and so was httpx to `169.254.169.254`.
- urllib to a private literal was refused.
- httpx to a declared name went through and reached the host.
- An asyncio server bound to `0.0.0.0` answered a client over declared loopback.
- `uvicorn` with its default loop and uvloop installed refused to start once the application
  installed the guard; with `--loop asyncio` it served, and an async httpx call to an undeclared
  name was refused.
- `connect(("localhost", port))`, a `DatagramHandler("localhost", port)`, a declared name mapped
  to `127.0.0.1` in the hosts file and a `bytearray` host were refused; an `AF_PACKET` datagram
  on `lo` passed.

**The Terp Standard follows.** `backend/no_raw_outbound_http` records its runtime applicability
as `not-applicable`. Its next release moves it to `required`, with this guard as the reference.
The entry is descriptive, and nothing here waits for it.
