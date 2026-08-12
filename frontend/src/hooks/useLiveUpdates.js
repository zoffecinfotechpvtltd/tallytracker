import { useEffect, useRef, useState } from "react";

// Subscribes to GET /api/stream (SSE). Returns { tick, connected } - tick
// increments every time the backend reports a new sync snapshot, so any
// component can do `useEffect(() => { load() }, [tick])` to refetch within
// ~2s of real data changing instead of waiting on a poll interval.
// Falls back to a plain 30s poll tick if the EventSource connection itself
// fails (e.g. proxy/browser doesn't support SSE) - never leaves the UI stuck.
export function useLiveUpdates() {
  const [tick, setTick] = useState(0);
  const [connected, setConnected] = useState(false);
  const fallbackRef = useRef(null);

  useEffect(() => {
    let closed = false;
    const source = new EventSource("/api/stream");

    source.addEventListener("sync", () => {
      if (!closed) setTick((t) => t + 1);
    });
    source.onopen = () => {
      if (!closed) {
        setConnected(true);
        if (fallbackRef.current) {
          clearInterval(fallbackRef.current);
          fallbackRef.current = null;
        }
      }
    };
    source.onerror = () => {
      if (closed) return;
      setConnected(false);
      if (!fallbackRef.current) {
        fallbackRef.current = setInterval(() => setTick((t) => t + 1), 30000);
      }
    };

    return () => {
      closed = true;
      source.close();
      if (fallbackRef.current) clearInterval(fallbackRef.current);
    };
  }, []);

  return { tick, connected };
}
