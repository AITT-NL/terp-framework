import { useCallback, useEffect, useRef, useState } from "react";

import type { DataViewQuery, DataViewRepository } from "../types";

export interface UseDataViewQueryResult<T> {
  rows: T[];
  totalCount: number;
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
  const [totalCount, setTotalCount] = useState(0);
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
