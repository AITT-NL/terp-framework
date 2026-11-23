import { expect, test } from "@playwright/test";
import { expectControlFitsHorizontally } from "../src/index";

test("detects a clipped button even when the document fits the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.setContent('<div style="width:64px;overflow:hidden"><button style="width:96px">Save</button></div>');
  // The fixture holds one button. A base-profile flow never finds an element by its wording.
  const save = page.locator("button");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320);
  await expect(expectControlFitsHorizontally(save)).rejects.toThrow(/Horizontal clipping/);
  await save.evaluate(button => { button.style.width = "60px"; });
  await expectControlFitsHorizontally(save);
});
