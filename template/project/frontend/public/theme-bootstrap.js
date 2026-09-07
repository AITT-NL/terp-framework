/*
 * The palette lands on <html> BEFORE the first paint.
 *
 * Why this file exists at all: the theme is a person's own choice, so it lives in
 * localStorage, and only script can read it. ThemeProvider does read it — and applies it in
 * an effect, which is the first moment React has committed anything. The document body is
 * empty until then, so the browser has already painted a canvas by the time the palette is
 * known: the token sheet's :root is the light palette, so a viewer who chose a dark one gets
 * a white flash on every reload. Not the viewer who follows their platform — the sheet's
 * prefers-color-scheme block covers that one before paint, with no script — which is why the
 * defect looks intermittent until you notice it tracks an EXPLICIT choice.
 *
 * A blocking classic script from the app's own origin, and each of those three words is a
 * constraint rather than a preference:
 *
 *   - BLOCKING (no defer, no async, no type="module") because a deferred script runs after
 *     the document is parsed, which is on the wrong side of the paint this exists to beat.
 *     Move it into the module entry point and the flash comes straight back.
 *   - CLASSIC and untranspiled, because public/ is copied verbatim: this file is served as
 *     written, in development and in production, so it is small ES5 with no imports and no
 *     dependency on the bundle. A syntax error here would be a silent no-op.
 *   - OWN ORIGIN, because production serves script-src 'self' with no 'unsafe-inline'
 *     (nginx.conf). The usual inline <script> in <head> would work in the dev server, which
 *     permits inline script for Vite's own preamble, and be refused in production with no
 *     error anyone reads. Same reason the appearance below is applied through CSSOM rather
 *     than a style attribute.
 *
 * The three facts it duplicates from the framework — the storage key, the theme names, and
 * which of them are dark — are held against their sources by
 * tests/architecture/test_theme_bootstrap.py, so a sixth theme cannot ship without this file
 * learning about it.
 *
 * An app that ships on a named palette declares it TWICE, and both halves are load-bearing:
 * `defaultTheme` in frontend/layout-contract.json, which is what ThemeProvider applies, and
 * the same name on the element in index.html (<html lang="en" data-theme="midnight">), which
 * is what paints it before this bundle exists. The attribute alone is not enough and fails in
 * the direction nobody expects: ThemeProvider defaults to "system", so it would REMOVE the
 * attribute on mount and the app would open on its palette and then leave it. This script
 * leaves a declared default alone and overrides it only for someone who has actually chosen.
 */
(function () {
  var STORAGE_KEY = "terp.theme";
  var THEMES = ["light", "dark", "midnight", "twilight", "contrast", "system"];
  var DARK = ["dark", "midnight", "twilight"];

  var root = document.documentElement;
  var stored = null;
  try {
    stored = window.localStorage.getItem(STORAGE_KEY);
  } catch (error) {
    // Private mode, or storage refused by policy. ThemeProvider swallows the same throw and
    // falls back to the app's default, so there is no CHOICE to pre-apply -- and the rest of
    // this script still has work to do, because an app that declares its palette on the
    // document has one either way. An earlier version returned here and took the appearance
    // with it, so a declared dark palette flashed white for exactly the viewers whose browser
    // refuses storage.
    stored = null;
  }

  if (stored === "system") {
    // A real choice, and it means "follow my platform" — so the attribute has to come OFF,
    // even when the document declares a default, or the sheet's prefers-color-scheme block
    // never gets to answer.
    root.removeAttribute("data-theme");
  } else if (stored !== null && THEMES.indexOf(stored) !== -1) {
    root.setAttribute("data-theme", stored);
  }
  // Anything else — no choice yet, or a theme name this build no longer ships — leaves the
  // document's own declaration standing. Stamping an unknown name would select no palette
  // block at all and suppress the platform default with it; ThemeProvider validates against
  // the same list and reaches the same answer on mount.

  // And then the appearance, which is the half that matters in development. `color-scheme`
  // is what the browser paints the canvas and the native scrollbars from, and it reaches
  // this document from the token sheet — which the entry point IMPORTS, so in a dev server
  // it arrives with the bundle and there is no palette at first paint whatever the attribute
  // says. Declaring it here paints the right canvas immediately in both builds.
  //
  // A BRIDGE, and ThemeProvider takes it back on mount: an inline value outranks every rule,
  // so leaving it would pin the native chrome to whatever was stored at load and a viewer
  // who then picks a light palette would keep dark scrollbars for the session.
  //
  // ONLY WHEN A PALETTE IS PINNED, and the empty case is left alone rather than declared as
  // "light dark". There is nothing to bridge there: with no attribute the token sheet's own
  // prefers-color-scheme block is what answers, and it answers before paint with no script at
  // all -- the one case that never flashed. Declaring the pair anyway put an inline value on
  // the document for a palette nobody chose, and an app composing TerpProvider without a
  // ThemeProvider would then keep it for the whole session: OS-dark native chrome on a light
  // app, from a bridge with nothing at the other end.
  var active = root.getAttribute("data-theme");
  if (active !== null) {
    root.style.colorScheme = DARK.indexOf(active) === -1 ? "light" : "dark";
  }
})();
