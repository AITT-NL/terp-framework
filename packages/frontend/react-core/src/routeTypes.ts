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

/**
 * The query-string half of the same table (ADR 0096): path -> its declared search keys.
 *
 * Params were checked and search keys were not, which sounds like a gap and behaves like
 * a hole: a list screen's filters, its sort and its page cursor all live in the query
 * string, so *every* screen with a filter had to leave the typed seam and reach for the
 * router's own `useNavigate` / `useSearch` — losing path checking too, on the majority of
 * screens. Declaring the keys in the manifest (`search: ["status", "page"]`) is what lets
 * navigation and reads stay inside the checked seam.
 *
 * Keyed only for routes that declare keys, so a route with none refuses `search` outright
 * rather than accepting anything. Values are `string | undefined`: a query parameter is
 * text and is absent until set — parsing is the screen's business, and the declaration is
 * what stops the *key* being a typo.
 */
// eslint-disable-next-line @typescript-eslint/no-empty-object-type -- augmentation target
export interface TerpRouteSearchTable {}

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
 * One route's declared query-string keys, all optional.
 *
 * Three cases, and the middle one is the point. Before `terp routes` has generated, the
 * shape is loose (like {@link TerpRouteParams}) so an app that has not adopted keeps
 * today's behavior. Once generated, a route that declared keys gets exactly those; a
 * route that declared **none** gets `Record<never, never>`, so passing `search` to it is a
 * typecheck error rather than a value silently dropped into the URL.
 */
export type TerpRouteSearch<P extends TerpRoutePath> = P extends keyof TerpRouteSearchTable
  ? TerpRouteSearchTable[P]
  : Ungenerated extends true
    ? Record<string, string | undefined>
    : Record<never, never>;

/** Every search key any route declares — or `string` before generating. */
export type TerpRouteSearchKey = Ungenerated extends true
  ? string
  : { [P in keyof TerpRouteSearchTable]: keyof TerpRouteSearchTable[P] }[keyof TerpRouteSearchTable] &
      string;

/**
 * A navigation target: a declared path, that path's params when it takes any, and that
 * path's declared search keys when it reads any.
 *
 * A paramless route refuses a `params` object; a parameterised one requires it, with the
 * names the manifest declared. `search` is always optional (a route may be visited with
 * no filters applied) but its *keys* are the declared ones, so a typo is a typecheck
 * error and a route that declares no search keys refuses the property. Before generating,
 * this is the loose shape.
 */
export type TerpNavigateTarget = Ungenerated extends true
  ? { to: string; params?: Record<string, string>; search?: Record<string, string | undefined> }
  : {
      [P in keyof TerpRouteTable & string]: (keyof TerpRouteTable[P] extends never
        ? { to: P; params?: undefined }
        : { to: P; params: TerpRouteTable[P] }) & { search?: TerpRouteSearch<P> };
    }[keyof TerpRouteTable & string];
