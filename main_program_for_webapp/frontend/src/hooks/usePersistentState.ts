"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

function read<T>(key: string, initial: T, merge: boolean): T {
  if (typeof window === "undefined") return initial;
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return initial;
    const parsed = JSON.parse(raw) as T;
    const isObject = (v: unknown) => typeof v === "object" && v !== null && !Array.isArray(v);
    return merge && isObject(initial) && isObject(parsed) ? { ...initial, ...parsed } : parsed;
  } catch {
    return initial; // Corrupt or inaccessible storage.
  }
}

/**
 * useState mirrored to localStorage. Only use under <ClientOnly> (the stored value is
 * read in the initializer, which would otherwise mismatch the server render).
 * Writes that fail (quota, private mode) go to `onWriteError` instead of throwing.
 */
export function usePersistentState<T>(
  key: string,
  initial: T,
  options: { onWriteError?: (value: T) => void; merge?: boolean } = {}
) {
  const [value, setValue] = useState<T>(() => read(key, initial, Boolean(options.merge)));
  const onWriteError = useRef(options.onWriteError);
  useEffect(() => {
    onWriteError.current = options.onWriteError;
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      onWriteError.current?.(value);
    }
  }, [key, value]);

  return [value, setValue] as const;
}

const noopSubscribe = () => () => {};

/** True only after hydration; lets client-only state initialize from browser storage. */
export function useIsClient() {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  );
}
