/**
 * The type-level route table an app's generated `routes.gen.d.ts` augments (ADR 0092).
 *
 * `buildAppRouter` realises routes at runtime from manifest data, so TanStack Router's
 * own type registry is empty for every Terp app: no route path and no param name is
 * checked anywhere, and a typo ships green. The information to check them is already
 * checked in — the manifests are static data — so `terp routes` extracts it and emits a
 * committed declaration file that augments this interface:
 *
 * ```ts
 * declare module "@terpjs/react-core" {
 *   interface TerpRouteTable {
 *     "/records": Record<never, never>;
 *     "/records/:recordId": { recordId: string };
 *   }
 * }
 * ```
 *
 * Paths are keyed in the manifest's stack-agnostic spelling (`:recordId`, not `$recordId`),
 * which is the spelling {@link useTerpNavigate} accepts and translates.
 *
 * Deliberately empty here: with no generated file the table has no keys, every helper
 * below falls back to `string`, and an app that has not generated keeps exactly today's
 * behavior. Generating is what turns these checks on.
 */
// eslint-disable-next-line @typescript-eslint/no-empty-object-type -- augmentation target
export interface TerpRouteTable {}

/** True when no `routes.gen.d.ts` has augmented {@link TerpRouteTable}. */
type Ungenerated = keyof TerpRouteTable extends never ? true : false;

/** Every route path the app's manifests declare — or `string` before generating. */
export type TerpRoutePath = Ungenerated extends true ? string : keyof TerpRouteTable & string;

/** The params of one declared route (`Record<never, never>` for a paramless route). */
export type TerpRouteParams<P extends TerpRoutePath> = P extends keyof TerpRouteTable
  ? TerpRouteTable[P]
  : Record<string, string>;

/**
 * Every param name declared by any route — or `string` before generating.
 *
 * This is the union across all routes, not per route: it refuses a name no route
 * declares (the reported failure mode, where a typo silently yielded `undefined`),
 * while a name belonging to a *different* route stays a runtime refusal. Read params
 * through {@link useRouteParams} when you want the exact, per-route check.
 */
export type TerpRouteParamName = Ungenerated extends true
  ? string
  : { [P in keyof TerpRouteTable]: keyof TerpRouteTable[P] }[keyof TerpRouteTable] & string;

/**
 * A navigation target: a declared path, plus that path's params when it takes any.
 * A paramless route refuses a `params` object; a parameterised one requires it, with
 * the names the manifest declared. Before generating, this is the loose shape.
 */
export type TerpNavigateTarget = Ungenerated extends true
  ? { to: string; params?: Record<string, string> }
  : {
      [P in keyof TerpRouteTable & string]: keyof TerpRouteTable[P] extends never
        ? { to: P; params?: undefined }
        : { to: P; params: TerpRouteTable[P] };
    }[keyof TerpRouteTable & string];
