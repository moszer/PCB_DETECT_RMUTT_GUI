"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getOperatorToken, setOperatorToken } from "@/lib/api";
import type { ControlLease } from "@/types";

/** Tracks whether this browser holds the station's operator lease and keeps it renewed. */
export function useOperatorLease(lease: ControlLease | undefined, onChange: () => void) {
  const [holdsToken, setIsMine] = useState(false);
  const controlled = Boolean(lease?.is_controlled);
  const isMine = controlled && holdsToken;

  // Re-validate a stored token whenever the station becomes controlled.
  useEffect(() => {
    if (!controlled || !getOperatorToken()) return;
    api
      .renewLease()
      .then(() => setIsMine(true))
      .catch(() => {
        setIsMine(false);
        setOperatorToken(null);
      });
  }, [controlled]);

  // Heartbeat: the backend lease TTL is 20 s.
  useEffect(() => {
    if (!isMine) return;
    const timer = setInterval(() => {
      api.renewLease().catch(() => {
        setIsMine(false);
        setOperatorToken(null);
        onChange();
      });
    }, 5000);
    return () => clearInterval(timer);
  }, [isMine, onChange]);

  const acquire = useCallback(
    async (name: string, passcode: string, force: boolean) => {
      const res = await api.acquireLease(name, passcode || undefined, force);
      if (!res.success || !res.operator_token) throw new Error(res.message);
      setOperatorToken(res.operator_token);
      setIsMine(true);
      onChange();
    },
    [onChange]
  );

  const release = useCallback(async () => {
    await api.releaseLease();
    setOperatorToken(null);
    setIsMine(false);
    onChange();
  }, [onChange]);

  return { isMine, controlled, acquire, release };
}

export type OperatorLease = ReturnType<typeof useOperatorLease>;
