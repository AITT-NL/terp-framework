"""How the static-site check reads a page (ADR 0198): the first half of its script.

:data:`terp.arch.deployment._site_check.SITE_CHECK` is one Node script that the recipe's
Dockerfile carries as a heredoc. This module holds its first half, the reading of a page; that
module holds the second, what the policy breaks and the run over ``site/dist/``, and joins the
two. They are two modules only so that neither crosses the 500-line cap: the render copies their
text byte for byte, one after the other, and nothing but that module imports this one.
"""

from __future__ import annotations

#: The script's imports, then how it reads a page: a tag's attributes by the HTML tokenizer's
#: states (so ``/ =`` starts an attribute named ``=``, as it does in a browser); a comment ended
#: where a browser ends it, in one search; character references decoded before a value is
#: judged; a raw-text element's content skipped in a page's own HTML; and SVG and MathML content
#: entered and left by the tree builder's rules for it on a start or end tag (breakout tags,
#: integration points, the end-tag steps for foreign content). An XML file is
#: read by namespace: each element and attribute by the URI its prefix is bound to, an XLink
#: attribute as ``xlink:<name>``, anything outside XHTML, SVG and MathML as data, a CDATA
#: section or processing instruction to its end, and an internal DTD subset refused, since a
#: browser expands its entities and the check does not.
#:
#: It models a browser's parser for these decisions and is not one. Where the two could differ,
#: its choices lean toward reading markup: inside SVG or MathML content, inside a ``<select>``
#: and after a ``<frameset>`` it skips no raw text, and an end tag whose effect it does not
#: model closes nothing. That costs a refusal now and then that a browser would not need, and it
#: is still no promise that the check reads all a browser does.
SITE_MARKUP = r"""import { lstatSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

// What an HTML parser reads as text inside these, where they stand in a page's HTML content.
const RAW = new Set([
  "iframe", "noembed", "noframes", "noscript", "plaintext", "script", "style", "textarea",
  "title", "xmp",
]);
// HTML elements a browser never leaves open.
const VOID = new Set([
  "area", "base", "basefont", "bgsound", "br", "col", "embed", "frame", "hr", "image", "img",
  "input", "keygen", "link", "meta", "param", "source", "track", "wbr",
]);
// The start tags that end SVG or MathML content, read as HTML again.
const BREAKOUT = new Set([
  "b", "big", "blockquote", "body", "br", "center", "code", "dd", "div", "dl", "dt", "em",
  "embed", "h1", "h2", "h3", "h4", "h5", "h6", "head", "hr", "i", "img", "li", "listing", "menu",
  "meta", "nobr", "ol", "p", "pre", "ruby", "s", "small", "span", "strong", "strike", "sub", "sup",
  "table", "tt", "u", "ul", "var",
]);
// The namespaces whose markup a browser renders, by URI; anything else in an XML file is data.
const NAMESPACES = {
  "http://www.w3.org/1999/xhtml": "html",
  "http://www.w3.org/2000/svg": "svg",
  "http://www.w3.org/1998/Math/MathML": "math",
};
const XLINK = "http://www.w3.org/1999/xlink";
const SPACE = /[\t\n\f\r ]/;

// The named character references a URL can be spelled with: ASCII punctuation and spaces. A
// letter has no name, only a number, and every number is decoded.
const NAMED = {
  Tab: "\t", NewLine: "\n", excl: "!", quot: '"', QUOT: '"', num: "#", dollar: "$",
  percnt: "%", amp: "&", AMP: "&", apos: "'", lpar: "(", rpar: ")", ast: "*", midast: "*",
  plus: "+", comma: ",", period: ".", sol: "/", colon: ":", semi: ";", lt: "<", LT: "<",
  equals: "=", gt: ">", GT: ">", quest: "?", commat: "@", lsqb: "[", lbrack: "[", bsol: "\\",
  rsqb: "]", rbrack: "]", Hat: "^", lowbar: "_", UnderBar: "_", grave: "`",
  DiacriticalGrave: "`", lcub: "{", lbrace: "{", verbar: "|", vert: "|", VerticalLine: "|",
  rcub: "}", rbrace: "}", nbsp: "\u00a0", NonBreakingSpace: "\u00a0", fjlig: "fj",
};

// A value as the browser reads it: every character reference decoded, a number with or
// without its semicolon, as the HTML tokenizer decodes one in an attribute.
function decode(text) {
  return text.replace(/&(?:#[xX]([0-9a-fA-F]+);?|#([0-9]+);?|([A-Za-z][A-Za-z0-9]*);)/g, (whole, hex, dec, name) => {
    if (name !== undefined) return NAMED[name] ?? whole;
    const point = hex !== undefined ? parseInt(hex, 16) : parseInt(dec, 10);
    const valid = point > 0 && point <= 0x10ffff && !(point >= 0xd800 && point <= 0xdfff);
    return valid ? String.fromCodePoint(point) : "\ufffd";
  });
}

// Where the content of element *name* ends, from *at*: its end tag, or the end of the page.
// *missing* remembers, per name, where a search already found none, so no search repeats.
const closers = new Map();
function closing(html, name, at, missing) {
  if (at >= (missing.get(name) ?? Infinity)) return html.length;
  if (!closers.has(name)) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    closers.set(name, new RegExp(`</${escaped}(?=[\\t\\n\\f\\r />])`, "gi"));
  }
  const close = closers.get(name);
  close.lastIndex = at;
  const found = close.exec(html);
  if (found === null) missing.set(name, at);
  return found === null ? html.length : found.index;
}

// A tag's attributes as the HTML tokenizer reads them, from just after its name: each name
// (in lower case where *fold*) with its value; where the tag ends; and whether it closes itself.
// Each state is the tokenizer's: after a "/" or a quoted value, any other character starts the
// next name, so "/ =" starts one named "=".
function readTag(html, at, fold = true) {
  const attrs = [];
  let name = "";
  let value = "";
  let state = "before";
  const flush = () => {
    if (name) attrs.push([fold ? name.toLowerCase() : name, value]);
    name = "";
    value = "";
  };
  for (let i = at; i < html.length; i += 1) {
    const c = html[i];
    if (state === "before") {
      if (SPACE.test(c)) continue;
      if (c === "/" || c === ">") {
        state = "after";
        i -= 1;
      } else {
        name = c;
        state = "name";
      }
    } else if (state === "name") {
      if (SPACE.test(c) || c === "/" || c === ">") {
        state = "after";
        i -= 1;
      } else if (c === "=") state = "value";
      else name += c;
    } else if (state === "after") {
      if (SPACE.test(c)) continue;
      if (c === "/") {
        flush();
        state = "closing";
      } else if (c === "=") state = "value";
      else if (c === ">") {
        flush();
        return [attrs, i, false];
      } else {
        flush();
        name = c;
        state = "name";
      }
    } else if (state === "value") {
      if (SPACE.test(c)) continue;
      if (c === '"' || c === "'") state = c;
      else if (c === ">") {
        flush();
        return [attrs, i, false];
      } else {
        value = c;
        state = "unquoted";
      }
    } else if (state === '"' || state === "'") {
      if (c === state) {
        flush();
        state = "quoted";
      } else value += c;
    } else if (state === "unquoted") {
      if (SPACE.test(c)) {
        flush();
        state = "before";
      } else if (c === ">") {
        flush();
        return [attrs, i, false];
      } else value += c;
    } else if (state === "quoted" && SPACE.test(c)) state = "before";
    else if (state === "quoted" && c === "/") state = "closing";
    else if (c === ">") return [attrs, i, state === "closing"];
    else {
      state = "before";
      i -= 1;
    }
  }
  flush();
  return [attrs, html.length, false];
}

// SVG's and MathML's HTML integration points, and MathML's text integration points, where a
// browser reads HTML again.
const integration = (node) =>
  (node.ns === "svg" && ["foreignobject", "desc", "title"].includes(node.name)) ||
  (node.ns === "math" && node.name === "annotation-xml" &&
    /^(?:text\/html|application\/xhtml\+xml)$/i.test(node.encoding ?? ""));
const textIntegration = (node) => node.ns === "math" && ["mi", "mo", "mn", "ms", "mtext"].includes(node.name);

// The open elements of an HTML page's SVG and MathML content, from its outermost <svg> or
// <math>, by the tree builder's rules for what this reading needs: the namespace a start tag
// is read in, and whether any such content is still open. Where a browser's rules for an end
// tag would close more than this models (an HTML end tag that closes the elements around its
// own, or one that ends SVG or MathML from the HTML inside it), this closes less, and so reads
// on as markup.
class Foreign {
  constructor() {
    this.stack = [];
    this.html = [];
    this.at = new Map();
  }

  get open() {
    return this.stack.length > 0;
  }

  push(node) {
    if (node.ns === "html") this.html.push(this.stack.length);
    else if (this.at.has(node.name)) this.at.get(node.name).push(this.stack.length);
    else this.at.set(node.name, [this.stack.length]);
    this.stack.push(node);
  }

  cut(length) {
    while (this.stack.length > length) {
      const node = this.stack.pop();
      (node.ns === "html" ? this.html : this.at.get(node.name)).pop();
    }
  }

  // Whether the current node is SVG or MathML content and no integration point.
  inForeign() {
    const node = this.stack[this.stack.length - 1];
    return node !== undefined && node.ns !== "html" && !integration(node) && !textIntegration(node);
  }

  start(name, attrs, selfClosing) {
    const node = this.stack[this.stack.length - 1];
    const asHtml = node === undefined || node.ns === "html" || integration(node) ||
      (textIntegration(node) && name !== "mglyph" && name !== "malignmark") ||
      (node.ns === "math" && node.name === "annotation-xml" && name === "svg");
    if (asHtml && (name === "svg" || name === "math")) {
      if (!selfClosing) this.push({ name, ns: name });
    } else if (asHtml) {
      if (node !== undefined && !VOID.has(name)) this.push({ name, ns: "html" });
    } else if (BREAKOUT.has(name) || (name === "font" && attrs.some(([attribute]) => ["color", "face", "size"].includes(attribute)))) {
      while (this.inForeign()) this.cut(this.stack.length - 1);
      this.start(name, attrs, selfClosing);
    } else if (!selfClosing) {
      const encoding = attrs.find(([attribute]) => attribute === "encoding");
      this.push({ name, ns: node.ns, encoding: encoding === undefined ? undefined : decode(encoding[1]) });
    }
  }

  // An end tag closes the current HTML element of its name; the SVG or MathML element of its
  // name above the topmost HTML element, with all above it, where SVG or MathML is current;
  // and </br> or </p> there closes that content up to the HTML around it.
  end(name) {
    const node = this.stack[this.stack.length - 1];
    if (node === undefined) return;
    if (node.ns === "html") {
      if (node.name === name) this.cut(this.stack.length - 1);
    } else if (name === "br" || name === "p") {
      while (this.inForeign()) this.cut(this.stack.length - 1);
    } else {
      const named = this.at.get(name) ?? [];
      const found = named.length ? named[named.length - 1] : -1;
      if (found > (this.html.length ? this.html[this.html.length - 1] : -1)) this.cut(found);
    }
  }
}

// An XML file's internal DTD subset, whose entities a browser expands into the page and the
// check does not read: refused wherever the prolog declares one, in one pass over the prolog.
function internalSubset(xml) {
  let at = xml.charCodeAt(0) === 0xfeff ? 1 : 0;
  for (;;) {
    while (at < xml.length && SPACE.test(xml[at])) at += 1;
    const [open, close] = xml.startsWith("<?", at) ? ["<?", "?>"] : xml.startsWith("<!--", at) ? ["<!--", "-->"] : [null, null];
    if (open === null) break;
    const end = xml.indexOf(close, at + open.length);
    if (end === -1) return null;
    at = end + close.length;
  }
  if (xml.slice(at, at + 9).toUpperCase() !== "<!DOCTYPE") return null;
  let quote = null;
  for (let i = at + 9; i < xml.length; i += 1) {
    const c = xml[i];
    if (quote !== null) {
      if (c === quote) quote = null;
    } else if (c === '"' || c === "'") quote = c;
    else if (c === "[") {
      return "<!DOCTYPE> declares an internal subset, whose entities a browser expands into the page and the check does not read: write each entity's text where it is used and remove the subset (an SVG or XHTML file needs none)";
    } else if (c === ">") return null;
  }
  return null;
}

// The first element of *source* whose markup the policy breaks in a browser, as the refusal's
// text, or null. *xml* reads it as an XML file: no raw text, CDATA and processing instructions
// to their ends, and each element and attribute by the namespace its prefix is bound to.
export function firstOffense(source, xml) {
  if (xml) {
    const subset = internalSubset(source);
    if (subset !== null) return subset;
  }
  const html = source;
  const foreign = new Foreign();
  // A browser may ignore a raw-text element's start tag inside a <select> or after a
  // <frameset> and read what follows as markup, so there the check skips no raw text.
  let select = 0;
  let frameset = false;
  // In an XML file, each prefix's bindings, innermost last ("" the default namespace), and
  // the prefixes each open element declares.
  const bound = new Map();
  const declared = [];
  const uriOf = (prefix) => bound.get(prefix)?.at(-1) ?? null;
  const missing = new Map();
  const comment = /--!?>/g;
  const tagOpen = xml ? /^<(\/?)([^\t\n\f\r />!?][^\t\n\f\r />]*)/ : /^<(\/?)([A-Za-z][^\t\n\f\r />]*)/;
  let at = 0;
  while ((at = html.indexOf("<", at)) !== -1) {
    if (html.startsWith("<!--", at)) {
      // A comment ends where a browser ends it: "<!-->" and "<!--->" at once, else the first
      // "-->" or "--!>", found in one search from where it starts.
      const body = at + 4;
      if (html[body] === ">" || html.startsWith("->", body)) {
        at = html.indexOf(">", body) + 1;
        continue;
      }
      comment.lastIndex = body;
      const close = comment.exec(html);
      at = close === null ? html.length : close.index + close[0].length;
      continue;
    }
    const head = tagOpen.exec(html.slice(at, at + 256));
    if (head === null) {
      // In an XML file a CDATA section runs to "]]>" and a processing instruction to "?>".
      // Anywhere else a doctype, a CDATA section or a processing instruction runs to its first
      // ">", as an HTML parser reads it. Any other "<" is text.
      const [open, close] = !xml ? [null, null] : html.startsWith("<![CDATA[", at) ? ["<![CDATA[", "]]>"]
        : html.startsWith("<?", at) ? ["<?", "?>"] : [null, null];
      if (open !== null) {
        const end = html.indexOf(close, at + open.length);
        const instruction = html.slice(at, end === -1 ? html.length : end + close.length);
        at += instruction.length;
        const why = open === "<?" ? instructionOffense(instruction) : null;
        if (why !== null) return `${shown(instruction)} ${why}`;
        continue;
      }
      const markup = html[at + 1] === "!" || html[at + 1] === "?";
      const end = markup ? html.indexOf(">", at) : -1;
      at = markup ? (end === -1 ? html.length : end + 1) : at + 1;
      continue;
    }
    const [attrs, end, selfClosing] = readTag(html, at + head[0].length, !xml);
    const tag = html.slice(at, end + 1);
    at = end + 1;
    let name;
    let decoded;
    if (xml) {
      if (head[1]) {
        for (const prefix of declared.pop() ?? []) bound.get(prefix).pop();
        continue;
      }
      const mine = [];
      for (const [attribute, written] of attrs) {
        if (attribute !== "xmlns" && !attribute.startsWith("xmlns:")) continue;
        const prefix = attribute.slice(6);
        if (!bound.has(prefix)) bound.set(prefix, []);
        bound.get(prefix).push(decode(written));
        mine.push(prefix);
      }
      const colon = head[2].indexOf(":");
      const uri = uriOf(colon === -1 ? "" : head[2].slice(0, colon));
      name = head[2].slice(colon + 1).toLowerCase();
      // An unprefixed attribute by its name, an XLink one as xlink:<name>; a declaration or
      // another namespace's attribute does nothing on an element a browser renders.
      decoded = [];
      for (const [attribute, written] of attrs) {
        const split = attribute.indexOf(":");
        if (attribute === "xmlns" || attribute.startsWith("xmlns:")) continue;
        if (split === -1) decoded.push([attribute.toLowerCase(), decode(written)]);
        else if (uriOf(attribute.slice(0, split)) === XLINK) {
          decoded.push([`xlink:${attribute.slice(split + 1).toLowerCase()}`, decode(written)]);
        }
      }
      if (selfClosing) for (const prefix of mine) bound.get(prefix).pop();
      else declared.push(mine);
      if (NAMESPACES[uri] === undefined) continue;
    } else {
      name = head[2].toLowerCase();
      if (head[1]) {
        if (name === "select" && !foreign.open) select = Math.max(0, select - 1);
        foreign.end(name);
        continue;
      }
      if (name === "select" && !foreign.open) select += 1;
      if (name === "frameset" && !foreign.open) frameset = true;
      foreign.start(name, attrs, selfClosing);
      decoded = attrs.map(([attribute, written]) => [attribute, decode(written)]);
    }
    let content = () => "";
    if (!xml && !foreign.open && select === 0 && !frameset && RAW.has(name)) {
      // HTML content outside SVG and MathML: what a browser reads as this element's text.
      const close = closing(html, name, at, missing);
      const text = html.slice(at, close);
      content = () => text;
      at = close;
    } else if ((name === "script" || name === "style") && !selfClosing) {
      // Read on as markup, its text looked at only where the policy asks what it holds.
      const [from, closer] = [at, xml ? head[2] : name];
      content = () => decode(html.slice(from, closing(html, closer, from, missing)).replace(/<!\[CDATA\[|\]\]>/g, ""));
    }
    const why = offense(name, decoded, content);
    if (why !== null) return `${shown(tag)} ${why}`;
  }
  return null;
}
"""

__all__ = ["SITE_MARKUP"]
