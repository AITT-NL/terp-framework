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

  it("takes its parent trail as parents, as DashboardPage does", () => {
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
    // The canvas sits in the host's one layer, which is what gives it a definite box.
    // Mutation: render the children straight into the section, and a canvas root that sizes
    // to its container resolves its percentage height against a flex-grown box.
    const layer = region.firstElementChild;
    expect(region.children).toHaveLength(1);
    expect(layer?.getAttribute("data-terp")).toBe("canvas-host-layer");
    expect(layer?.firstElementChild).toBe(screen.getByTestId("drawing"));
    // It renders no inline style: its geometry is the stylesheet's.
    expect(region.hasAttribute("style")).toBe(false);
    expect(layer?.hasAttribute("style")).toBe(false);
  });
});
