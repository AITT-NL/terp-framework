import { expect, test } from "@playwright/test";
import { expectControlFitsHorizontally } from "../src/index";

test("detects a clipped button even when the document fits the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.setContent('<div style="width:64px;overflow:hidden"><button style="width:96px">Save</button></div>');
  const save = page.getByRole("button", { name: "Save" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320);
  await expect(expectControlFitsHorizontally(save)).rejects.toThrow(/Horizontal clipping/);
  await save.evaluate(button => { button.style.width = "60px"; });
  await expectControlFitsHorizontally(save);
});
