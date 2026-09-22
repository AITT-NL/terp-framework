import { useCallback, useEffect, useRef, useState } from "react";

import type { DataViewQuery, DataViewRepository } from "../types";

export interface UseDataViewQueryResult<T> {
  rows: T[];
  /**
   * How many rows match, or `undefined` while that is genuinely not known yet -- before
   * the first query answers, and after one fails.
   *
   * Not `0`, which is a different answer and a wrong one: a footer reading "0-0 of 0
   * results" beside a loading skeleton states a fact the app has not been told. This is
   * the same distinction `Resource.total` draws for `useResource` (0.17.0), one component
   * over, and for the same reason -- unknown is a real answer and must not render as zero.
   */
  totalCount: number | undefined;
  /** True until the first page for this repository has resolved (skeleton state). */
  isLoading: boolean;
  /** True while any query is in flight (subtle refresh indicator; stale data stays). */
  isFetching: boolean;
  error: unknown;
  /** Re-run the current query. */
  refresh: () => void;
}

/**
 * Runs `repository.query` whenever the query changes, with abort-on-supersede:
 * a newer query cancels the in-flight one, and stale results never land. Data from
 * the previous query stays visible while the next one loads (`isFetching`).
 */
export function useDataViewQuery<T>(
  repository: DataViewRepository<T>,
  query: DataViewQuery,
): UseDataViewQueryResult<T> {
  const [rows, setRows] = useState<T[]>([]);
  const [totalCount, setTotalCount] = useState<number | undefined>(undefined);
  const [isLoading, setIsLoading] = useState(true);
  const [isFetching, setIsFetching] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  // Serialize the query so effect deps are value-based (no refetch loop when the
  // caller rebuilds an identical query object each render).
  const queryKey = JSON.stringify(query);
  const queryRef = useRef(query);
  queryRef.current = query;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setIsFetching(true);
    repository
      .query(queryRef.current, controller.signal)
      .then((result) => {
        if (!active) {
          return;
        }
        setRows(result.rows);
        setTotalCount(result.totalCount);
        setError(null);
        setIsLoading(false);
        setIsFetching(false);
      })
      .catch((caught: unknown) => {
        if (!active || controller.signal.aborted) {
          return;
        }
        // The count is not carried over from a previous success: a failed refetch knows
        // nothing about how many rows match now, and saying the old number would be a
        // guess presented as a fact.
        setTotalCount(undefined);
        setError(caught);
        setIsLoading(false);
        setIsFetching(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [repository, queryKey, refreshToken]);

  const refresh = useCallback(() => setRefreshToken((token) => token + 1), []);

  return { rows, totalCount, isLoading, isFetching, error, refresh };
}
