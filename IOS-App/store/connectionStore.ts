import { create } from 'zustand';

interface ConnectionState {
  readonly isOnline: boolean;
  readonly tunnelUrl: string | null;
  readonly sessionToken: string | null;
  readonly isPaired: boolean;
  readonly isRevoked: boolean;

  setOnline: (online: boolean) => void;
  setPaired: (url: string, token: string) => void;
  setRevoked: (revoked: boolean) => void;
  disconnect: () => void;
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  isOnline: false,
  tunnelUrl: null,
  sessionToken: null,
  isPaired: false,
  isRevoked: false,

  setOnline: (online: boolean) =>
    set((state) => ({
      ...state,
      isOnline: online,
    })),

  setPaired: (url: string, token: string) =>
    set((state) => ({
      ...state,
      tunnelUrl: url,
      sessionToken: token,
      isPaired: true,
      isRevoked: false,
      isOnline: true,
    })),

  setRevoked: (revoked: boolean) =>
    set((state) => ({
      ...state,
      isRevoked: revoked,
    })),

  disconnect: () =>
    set((state) => ({
      ...state,
      isOnline: false,
      tunnelUrl: null,
      sessionToken: null,
      isPaired: false,
      isRevoked: false,
    })),
}));
