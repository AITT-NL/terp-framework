// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useRecord } from "./useRecord";

afterEach(cleanup);

describe("useRecord", () => {
  it("loads on mount and exposes the record", async () => {
    const { result } = renderHook(() =>
      useRecord<{ id: string }>({ get: async () => ({ id: "r1" }) }),
    );
    expect(result.current.loading).toBe(true);
    expect(result.current.item).toBeNull();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.item).toEqual({ id: "r1" });
    expect(result.current.error).toBeNull();
  });

  it("treats a null get as a normal absent state, not an error (unwrapOptional composes)", async () => {
    const { result } = renderHook(() => useRecord<{ id: string }>({ get: async () => null }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.item).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("reloads when a declared dependency changes (in-place route-param navigation)", async () => {
    const get = vi.fn(async (id: string) => ({ id }));
    const { result, rerender } = renderHook(
      ({ id }: { id: string }) => useRecord({ get: () => get(id) }, [id]),
      { initialProps: { id: "r1" } },
    );
    await waitFor(() => expect(result.current.item).toEqual({ id: "r1" }));

    rerender({ id: "r2" });
    await waitFor(() => expect(result.current.item).toEqual({ id: "r2" }));
    expect(get).toHaveBeenCalledTimes(2);

    // A rerender with the same dependency does not refetch.
    rerender({ id: "r2" });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("captures a get error as a message and its cause", async () => {
    const { result } = renderHook(() =>
      useRecord<string>({
        get: async () => {
          throw new Error("boom");
        },
      }),
    );
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.cause).toBeInstanceOf(Error);
    expect(result.current.item).toBeNull();
  });

  it("mutate surfaces write failures, rejects, and reloads on success", async () => {
    let label = "before";
    const { result } = renderHook(() => useRecord({ get: async () => ({ label }) }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await expect(
        result.current.mutate(async () => {
          throw new Error("Save failed.");
        }),
      ).rejects.toThrow("Save failed.");
    });
    expect(result.current.error).toBe("Save failed.");

    await act(async () => {
      await result.current.mutate(async () => {
        label = "after";
      });
    });
    expect(result.current.item).toEqual({ label: "after" });
    expect(result.current.error).toBeNull();
  });
});
