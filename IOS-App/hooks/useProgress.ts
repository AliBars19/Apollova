import { useEffect, useRef, useCallback } from 'react';
import { useConnectionStore } from '../store/connectionStore';
import { useProgressStore } from '../store/progressStore';

const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;
const BACKOFF_MULTIPLIER = 2;

interface ProgressEvent {
  readonly type: string;
  readonly percent?: number;
  readonly message?: string;
  readonly totalJobs?: number;
  readonly completed?: number;
  readonly failed?: number;
  readonly duration?: string;
}

export function useProgress(): void {
  const isPaired = useConnectionStore((s) => s.isPaired);
  const isOnline = useConnectionStore((s) => s.isOnline);
  const tunnelUrl = useConnectionStore((s) => s.tunnelUrl);
  const sessionToken = useConnectionStore((s) => s.sessionToken);

  const setPercent = useProgressStore((s) => s.setPercent);
  const setMessage = useProgressStore((s) => s.setMessage);
  const setLastEvent = useProgressStore((s) => s.setLastEvent);
  const setBatchResult = useProgressStore((s) => s.setBatchResult);
  const resetProgress = useProgressStore((s) => s.reset);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY_MS);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shouldReconnectRef = useRef(true);

  const handleEvent = useCallback(
    (event: ProgressEvent) => {
      setLastEvent(event.type);

      switch (event.type) {
        case 'progress':
          if (event.percent !== undefined) {
            setPercent(event.percent);
          }
          if (event.message !== undefined) {
            setMessage(event.message);
          }
          break;

        case 'batch_complete':
          setPercent(100);
          setMessage('Batch complete');
          if (
            event.totalJobs !== undefined &&
            event.completed !== undefined &&
            event.failed !== undefined &&
            event.duration !== undefined
          ) {
            setBatchResult({
              totalJobs: event.totalJobs,
              completed: event.completed,
              failed: event.failed,
              duration: event.duration,
            });
          }
          break;

        case 'error':
          if (event.message !== undefined) {
            setMessage(event.message);
          }
          break;

        case 'reset':
          resetProgress();
          break;

        default:
          break;
      }
    },
    [setPercent, setMessage, setLastEvent, setBatchResult, resetProgress],
  );

  const connect = useCallback(() => {
    if (!tunnelUrl || !sessionToken) {
      return;
    }

    if (wsRef.current !== null) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const wsScheme = tunnelUrl.startsWith('https') ? 'wss' : 'ws';
    const host = tunnelUrl.replace(/^https?:\/\//, '');
    const wsUrl = `${wsScheme}://${host}/progress?token=${encodeURIComponent(sessionToken)}`;

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      reconnectDelayRef.current = INITIAL_RECONNECT_DELAY_MS;
    };

    ws.onmessage = (messageEvent: WebSocketMessageEvent) => {
      try {
        const parsed: ProgressEvent = JSON.parse(messageEvent.data);
        handleEvent(parsed);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onerror = () => {
      // Error handling is done in onclose
    };

    ws.onclose = () => {
      wsRef.current = null;

      if (!shouldReconnectRef.current) {
        return;
      }

      const delay = reconnectDelayRef.current;
      reconnectDelayRef.current = Math.min(
        delay * BACKOFF_MULTIPLIER,
        MAX_RECONNECT_DELAY_MS,
      );

      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        if (shouldReconnectRef.current) {
          connect();
        }
      }, delay);
    };

    wsRef.current = ws;
  }, [tunnelUrl, sessionToken, handleEvent]);

  useEffect(() => {
    if (!isPaired || !isOnline) {
      shouldReconnectRef.current = false;
      if (wsRef.current !== null) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      return;
    }

    shouldReconnectRef.current = true;
    connect();

    return () => {
      shouldReconnectRef.current = false;
      if (wsRef.current !== null) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
  }, [isPaired, isOnline, connect]);
}
