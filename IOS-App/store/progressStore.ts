import { create } from 'zustand';

export interface BatchResult {
  readonly totalJobs: number;
  readonly completed: number;
  readonly failed: number;
  readonly duration: string;
}

interface ProgressState {
  readonly percent: number;
  readonly message: string;
  readonly lastEvent: string | null;
  readonly batchResult: BatchResult | null;

  setPercent: (percent: number) => void;
  setMessage: (message: string) => void;
  setLastEvent: (event: string) => void;
  setBatchResult: (result: BatchResult | null) => void;
  reset: () => void;
}

export const useProgressStore = create<ProgressState>((set) => ({
  percent: 0,
  message: '',
  lastEvent: null,
  batchResult: null,

  setPercent: (percent: number) =>
    set((state) => ({
      ...state,
      percent,
    })),

  setMessage: (message: string) =>
    set((state) => ({
      ...state,
      message,
    })),

  setLastEvent: (event: string) =>
    set((state) => ({
      ...state,
      lastEvent: event,
    })),

  setBatchResult: (result: BatchResult | null) =>
    set((state) => ({
      ...state,
      batchResult: result,
    })),

  reset: () =>
    set((state) => ({
      ...state,
      percent: 0,
      message: '',
      lastEvent: null,
      batchResult: null,
    })),
}));
