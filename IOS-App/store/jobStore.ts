import { create } from 'zustand';
import { JobEntry } from '../api/endpoints';

interface JobState {
  readonly jobs: readonly JobEntry[];
  readonly isProcessing: boolean;
  readonly batchProgress: number;

  setJobs: (jobs: readonly JobEntry[]) => void;
  setProcessing: (processing: boolean) => void;
  setBatchProgress: (progress: number) => void;
  clearJobs: () => void;
}

export const useJobStore = create<JobState>((set) => ({
  jobs: [],
  isProcessing: false,
  batchProgress: 0,

  setJobs: (jobs: readonly JobEntry[]) =>
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
