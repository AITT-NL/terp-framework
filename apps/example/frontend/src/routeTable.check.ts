/**
 * Compile-time proof that the generated route table actually enforces (ADR 0092).
 *
 * Type-only, no runtime role. Every `@ts-expect-error` below inverts the assertion: this
 * file stops compiling the moment the check stops working — a stale `routes.gen.d.ts`, a
 * lost augmentation, or a `TerpRouteTable` that silently fell back to `string` would all
 * turn these deliberate mistakes green again, and the failure would otherwise be
 * invisible (that invisibility is the bug ADR 0092 exists to fix).
 */
import type { TerpNavigateTarget, TerpRoutePath } from "@terpjs/react-core";

// A path this app's manifests declare is accepted.
const declared: TerpRoutePath = "/explorer/devices";

// A path no manifest declares is refused — the dead link that used to ship green.
// @ts-expect-error — "/definitely/not/a/route" is not a declared route path
const dead: TerpRoutePath = "/definitely/not/a/route";

// A paramless route refuses params: the table knows this route takes none.
// @ts-expect-error — "/files" declares no params
const spurious: TerpNavigateTarget = { to: "/files", params: { nope: "x" } };

// A declared paramless route needs no params.
const fine: TerpNavigateTarget = { to: "/files" };

export type { TerpRoutePath };
void declared;
void dead;
void spurious;
void fine;
