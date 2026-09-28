// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineModuleManifest } from "@terpjs/contract";
import type { FrameworkText, UiText } from "@terpjs/contract";

import { Page } from "./Page";
import { ResourceList } from "./ResourceList";
import { TerpProvider } from "./TerpProvider";
import { resolveUiText, resolveUiTextNode, UiTextProvider, useUiText } from "./uiText";

afterEach(cleanup);

describe("resolveUiText", () => {
  it("passes plain strings through and falls back to a descriptor's message", () => {
    expect(resolveUiText("Tasks")).toBe("Tasks");
    expect(resolveUiText({ id: "tasks.title", message: "Tasks" })).toBe("Tasks");
  });

  it("resolves descriptors in prose slots and preserves rich React nodes", () => {
    const resolve = (text: string | { readonly id: string; readonly message: string }) =>
      typeof text === "string" ? text : `translated:${text.id}`;
    expect(
      resolveUiTextNode(
        { id: "tasks.empty.description", message: "Create your first task." },
        resolve,
      ),
    ).toBe("translated:tasks.empty.description");

    const rich = <strong>Already rendered</strong>;
    expect(resolveUiTextNode(rich, resolve)).toBe(rich);
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

describe("FrameworkText", () => {
  function Label({ text }: { text: UiText | FrameworkText }) {
    const resolve = useUiText();
    return <span>{resolve(text)}</span>;
  }

  it("reads the active framework strings and never reaches the app's resolver", () => {
    // The app's resolver is the one that treats a descriptor's `message` as source-locale text,
    // which is exactly what framework copy is not. Handed a FrameworkText, this one would say so.
    const appResolver = vi.fn((text: UiText) =>
      typeof text === "string" ? text : `app:${text.id}`,
    );
    render(
      <UiTextProvider strings={{ admin: "Beheer" }} resolveText={appResolver}>
        <Label text={{ framework: "admin" }} />
      </UiTextProvider>,
    );
    expect(screen.getByText("Beheer")).toBeInTheDocument();
    expect(appResolver).not.toHaveBeenCalled();
  });

  it("refuses a key the table does not have, including one it only inherits", () => {
    // Cast past the type on purpose: this is the manifest a typecheck never saw.
    const misspelt = { framework: "admn" } as unknown as FrameworkText;
    expect(() => render(<Label text={misspelt} />)).toThrow(
      /FrameworkText names "admn", which is not a framework string/,
    );
    const inherited = { framework: "toString" } as unknown as FrameworkText;
    expect(() => render(<Label text={inherited} />)).toThrow(/names "toString"/);
  });

  it("is a typecheck error for a key the table does not have", () => {
    // The directive is the test, and `tsc --noEmit` is what runs it: it fails as unused the
    // moment a misspelt key compiles, as one would if the key were widened to `string`. The
    // assertion below only proves the literal is still an ordinary manifest at runtime.
    const manifest = defineModuleManifest({
      name: "typo",
      routes: [],
      nav: [
        {
          // @ts-expect-error "admn" is not a TerpStrings key.
          label: { framework: "admn" },
          to: "/",
        },
      ],
    });
    expect(manifest.nav).toHaveLength(1);
  });
});
