import apiClient from './client';

// ── Response types ──────────────────────────────────────────────

export interface HealthResponse {
  readonly status: string;
  readonly version: string;
}

export interface StatusResponse {
  readonly is_processing: boolean;
  readonly cancel_requested: boolean;
  readonly batch_render_active: boolean;
  readonly tunnel_url: string | null;
  readonly template: string;
  readonly mobile_enabled: boolean;
}

export interface Song {
  readonly id: number;
  readonly song_title: string;
  readonly youtube_url: string;
  readonly start_time: string;
  readonly end_time: string;
  readonly use_count: number;
  readonly last_used: string | null;
}

export interface DatabaseResponse {
  readonly songs: readonly Song[];
  readonly total: number;
}

export interface AddSongRequest {
  readonly title: string;
  readonly url: string;
  readonly start: string;
  readonly end: string;
}

export interface JobEntry {
  readonly folder: string;
  readonly template: string;
  readonly status: 'complete' | 'incomplete';
  readonly song_title?: string;
}

export interface JobsResponse {
  readonly jobs: readonly JobEntry[];
  readonly total: number;
}

export interface GenerateRequest {
  readonly template: string;
  readonly mode: 'smart_picker' | 'manual';
  readonly count: number;
  readonly songs?: readonly Record<string, string>[];
}

export interface SmartPickerResponse {
  readonly songs: readonly Song[];
}

export interface RenderStatusResponse {
  readonly status: string;
  readonly queue: readonly unknown[];
}

export interface MessageResponse {
  readonly status: string;
  readonly detail?: string;
}

// ── API functions ───────────────────────────────────────────────

export async function getHealth(): Promise<HealthResponse> {
  const response = await apiClient.get<HealthResponse>('/health');
  return response.data;
}

export async function getStatus(): Promise<StatusResponse> {
  const response = await apiClient.get<StatusResponse>('/status');
  return response.data;
}

export async function getDatabase(): Promise<DatabaseResponse> {
  const response = await apiClient.get<DatabaseResponse>('/database');
  return response.data;
}

export async function addSong(data: AddSongRequest): Promise<MessageResponse> {
  const response = await apiClient.post<MessageResponse>('/database/add', data);
  return response.data;
}

export async function deleteSong(songId: number): Promise<MessageResponse> {
  const response = await apiClient.delete<MessageResponse>(`/database/${songId}`);
  return response.data;
}

export async function getJobs(): Promise<JobsResponse> {
  const response = await apiClient.get<JobsResponse>('/jobs');
  return response.data;
}

export async function generateJobs(request: GenerateRequest): Promise<MessageResponse> {
  const response = await apiClient.post<MessageResponse>('/jobs/generate', request);
  return response.data;
}

export async function cancelJobs(): Promise<MessageResponse> {
  const response = await apiClient.post<MessageResponse>('/jobs/cancel');
  return response.data;
}

export async function resumeJobs(): Promise<MessageResponse> {
  const response = await apiClient.post<MessageResponse>('/jobs/resume');
  return response.data;
}

export async function getSmartPickerPreview(shuffle: boolean = false): Promise<SmartPickerResponse> {
  const response = await apiClient.get<SmartPickerResponse>('/smart-picker/preview', {
    params: { shuffle },
  });
  return response.data;
}

export async function reshuffleSmartPicker(): Promise<SmartPickerResponse> {
  const response = await apiClient.post<SmartPickerResponse>('/smart-picker/reshuffle');
  return response.data;
}

export async function triggerRender(template: string): Promise<MessageResponse> {
  const response = await apiClient.post<MessageResponse>('/render/trigger', { template });
  return response.data;
}

export async function tripleRender(): Promise<MessageResponse> {
  const response = await apiClient.post<MessageResponse>('/render/triple');
  return response.data;
}

export async function getRenderStatus(): Promise<RenderStatusResponse> {
  const response = await apiClient.get<RenderStatusResponse>('/render/status');
  return response.data;
}

export async function getQrCode(regenerate: boolean = false): Promise<Blob> {
  const response = await apiClient.get('/qr', {
    params: regenerate ? { new: true } : undefined,
    responseType: 'blob',
  });
  return response.data;
}
