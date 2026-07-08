import type { ReactNode } from "react";

import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

export interface MarkdownProps {
  source: UiText;
}

type Block =
  | { type: "heading"; level: 1 | 2 | 3 | 4 | 5 | 6; text: string }
  | { type: "paragraph"; text: string }
  | { type: "code"; text: string }
  | { type: "list"; ordered: boolean; items: string[] };

const SAFE_SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;

function isSafeLink(href: string): boolean {
  return /^(https?:\/\/|mailto:)/i.test(href) || (!SAFE_SCHEME_RE.test(href) && !href.startsWith("//"));
}

function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index] ?? "";
    if (line.trim() === "") {
      index += 1;
      continue;
    }
    if (line.trimStart().startsWith("```")) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !(lines[index] ?? "").trimStart().startsWith("```")) {
        code.push(lines[index] ?? "");
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push({ type: "code", text: code.join("\n") });
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length as 1 | 2 | 3 | 4 | 5 | 6, text: heading[2] });
      index += 1;
      continue;
    }
    const unordered = /^\s*[-*]\s+(.+)$/.exec(line);
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (unordered || ordered) {
      const listItems: string[] = [];
      const isOrdered = Boolean(ordered);
      while (index < lines.length) {
        const match = isOrdered ? /^\s*\d+[.)]\s+(.+)$/.exec(lines[index] ?? "") : /^\s*[-*]\s+(.+)$/.exec(lines[index] ?? "");
        if (!match) {
          break;
        }
        listItems.push(match[1]);
        index += 1;
      }
      blocks.push({ type: "list", ordered: isOrdered, items: listItems });
      continue;
    }
    const paragraph: string[] = [line.trim()];
    index += 1;
    while (index < lines.length) {
      const next = lines[index] ?? "";
      if (
        next.trim() === "" ||
        next.trimStart().startsWith("```") ||
        /^(#{1,6})\s+/.test(next) ||
        /^\s*[-*]\s+/.test(next) ||
        /^\s*\d+[.)]\s+/.test(next)
      ) {
        break;
      }
      paragraph.push(next.trim());
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join(" ") });
  }

  return blocks;
}

function findNextToken(text: string, start: number) {
  const tokens = ["`", "**", "*", "_", "["];
  let next = -1;
  let token = "";
  for (const candidate of tokens) {
    const found = text.indexOf(candidate, start);
    if (found !== -1 && (next === -1 || found < next)) {
      next = found;
      token = candidate;
    }
  }
  return { next, token };
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let index = 0;
  let key = 0;

  while (index < text.length) {
    const { next, token } = findNextToken(text, index);
    if (next === -1) {
      nodes.push(text.slice(index));
      break;
    }
    if (next > index) {
      nodes.push(text.slice(index, next));
    }
    if (token === "`") {
      const end = text.indexOf("`", next + 1);
      if (end === -1) {
        nodes.push("`");
        index = next + 1;
      } else {
        nodes.push(<code key={key++}>{text.slice(next + 1, end)}</code>);
        index = end + 1;
      }
      continue;
    }
    if (token === "**") {
      const end = text.indexOf("**", next + 2);
      if (end === -1) {
        nodes.push("**");
        index = next + 2;
      } else {
        nodes.push(<strong key={key++}>{renderInline(text.slice(next + 2, end))}</strong>);
        index = end + 2;
      }
      continue;
    }
    if (token === "*" || token === "_") {
      const end = text.indexOf(token, next + 1);
      if (end === -1) {
        nodes.push(token);
        index = next + 1;
      } else {
        nodes.push(<em key={key++}>{renderInline(text.slice(next + 1, end))}</em>);
        index = end + 1;
      }
      continue;
    }
    const closeLabel = text.indexOf("]", next + 1);
    const openHref = closeLabel === -1 ? -1 : text.indexOf("(", closeLabel + 1);
    const closeHref = openHref === -1 ? -1 : text.indexOf(")", openHref + 1);
    if (closeLabel !== -1 && openHref === closeLabel + 1 && closeHref !== -1) {
      const href = text.slice(openHref + 1, closeHref).trim();
      const label = text.slice(next + 1, closeLabel);
      if (isSafeLink(href)) {
        nodes.push(
          <a key={key++} href={href}>
            {renderInline(label)}
          </a>,
        );
      } else {
        nodes.push(`${label} (${href})`);
      }
      index = closeHref + 1;
    } else {
      nodes.push("[");
      index = next + 1;
    }
  }

  return nodes;
}

/** Safe dependency-free markdown renderer; raw HTML is always rendered as text. */
export function Markdown({ source }: MarkdownProps) {
  const resolve = useUiText();
  const blocks = parseBlocks(resolve(source));
  return (
    <>
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          const content = renderInline(block.text);
          if (block.level === 1) return <h1 key={index}>{content}</h1>;
          if (block.level === 2) return <h2 key={index}>{content}</h2>;
          if (block.level === 3) return <h3 key={index}>{content}</h3>;
          if (block.level === 4) return <h4 key={index}>{content}</h4>;
          if (block.level === 5) return <h5 key={index}>{content}</h5>;
          return <h6 key={index}>{content}</h6>;
        }
        if (block.type === "code") {
          return (
            <pre key={index}>
              <code>{block.text}</code>
            </pre>
          );
        }
        if (block.type === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{renderInline(item)}</li>
              ))}
            </List>
          );
        }
        return <p key={index}>{renderInline(block.text)}</p>;
      })}
    </>
  );
}
