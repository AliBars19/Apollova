import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { useConnectionStore } from '../store/connectionStore';

const apiClient = axios.create({
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const { tunnelUrl, sessionToken } = useConnectionStore.getState();

    if (tunnelUrl) {
      config.baseURL = tunnelUrl;
    }

    if (sessionToken && config.headers) {
      config.headers.Authorization = `Bearer ${sessionToken}`;
    }

    return config;
  },
  (error: AxiosError) => Promise.reject(error),
);

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      useConnectionStore.getState().setRevoked(true);
    }
    return Promise.reject(error);
  },
);

export default apiClient;
