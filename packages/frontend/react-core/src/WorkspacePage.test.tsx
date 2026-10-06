// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DashboardPage } from "./DashboardPage";
import { Page } from "./Page";
import { CanvasHost, WorkspacePage } from "./WorkspacePage";

afterEach(cleanup);

describe("WorkspacePage (ADR 0179)", () => {
  it("marks its page as the one that fills the shell", () => {
    const { container } = render(
      <WorkspacePage title="Network">
        <CanvasHost label="Network diagram">
          <svg viewBox="0 0 10 10" />
        </CanvasHost>
      </WorkspacePage>,
    );
    const page = container.querySelector('[data-terp="page"]');
    expect(page?.getAttribute("data-fill")).toBe("workspace");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Network");
  });

  it("leaves every other page as it was", () => {
    // Mutation: stamp data-fill on every page, and every main becomes a flex column.
    for (const page of [
      <Page key="page" title="Plain">body</Page>,
      <DashboardPage key="dashboard" title="Overview">body</DashboardPage>,
    ]) {
      const { container, unmount } = render(page);
      expect(container.querySelector('[data-terp="page"]')?.hasAttribute("data-fill")).toBe(false);
      unmount();
    }
  });

  it("takes its parent trail as parents, the alias every nested archetype uses", () => {
    render(
      <WorkspacePage title="Network" parents={[{ label: "Sites", to: "/sites" }]}>
        <CanvasHost label="Network diagram">
          <svg viewBox="0 0 10 10" />
        </CanvasHost>
      </WorkspacePage>,
    );
    expect(screen.getByRole("link", { name: "Sites" }).getAttribute("href")).toBe("/sites");
  });
});

describe("CanvasHost", () => {
  it("is a named region carrying the canvas", () => {
    render(
      <CanvasHost label={{ id: "network.canvas", message: "Network diagram" }}>
        <svg data-testid="drawing" viewBox="0 0 10 10" />
      </CanvasHost>,
    );
    const region = screen.getByRole("region", { name: "Network diagram" });
    expect(region.getAttribute("data-terp")).toBe("canvas-host");
    expect(region.contains(screen.getByTestId("drawing"))).toBe(true);
    // It renders no inline style: its geometry is the stylesheet's.
    expect(region.hasAttribute("style")).toBe(false);
  });
});
