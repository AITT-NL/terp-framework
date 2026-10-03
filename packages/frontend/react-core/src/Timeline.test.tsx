// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { LOCALE_EN, LOCALE_NL, LocaleProvider } from "./locale";
import { Timeline } from "./Timeline";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function renderIn(locale: "nl" | "en", node: ReactNode) {
  return render(
    <LocaleProvider locales={{ nl: LOCALE_NL, en: LOCALE_EN }} defaultLocale={locale}>
      {node}
    </LocaleProvider>,
  );
}

const EVENTS = [
  { label: "Changed", when: "2026-08-21T09:30:00Z", detail: "Actor: 9f2c1b7e" },
  { label: "Created", when: "2026-08-20T08:00:00Z", tone: "success" as const },
];

describe("Timeline", () => {
  it("is an ordered list named for what its events are of, one item per event", () => {
    // An ordered list, so a screen reader says how many events there are and where it is.
    renderIn("en", <Timeline label="History" events={EVENTS} />);
    const list = screen.getByRole("list", { name: "History" });
    expect(list.tagName).toBe("OL");
    // Mutation: drop the stated role, and VoiceOver reads a list without markers as no list.
    expect(list).toHaveAttribute("role", "list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
  });

  it("prints each event's words and its moment in the app's locale, with the instant in a time element", () => {
    // Mutation: drop the dateTime, and the machine-readable instant is gone.
    renderIn("nl", <Timeline label="Geschiedenis" events={EVENTS} />);
    const times = [...document.querySelectorAll('[data-terp="timeline-when"]')];
    expect(times[0]!.tagName).toBe("TIME");
    expect(times[0]).toHaveAttribute("dateTime", "2026-08-21T09:30:00.000Z");
    expect(times[0]!.textContent).toMatch(/21 aug\.? 2026/);
    expect(document.querySelector('[data-terp="timeline-label"]')!.textContent).toBe("Changed");
    expect(document.querySelector('[data-terp="timeline-detail"]')!.textContent).toBe("Actor: 9f2c1b7e");
  });

  it("marks an event's tone on the event and hides the marker, whose word is the label", () => {
    renderIn("en", <Timeline label="History" events={EVENTS} />);
    const events = [...document.querySelectorAll('[data-terp="timeline-event"]')];
    expect(events[0]).not.toHaveAttribute("data-tone");
    expect(events[1]).toHaveAttribute("data-tone", "success");
    expect(events[1]!.querySelector('[data-terp="timeline-marker"]')).toHaveAttribute("aria-hidden", "true");
  });

  it("renders no detail line for a detail that renders nothing, and no instant for a value that is not a date", () => {
    // Mutation: test `detail !== undefined` alone, and an empty line is added.
    renderIn("en", (
      <Timeline
        label="History"
        events={[
          { label: "A", when: "not a date", detail: "" },
          { label: "B", when: null, detail: false },
        ]}
      />
    ));
    expect(document.querySelector('[data-terp="timeline-detail"]')).toBeNull();
    for (const time of document.querySelectorAll('[data-terp="timeline-when"]')) {
      expect(time).not.toHaveAttribute("dateTime");
      expect(time.textContent).toBe("—");
    }
  });
});
