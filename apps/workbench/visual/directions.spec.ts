import { expect, test, type Page } from "@playwright/test";

import { directionSheet, REFERENCE_DIRECTIONS } from "./reference-directions";

// The reference directions (ADR 0226), resolved in a browser.
//
// `roles.test.ts` in react-core holds the sheet's READERS to exact lists: which rule reads which
// role. What it cannot see is what a look an app actually ships resolves to, once an unlayered
// `theme.css` has set the roles and the steps behind them, references and all. That is the
// contract an app relies on when it asks for pill-shaped buttons or a serif heading, and it is
// only observable here: a reference that resolves to nothing, a math function an author's value
// makes invalid, or a component reading a step where it should read the role all render a
// perfectly good page, just not the one that was asked for.
//
// Each direction is injected exactly as an app's own sheet arrives: one unlayered `:root` block
// after the framework's layered one. The expected values come from a probe that reads the same
// tokens, so the test states the contract ("a button wears the control corner, whatever it is")
// rather than a number per direction.

interface Resolved {
  control: string;
  container: string;
  face: string;
  weight: string;
}

/** What the roles resolve to on the page as it stands, read off a probe element. */
async function resolvedRoles(page: Page): Promise<Resolved> {
  return page.evaluate(() => {
    const probe = document.createElement("div");
    document.body.append(probe);
    const read = (property: string, value: string) => {
      probe.style.setProperty(property, value);
      const out = getComputedStyle(probe).getPropertyValue(property);
      probe.style.removeProperty(property);
      return out;
    };
    const resolved = {
      control: read("border-top-left-radius", "var(--radius-control)"),
      container: read("border-top-left-radius", "var(--radius-container)"),
      face: read("font-family", "var(--font-family-heading)"),
      weight: read("font-weight", "var(--font-weight-heading)"),
    };
    probe.remove();
    return resolved;
  });
}

/** The computed `property` of every element matching `selector`, with the specimen it is in. */
async function computed(page: Page, selector: string, property: string) {
  return page.evaluate(
    ([css, name]) =>
      [...document.querySelectorAll(css)].map((element) => ({
        specimen: element.closest("[data-specimen]")?.getAttribute("data-specimen") ?? "(page)",
        value: getComputedStyle(element).getPropertyValue(name),
      })),
    [selector, property] as const,
  );
}

const px = (value: string) => Number.parseFloat(value);

for (const direction of REFERENCE_DIRECTIONS) {
  test.describe(`the ${direction.id} direction (${direction.purpose})`, () => {
    test.beforeEach(async ({ page }) => {
      await page.goto("/?theme=midday");
      await page.locator("[data-specimen]").first().waitFor({ state: "visible" });
      await page.addStyleTag({ content: directionSheet(direction) });
    });

    test("every control wears the control corner, and every container the container's", async ({ page }) => {
      const roles = await resolvedRoles(page);
      // Not the defaults: a direction that resolved to the framework's own corners would make
      // every assertion below pass without the roles being read at all.
      expect(roles.control).not.toBe("8px");

      // A one-line select: a list box is a multi-line field, checked below.
      for (const selector of ['[data-terp="button"]', 'input[data-terp="input"]', 'select[data-terp="input"]:not([multiple])']) {
        const found = await computed(page, selector, "border-top-left-radius");
        expect(found.length, selector).toBeGreaterThan(0);
        for (const { specimen, value } of found) expect(value, `${selector} in ${specimen}`).toBe(roles.control);
      }
      // Not a stat: whether it is a container depends on where it sits (a segment of a group's
      // strip, or a figure inside a card, keeps square corners), which roles.test.ts records.
      for (const selector of ['[data-terp="card"]', '[data-terp="empty-state"]', '[data-terp="dataview-card"]']) {
        const found = await computed(page, selector, "border-top-left-radius");
        expect(found.length, selector).toBeGreaterThan(0);
        for (const { specimen, value } of found) expect(value, `${selector} in ${specimen}`).toBe(roles.container);
      }
    });

    test("a multi-line field is never rounder than a container, so its corners never cut into its text", async ({
      page,
    }) => {
      // No specimen renders a list-box Select (a new one would need baselines on both platforms),
      // so this renders the element Select renders with `multiple`, which its own test pins.
      await page.evaluate(() => {
        const list = document.createElement("select");
        list.multiple = true;
        list.setAttribute("data-terp", "input");
        for (const name of ["Alpha option", "Beta option", "Gamma option", "Delta option"]) {
          list.append(new Option(name));
        }
        document.querySelector("[data-specimen]")!.append(list);
      });
      const roles = await resolvedRoles(page);
      const expected = `${Math.min(px(roles.control), px(roles.container))}px`;
      for (const selector of [
        'textarea[data-terp="input"]',
        'select[data-terp="input"][multiple]',
        '[data-terp="combobox-field"][data-multiple="true"]',
      ]) {
        const found = await computed(page, selector, "border-top-left-radius");
        expect(found.length, selector).toBeGreaterThan(0);
        for (const { specimen, value } of found) {
          expect(value, `${selector} in ${specimen}`).toBe(expected);
          expect(px(value), `${selector} in ${specimen}`).toBeLessThanOrEqual(px(roles.container));
        }
      }
      // A list box opens no dropdown, so it draws no chevron and reserves no room for one.
      const listBox = await page.evaluate(() => {
        const style = getComputedStyle(document.querySelector('select[data-terp="input"][multiple]')!);
        return { image: style.backgroundImage, left: style.paddingLeft, right: style.paddingRight };
      });
      expect(listBox.image).toBe("none");
      expect(listBox.right).toBe(listBox.left);
    });

    test("every title takes the heading face, and the titles that follow the role its weight", async ({ page }) => {
      const roles = await resolvedRoles(page);
      for (const selector of ['[data-terp="page-title"]', '[data-terp="card-title"]', '[data-terp="empty-state-title"]']) {
        const faces = await computed(page, selector, "font-family");
        expect(faces.length, selector).toBeGreaterThan(0);
        for (const { specimen, value } of faces) expect(value, `${selector} in ${specimen}`).toBe(roles.face);
        const weights = await computed(page, selector, "font-weight");
        for (const { specimen, value } of weights) expect(value, `${selector} in ${specimen}`).toBe(roles.weight);
      }
    });
  });
}
