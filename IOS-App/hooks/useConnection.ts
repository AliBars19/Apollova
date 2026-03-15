import { useEffect, useRef, useCallback } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { useConnectionStore } from '../store/connectionStore';
import { getHealth } from '../api/endpoints';

const FOREGROUND_INTERVAL_MS = 5000;
const BACKGROUND_INTERVAL_MS = 30000;
const MAX_CONSECUTIVE_FAILURES = 3;

export function useConnection(): void {
  const isPaired = useConnectionStore((s) => s.isPaired);
  const setOnline = useConnectionStore((s) => s.setOnline);
  const failureCountRef = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const appStateRef = useRef<AppStateStatus>(AppState.currentState);

  const poll = useCallback(async () => {
    if (!useConnectionStore.getState().isPaired) {
      return;
    }

    try {
      await getHealth();
      failureCountRef.current = 0;
      setOnline(true);
    } catch {
      failureCountRef.current += 1;
      if (failureCountRef.current >= MAX_CONSECUTIVE_FAILURES) {
        setOnline(false);
      }
    }
  }, [setOnline]);

  const startPolling = useCallback(
    (intervalMs: number) => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
      }
      intervalRef.current = setInterval(poll, intervalMs);
    },
    [poll],
  );

  useEffect(() => {
    if (!isPaired) {
      return;
    }

    poll();
    startPolling(FOREGROUND_INTERVAL_MS);

    const subscription = AppState.addEventListener('change', (nextState: AppStateStatus) => {
      const wasForeground =
        appStateRef.current === 'active';
      const isNowForeground = nextState === 'active';

      appStateRef.current = nextState;

      if (!wasForeground && isNowForeground) {
        failureCountRef.current = 0;
        poll();
        startPolling(FOREGROUND_INTERVAL_MS);
      } else if (wasForeground && !isNowForeground) {
        startPolling(BACKGROUND_INTERVAL_MS);
      }
    });

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      subscription.remove();
    };
  }, [isPaired, poll, startPolling]);
}
