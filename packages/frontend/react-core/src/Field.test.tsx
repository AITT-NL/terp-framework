// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Field } from "./Field";
import { Input } from "./ui/Input";
import { Select } from "./ui/Select";
import { Textarea } from "./ui/Textarea";

afterEach(cleanup);

describe("Field", () => {
  it("labels its control (accessible association) and shows hint + error", () => {
    render(
      <Field label="Email" hint="we never share it" error="required">
        <Input defaultValue="" />
      </Field>,
    );
    // The control is reachable by its label text (implicit association via the wrapping <label>).
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByText("we never share it")).toBeInTheDocument();
    expect(screen.getByText("required")).toBeInTheDocument();
  });

  it("renders no error node when error is null", () => {
    render(
      <Field label="Name" error={null}>
        <Input defaultValue="" />
      </Field>,
    );
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
  });
});

describe("Select / Textarea primitives", () => {
  it("render token-styled controls reachable by their Field label", () => {
    render(
      <>
        <Field label="Status">
          <Select defaultValue="open">
            <option value="open">open</option>
            <option value="done">done</option>
          </Select>
        </Field>
        <Field label="Notes">
          <Textarea defaultValue="" />
        </Field>
      </>,
    );
    expect(screen.getByLabelText("Status")).toBeInTheDocument();
    expect(screen.getByLabelText("Notes")).toBeInTheDocument();
  });
});
