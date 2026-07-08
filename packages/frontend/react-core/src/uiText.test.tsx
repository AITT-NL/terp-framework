// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Page } from "./Page";
import { ResourceList } from "./ResourceList";
import { TerpProvider } from "./TerpProvider";
import { resolveUiText, UiTextProvider } from "./uiText";

afterEach(cleanup);

describe("resolveUiText", () => {
  it("passes plain strings through and falls back to a descriptor's message", () => {
    expect(resolveUiText("Tasks")).toBe("Tasks");
    expect(resolveUiText({ id: "tasks.title", message: "Tasks" })).toBe("Tasks");
  });
});

describe("UiTextProvider", () => {
  it("components use the bundled defaults without a provider", () => {
    render(
      <Page title="Tasks" isLoading>
        x
      </Page>,
    );
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("overrides framework strings per key", () => {
    render(
      <UiTextProvider strings={{ loading: "Laden..." }}>
        <Page title="Taken" isLoading>
          x
        </Page>
      </UiTextProvider>,
    );
    expect(screen.getByText("Laden...")).toBeInTheDocument();
    expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
  });

  it("routes UiText props through a custom resolver (the i18n runtime hook)", () => {
    render(
      <UiTextProvider
        resolveText={(text) =>
          typeof text === "string" ? text : `[${text.id}] ${text.message}`
        }
      >
        <Page title={{ id: "tasks.title", message: "Tasks" }}>x</Page>
      </UiTextProvider>,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "[tasks.title] Tasks" }),
    ).toBeInTheDocument();
  });

  it("nested providers merge string overrides", () => {
    render(
      <UiTextProvider strings={{ loading: "Laden..." }}>
        <UiTextProvider strings={{ emptyList: "Nog niets." }}>
          <Page title="Taken" isLoading>
            x
          </Page>
        </UiTextProvider>
      </UiTextProvider>,
    );
    expect(screen.getByText("Laden...")).toBeInTheDocument();
  });

  it("localises ResourceList's empty message and create button", () => {
    render(
      <TerpProvider baseUrl="http://api.test">
        <UiTextProvider strings={{ emptyList: "Nog niets.", add: "Toevoegen" }}>
          <ResourceList
            resource={{
              items: [],
              loading: false,
              error: null,
              cause: null,
              create: async () => {},
              reload: async () => {},
              mutate: async (run: () => Promise<unknown>) => {
                await run();
              },
            }}
            renderItem={() => null}
            createPlaceholder="Titel"
          />
        </UiTextProvider>
      </TerpProvider>,
    );
    expect(screen.getByText("Nog niets.")).toBeInTheDocument();
  });
});
