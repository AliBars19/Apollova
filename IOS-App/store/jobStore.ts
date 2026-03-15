import { create } from 'zustand';

export interface Job {
  readonly id: number;
  readonly songTitle: string;
  readonly template: string;
  readonly status: 'pending' | 'running' | 'complete' | 'failed';
  readonly createdAt: string;
}

interface JobState {
  readonly jobs: readonly Job[];
  readonly isProcessing: boolean;
  readonly batchProgress: number;

  setJobs: (jobs: readonly Job[]) => void;
  setProcessing: (processing: boolean) => void;
  setBatchProgress: (progress: number) => void;
  clearJobs: () => void;
}

export const useJobStore = create<JobState>((set) => ({
  jobs: [],
  isProcessing: false,
  batchProgress: 0,

  setJobs: (jobs: readonly Job[]) =>
    set((state) => ({
      ...state,
      jobs,
    })),

  setProcessing: (processing: boolean) =>
    set((state) => ({
      ...state,
      isProcessing: processing,
    })),

  setBatchProgress: (progress: number) =>
    set((state) => ({
      ...state,
      batchProgress: progress,
    })),

  clearJobs: () =>
    set((state) => ({
      ...state,
      jobs: [],
      isProcessing: false,
      batchProgress: 0,
    })),
}));
