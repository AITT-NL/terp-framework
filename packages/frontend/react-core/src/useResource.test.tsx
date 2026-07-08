// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useResource } from "./useResource";

afterEach(cleanup);

describe("useResource", () => {
  it("loads on mount and exposes the rows", async () => {
    const { result } = renderHook(() =>
      useResource<string, string>({ list: async () => ["a", "b"] }),
    );
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toEqual(["a", "b"]);
    expect(result.current.error).toBeNull();
  });

  it("reloads when a declared dependency changes (in-place route-param navigation)", async () => {
    // A detail view keyed by a route param must refetch when the param changes
    // without a remount — otherwise the previous record's data lingers.
    const list = vi.fn(async () => ["row"]);
    const { result, rerender } = renderHook(
      ({ id }: { id: string }) =>
        useResource<string>(
          {
            list: async () => {
              await list();
              return [id];
            },
          },
          [id],
        ),
      { initialProps: { id: "g1" } },
    );
    await waitFor(() => expect(result.current.items).toEqual(["g1"]));

    rerender({ id: "g2" });
    await waitFor(() => expect(result.current.items).toEqual(["g2"]));
    expect(list).toHaveBeenCalledTimes(2);

    // A rerender with the same dependency does not refetch.
    rerender({ id: "g2" });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("create runs the source create then reloads", async () => {
    let rows = ["a"];
    const create = vi.fn(async (value: string) => {
      rows = [...rows, value];
    });
    const { result } = renderHook(() =>
      useResource<string, string>({ list: async () => rows, create }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.create("b");
    });

    expect(create).toHaveBeenCalledWith("b");
    expect(result.current.items).toEqual(["a", "b"]);
  });

  it("captures a list error as a message", async () => {
    const { result } = renderHook(() =>
      useResource<string>({
        list: async () => {
          throw new Error("boom");
        },
      }),
    );
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.cause).toBeInstanceOf(Error);
    expect(result.current.items).toEqual([]);
  });

  it("rejects create on a read-only resource", async () => {
    const { result } = renderHook(() => useResource<string, string>({ list: async () => [] }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(result.current.create("x")).rejects.toThrow(/read-only/);
  });

  it("surfaces a failed create as an error and rejects (not a silent no-op)", async () => {
    const create = vi.fn(async () => {
      throw new Error("You do not have permission.");
    });
    const { result } = renderHook(() =>
      useResource<string, string>({ list: async () => ["a"], create }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await expect(result.current.create("b")).rejects.toThrow("You do not have permission.");
    });
    expect(result.current.error).toBe("You do not have permission.");
    expect(result.current.cause).toBeInstanceOf(Error);
  });

  it("mutate surfaces module-specific write failures and rejects", async () => {
    const { result } = renderHook(() =>
      useResource<string, string>({ list: async () => ["a"] }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await expect(
        result.current.mutate(async () => {
          throw new Error("Delete failed.");
        }),
      ).rejects.toThrow("Delete failed.");
    });
    expect(result.current.error).toBe("Delete failed.");
    expect(result.current.items).toEqual(["a"]);
  });
});
