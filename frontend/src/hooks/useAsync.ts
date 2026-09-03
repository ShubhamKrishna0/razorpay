import { useCallback, useEffect, useRef, useState } from "react";

interface State<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/** Load once, expose a manual refresh, and drop results from stale requests. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []): State<T> & {
  refresh: () => void;
} {
  const [state, setState] = useState<State<T>>({ data: null, loading: true, error: null });
  const generation = useRef(0);

  const run = useCallback(() => {
    const gen = ++generation.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn()
      .then((data) => {
        if (gen === generation.current) setState({ data, loading: false, error: null });
      })
      .catch((err: Error) => {
        if (gen === generation.current) {
          setState({ data: null, loading: false, error: err.message });
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run();
  }, [run]);

  return { ...state, refresh: run };
}

/** Poll while `active` is true. Used to watch a run reach a terminal state. */
export function usePolling(callback: () => void, intervalMs: number, active: boolean): void {
  const saved = useRef(callback);
  saved.current = callback;

  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => saved.current(), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, active]);
}
