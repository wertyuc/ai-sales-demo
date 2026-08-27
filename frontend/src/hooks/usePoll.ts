import { useCallback, useEffect, useRef, useState } from "react";

interface PollState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
  setData: (value: T) => void;
}

/**
 * Fetch on mount, then re-fetch on an interval.
 *
 * The demo has a background scheduler moving state on its own, so screens stay
 * live without a websocket. `loading` is only true for the first load, which
 * keeps skeletons from flashing on every poll.
 */
export function usePoll<T>(
  loader: () => Promise<T>,
  intervalMs = 4000,
  deps: unknown[] = [],
): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const refresh = useCallback(async () => {
    try {
      const result = await loaderRef.current();
      if (!mounted.current) return;
      setData(result);
      setError(null);
    } catch (err) {
      if (!mounted.current) return;
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    setLoading(true);
    void refresh();
    if (intervalMs <= 0) return () => { mounted.current = false; };
    const timer = window.setInterval(() => void refresh(), intervalMs);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps]);

  return { data, error, loading, refresh, setData };
}
