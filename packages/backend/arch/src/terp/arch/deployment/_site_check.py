"""The static-site recipe's check at build: markup the site's policy would break (ADR 0198).

The recipe's Dockerfile (:mod:`terp.arch.deployment._static_site`) carries :data:`SITE_CHECK` as
a heredoc and runs it with the build stage's Node over ``site/dist/``, so a page whose markup
the policy would break fails the image build rather than a browser. It is a program of its own:
a Node script, built-ins only, held as text the render copies byte for byte, and imported by
nothing but the recipe. Its first half, how it reads a page, is
:data:`~terp.arch.deployment._site_markup.SITE_MARKUP`; this module holds the second, what the
policy breaks and the run over ``dist/``, and joins the two.
"""

from __future__ import annotations

from terp.arch.deployment._site_markup import SITE_MARKUP

#: The refusal at build (decision 2). The policy (``_static_site.SITE_NGINX``) is the control: a
#: browser holds every page to it, whatever built the page. This check is a finder, run where a
#: failure has a file name: it looks in the markup for what the policy would break, so such a
#: page fails in the build log rather than silently in a browser. A page it passes is no promise
#: that the policy admits it.
#:
#: It reads the files nginx serves as documents by these names: ``.html``, ``.htm`` and
#: ``.shtml``, and as XML ``.xhtml``, ``.svg``, ``.xml``, ``.rss``, ``.atom``, ``.kml`` and
#: ``.xspf``, each as UTF-8; a ``.svgz`` it does not read, and the policy alone holds one. It
#: refuses an inline script that runs, a ``<style>`` element, a ``style`` attribute, an event
#: handler (any attribute named ``on`` and letters), a ``javascript:`` URL in any attribute that
#: holds a URL (an SVG animation of one and a refresh to one included), a ``<base href>``, an
#: ``<object>`` or ``<embed>``, a form that submits to another origin, an ``<iframe srcdoc>``
#: whose page holds any of these, and a load from another origin or a ``data:`` URL: a script
#: (an SVG one by ``href``, and a module preload), a stylesheet (an ``xml-stylesheet``
#: instruction's, an XSLT one included), a frame, an image (``img`` and its ``srcset``,
#: ``picture``'s ``source``, a video's ``poster``, an SVG ``image`` or ``feImage``, an ``input``
#: of type ``image``, a ``background``, an icon), media (``video``, ``audio``, ``source``,
#: ``track``), an SVG ``use``, a manifest, and a preload of a font, script, stylesheet, image,
#: media or fetch. An image or an icon may be a ``data:`` URL, as ``img-src`` allows, and a
#: frame ``about:blank``. It refuses a symbolic link anywhere under ``dist/``, which the image
#: copies as a link and nginx follows wherever it points.
#:
#: It never reads CSS (``url()``, ``@import``), what a script does or fetches, what an XSLT
#: stylesheet makes of a file, or a file in another encoding as that encoding, and it names the
#: first offending tag of each file only. A data block such as JSON-LD runs as nothing and
#: passes, and so does markup a browser reads as text or as a comment. Each refusal names the
#: file, its tag, and what to change.
SITE_CHECK = SITE_MARKUP + r"""
// The files a browser renders as a document when nginx serves them: text/html (.html, .htm,
// .shtml), and the XML types the image's mime.types names (.xhtml, .svg, .xml, .rss, .atom,
// .kml, .xspf; not .svgz, compressed bytes served with no encoding a browser could undo), in
// which a browser renders the XHTML, SVG and MathML they hold.
const DOCUMENT = /\.(?:html?|shtml|xhtml|svg|xml|rss|atom|kml|xspf)$/i;
const XML = /\.(?:xhtml|svg|xml|rss|atom|kml|xspf)$/i;

// The script types that run; a data block such as application/ld+json runs as nothing.
const RUNS = new Set([
  "", "module", "importmap", "speculationrules", "application/ecmascript",
  "application/javascript", "application/x-ecmascript", "application/x-javascript",
  "text/ecmascript", "text/javascript", "text/javascript1.0", "text/javascript1.1",
  "text/javascript1.2", "text/javascript1.3", "text/javascript1.4", "text/javascript1.5",
  "text/jscript", "text/livescript", "text/x-ecmascript", "text/x-javascript",
]);
// Every attribute that holds a URL a browser fetches or navigates to.
const URLS = new Set([
  "action", "archive", "background", "cite", "classid", "codebase", "data", "dynsrc",
  "formaction", "href", "icon", "longdesc", "lowsrc", "manifest", "ping", "poster", "profile",
  "src", "srcset", "xlink:href",
]);
// Of those, the ones that hold a list, each item a URL of its own.
const LISTS = { archive: /[\s,]+/, ping: /\s+/, srcset: /,/ };
// What an element loads as the page renders, by attribute, as the kind of load the policy
// holds it to. A link and a script are read on their own below.
const LOADS = {
  img: [["src", "image"], ["srcset", "image"]],
  image: [["src", "image"], ["srcset", "image"], ["href", "image"], ["xlink:href", "image"]],
  feimage: [["href", "image"], ["xlink:href", "image"]],
  source: [["src", "media"], ["srcset", "image"]],
  video: [["src", "media"], ["poster", "image"]],
  audio: [["src", "media"]],
  track: [["src", "media"]],
  iframe: [["src", "frame"]],
  frame: [["src", "frame"]],
  use: [["href", "use"], ["xlink:href", "use"]],
  body: [["background", "image"]],
  table: [["background", "image"]],
  td: [["background", "image"]],
  th: [["background", "image"]],
};
// What a <link rel="preload"> fetches, by its as=, as the kind of load.
const PRELOADS = {
  audio: "media", fetch: "connect", font: "font", image: "image", json: "connect",
  script: "script", style: "style", track: "media", video: "media", worker: "script",
};
// Each kind of load: what the page does, why it fails, and what to change. ALLOWED holds the
// one scheme besides the site's own that a kind may load: data: for an image or an icon, as
// the policy's img-src allows, and about: for a frame, which loads no other origin.
const KINDS = {
  image: ["loads an image from", "the policy's img-src 'self' data: refuses", "copy the image into the site's build and load it by its path"],
  icon: ["loads an icon from", "the policy's img-src 'self' data: refuses", "copy the icon into the site's build and link it by its path"],
  media: ["loads media from", "the policy's default-src 'self' refuses", "copy the file into the site's build and load it by its path"],
  font: ["loads a font from", "the policy's font-src 'self' refuses", "copy the font into the site's build and load it by its path"],
  connect: ["fetches from", "the policy's connect-src 'self' refuses", "copy the file into the site's build and fetch it by its path"],
  script: ["loads its script from", "the policy's script-src 'self' refuses", "copy the script into the site's build and load it by its path"],
  style: ["loads a stylesheet from", "the policy's style-src 'self' refuses", "copy the stylesheet into the site's build and link it by its path"],
  sheet: ["loads a stylesheet from", "the policy's style-src 'self' refuses", "copy the stylesheet into the site's build and name it by its path"],
  xslt: ["loads an XSLT stylesheet from", "the policy's script-src 'self' refuses", "copy the stylesheet into the site's build and name it by its path"],
  frame: ["frames", "the policy's default-src 'self' refuses", "link to the page instead, or frame one of the site's own"],
  use: ["uses a drawing from", "a browser loads into <use> from the page's own origin alone", "copy the drawing into the site's build and use it by its path"],
  manifest: ["loads its manifest from", "the policy's default-src 'self' refuses", "copy the manifest into the site's build and link it by its path"],
};
const ALLOWED = { image: "data", icon: "data", frame: "about" };

// A URL with every control character and space gone, wherever it stands: a URL parser drops
// tabs and newlines anywhere and the rest at either end, and dropping more refuses more.
const bare = (url) => url.replace(/[\x00- ]/g, "");
const scriptsUrl = (url) => bare(url).toLowerCase().startsWith("javascript:");
// Whether an attribute's value, or any item of a list one holds, is a javascript: URL.
const scriptsValue = (attribute, written) =>
  scriptsUrl(written) || (attribute in LISTS && written.split(LISTS[attribute]).some(scriptsUrl));

// What a URL names beyond a path on the site's own origin, or null: a scheme, or a host. The
// build cannot know its own host, so a URL that names one is refused whichever host it is, and
// the refusal says so: the policy admits the site's own origin written in full, and calling
// that "another origin" gave a cause that was not true. *allowed* is the one other scheme a
// kind of load may take.
const HOST = "a URL that names a host";
const UNLESS_OWN = " unless the host is the site's own, which the build cannot know";
const unlessOwn = (there) => (there.startsWith(HOST) ? UNLESS_OWN : "");
function elsewhere(url, allowed = null) {
  const plain = bare(url);
  const scheme = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(plain);
  if (scheme !== null) {
    const name = scheme[1].toLowerCase();
    if (name === allowed) return null;
    if (name === "http" || name === "https") return `${HOST} (${name}:)`;
    return name === "data" ? "a data: URL" : `another origin (${name}:)`;
  }
  return /^[\\/]{2}/.test(plain) ? HOST : null;
}

// The URL of each candidate of a srcset, its descriptors left behind.
function candidates(srcset) {
  const found = [];
  let at = 0;
  while (at < srcset.length) {
    while (at < srcset.length && /[\s,]/.test(srcset[at])) at += 1;
    const start = at;
    while (at < srcset.length && !/\s/.test(srcset[at])) at += 1;
    let url = srcset.slice(start, at);
    if (url.endsWith(",")) url = url.replace(/,+$/, "");
    else while (at < srcset.length && srcset[at] !== ",") at += 1;
    if (url) found.push(url);
  }
  return found;
}

// The refusal for a load of *kind* from *there*.
const loaded = (kind, there) => {
  const [what, why, remedy] = KINDS[kind];
  return `${what} ${there}, which ${why}${unlessOwn(there)}: ${remedy}`;
};

// A tag as a refusal quotes it: whole, or its first 117 characters.
const shown = (tag) => (tag.length > 120 ? `${tag.slice(0, 117)}...` : tag);

// An xml-stylesheet processing instruction that loads its stylesheet from elsewhere: CSS,
// which style-src holds, or XSLT, which script-src holds.
function instructionOffense(instruction) {
  if (!/^<\?xml-stylesheet[\t\n\r ]/.test(instruction)) return null;
  const [attrs] = readTag(instruction.replace(/\?>$/, ">"), 16);
  const named = new Map(attrs.reverse());
  const there = named.has("href") ? elsewhere(decode(named.get("href"))) : null;
  return there === null ? null : loaded(/xsl|xml/i.test(named.get("type") ?? "") ? "xslt" : "sheet", there);
}

// Every element whose markup the policy breaks in a browser, as a reason and what to change.
// *content* gives the element's text, for the two whose text the policy refuses.
function offense(name, attrs, content) {
  const named = new Map();
  for (const [attribute, written] of attrs) if (!named.has(attribute)) named.set(attribute, written);
  for (const [attribute, written] of attrs) {
    if (attribute === "style" && written.trim()) {
      return "carries a style attribute: move the declaration to a stylesheet the page loads";
    }
    if (/^on[a-z]+$/.test(attribute) && written.trim()) {
      return `carries the event handler ${attribute}: attach the listener from a script file`;
    }
    if (URLS.has(attribute) && scriptsValue(attribute, written)) {
      return `points ${attribute} at a javascript: URL: link to a page, or attach the behaviour from a script file`;
    }
  }
  const animated = bare(named.get("attributename") ?? "").toLowerCase();
  if (URLS.has(animated)) {
    for (const attribute of ["from", "to", "by", "values"]) {
      if ((named.get(attribute) ?? "").split(";").some(scriptsUrl)) {
        return `animates ${animated} to a javascript: URL: remove the animation, or animate it to a page`;
      }
    }
  }
  const refresh = (named.get("http-equiv") ?? "").trim().toLowerCase() === "refresh";
  if (name === "meta" && refresh && scriptsUrl((named.get("content") ?? "").replace(/^[^;,]*[;,]\s*(?:url\s*=\s*)?['"]?/i, ""))) {
    return "refreshes to a javascript: URL: refresh to a page, or remove it";
  }
  if (name === "script") {
    const runs = RUNS.has((named.get("type") ?? "").split(";")[0].trim().toLowerCase());
    const source = named.get("src") ?? named.get("href") ?? named.get("xlink:href");
    const there = source === undefined ? null : elsewhere(source);
    if (runs && there !== null) return loaded("script", there);
    if (runs && source === undefined && content().trim()) {
      return "is an inline script: write it to a file the page loads with src";
    }
  }
  if (name === "style" && content().trim()) {
    return "is a <style> element: write it to a stylesheet the page loads with <link rel=\"stylesheet\">";
  }
  if (name === "link" && named.has("href")) {
    const rel = (named.get("rel") ?? "").toLowerCase().split(/[\t\n\f\r ]+/);
    const kind = rel.includes("stylesheet") ? "style" : rel.includes("modulepreload") ? "script"
      : rel.includes("preload") ? PRELOADS[(named.get("as") ?? "").trim().toLowerCase()] ?? null
        : rel.includes("manifest") ? "manifest" : rel.includes("icon") ? "icon" : null;
    const there = kind === null ? null : elsewhere(named.get("href"), ALLOWED[kind]);
    if (there !== null) return loaded(kind, there);
  }
  const image = name === "input" && (named.get("type") ?? "").trim().toLowerCase() === "image";
  for (const [attribute, kind] of image ? [["src", "image"]] : LOADS[name] ?? []) {
    const written = named.get(attribute);
    for (const url of written === undefined ? [] : attribute === "srcset" ? candidates(written) : [written]) {
      const there = elsewhere(url, ALLOWED[kind]);
      if (there !== null) return loaded(kind, there);
    }
  }
  if (named.has("srcdoc")) {
    const inner = firstOffense(named.get("srcdoc"), false);
    if (inner !== null) return `carries a srcdoc whose page holds ${inner}`;
  }
  if (name === "object" || name === "embed") {
    return `is an <${name}> element, which the policy's object-src 'none' refuses: remove it`;
  }
  if (name === "base" && named.has("href")) {
    return "sets the page's base URL, which the policy's base-uri 'none' refuses: remove it and write each URL whole";
  }
  for (const attribute of ["action", "formaction"]) {
    const there = named.has(attribute) && (name === "form" || attribute === "formaction") ? elsewhere(named.get(attribute)) : null;
    if (there !== null) {
      return `submits a form to ${there}, which the policy's form-action 'self' refuses${unlessOwn(there)}: a site built from the recipe has no form that posts, so remove it or build the site under "build": "own"`;
    }
  }
  return null;
}

// Every document under *dir*, in name order, and every symbolic link there, which the image
// copies as a link and nginx follows wherever it points: the check cannot read what it serves.
function documents(dir) {
  return readdirSync(dir, { withFileTypes: true })
    .sort((a, b) => (a.name < b.name ? -1 : 1))
    .flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isSymbolicLink()) {
        return [[path, "is a symbolic link, which the image copies as a link and nginx follows wherever it points, so the check cannot read what it serves: make the build write the file itself"]];
      }
      if (entry.isDirectory()) return documents(path);
      return entry.isFile() && DOCUMENT.test(entry.name) ? [[path, null]] : [];
    });
}

if (process.argv[2] !== undefined) {
  const root = process.argv[2];
  const made = lstatSync(root, { throwIfNoEntry: false });
  if (made === undefined || !made.isDirectory()) {
    const what = made === undefined ? "does not exist" : made.isSymbolicLink() ? "is a symbolic link" : "is not a directory";
    console.error(
      `site/${root}/ ${what}: the static-site recipe serves the pages \`npm run build\` writes ` +
        `there (terp-framework ADR 0198). Make the site's build write its pages to ${root}/, or ` +
        `build the site under "build": "own".`,
    );
    process.exit(1);
  }
  const refused = documents(root).flatMap(([path, linked]) => {
    const why = linked ?? firstOffense(readFileSync(path, "utf8"), XML.test(path));
    return why === null ? [] : [`site/${relative(".", path)}: ${why}`];
  });
  for (const line of refused) console.error(line);
  if (refused.length) {
    console.error(
      "Each line is markup the site's content security policy breaks in a browser, where a page " +
        "breaks with nothing in any log, a URL that names a host, which the build cannot tell " +
        "from another origin, or a file the check cannot read (terp-framework ADR 0198). The " +
        "policy is the control; the check only finds what it can see before deploy, " +
        "and a page it passes is no promise: change each as its line says, or build the site " +
        "under \"build\": \"own\".",
    );
    process.exit(1);
  }
}
"""

__all__ = ["SITE_CHECK"]
