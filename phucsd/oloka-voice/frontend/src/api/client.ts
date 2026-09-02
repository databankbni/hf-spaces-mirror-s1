export function getApiBaseUrl(): string {
  // Resolve API Base URL dynamically based on running environment
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    if (hostname === "localhost" || hostname === "127.0.0.1") {
      const envUrl = import.meta.env.VITE_API_BASE_URL;
      if (envUrl && envUrl.startsWith("http")) {
        return envUrl.replace(/\/$/, "");
      }
      return "http://localhost:7860";
    }
    
    // For Cloudflare Pages, custom domain (voice.oloka.net), etc., always route API requests through same-origin proxy
    return window.location.origin;
  }
  
  return "https://voice.oloka.net";
}

export function setApiBaseUrl(url: string) {
  // Disabled as requested: URL is fixed for all users
  void url;
}

export interface HealthResponse {
  status: string;
  app: string;
}

export interface VoiceSampleUploadResponse {
  voice_sample_id: string;
  status: string;
  message: string;
}

export interface VoiceSampleResponse {
  id: string;
  source_type: string;
  ref_text: string | null;
  duration: number | null;
  sample_rate: number | null;
  status: string;
  created_at: string;
  name: string | null;
  is_public: boolean;
  source_job_id: string | null;
  tags?: string[] | null;
  source_job_data?: Record<string, any> | null;
}

export interface VoiceSampleUpdateRequest {
  name?: string;
  tags?: string[];
  ref_text?: string;
  is_public?: boolean;
}

export interface VoiceDesignPreviewResponse {
  preview_id: string;
  job_id: string;
  status: string;
  message: string;
}

export interface VoiceDesignPreviewDetail {
  id: string;
  voice_request: string;
  instruct: string;
  preview_text: string;
  preview_audio_path: string | null;
  accepted_sample_id: string | null;
  status: string;
  created_at: string;
}

export interface AcceptPreviewResponse {
  voice_sample_id: string;
  status: string;
  message: string;
}

export interface TTSJobResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: string;
  message: string | null;
  progress: number;
  audio_url: string | null;
  cdn_audio_url?: string | null;
  error_message: string | null;
  job_type?: string;
  text?: string;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  processing_time?: number;
  queue_time?: number;
  total_time?: number;
  params?: Record<string, any>;
  alignment?: any;
}

export interface ApiKeyResponse {
  id: string;
  name: string;
  key: string;
  created_at: string;
  last_used_at: string | null;
}

export interface AdminApiKeyResponse extends ApiKeyResponse {
  user_id: string;
}

export interface UserCreateRequest {
  username: string;
  email: string;
  password: string;
  is_verified?: boolean;
  is_approved?: boolean;
  is_admin?: boolean;
}

export interface UserUpdateRequest {
  username?: string;
  email?: string;
  password?: string;
  is_verified?: boolean;
  is_approved?: boolean;
  is_admin?: boolean;
}

export interface SystemSettingsResponse {
  worker_mode: string;
  allow_registration: boolean;
  require_admin_approval: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string;
  smtp_from: string;
  kaggle_username: string;
  kaggle_key: string;
  kaggle_kernel_ref: string;
  kaggle_kernel_slug: string;
  kaggle_kernel_title: string;
  kaggle_accelerator: string;
  kaggle_timeout_seconds: number;
  kaggle_idle_timeout_seconds: number;
  kaggle_worker_dir: string;
  ui_layout: string;
  hf_token: string;
  llm_provider?: string;
  llm_api_key?: string;
  llm_model?: string;
  llm_custom_endpoint?: string;
  llm_thinking_effort?: string;
}

export interface SystemSettingsUpdateRequest {
  worker_mode?: string;
  allow_registration?: boolean;
  require_admin_approval?: boolean;
  smtp_host?: string;
  smtp_port?: number;
  smtp_username?: string;
  smtp_password?: string;
  smtp_from?: string;
  kaggle_username?: string;
  kaggle_key?: string;
  kaggle_kernel_ref?: string;
  kaggle_kernel_slug?: string;
  kaggle_kernel_title?: string;
  kaggle_accelerator?: string;
  kaggle_timeout_seconds?: number;
  kaggle_idle_timeout_seconds?: number;
  kaggle_worker_dir?: string;
  ui_layout?: string;
  hf_token?: string;
  llm_provider?: string;
  llm_api_key?: string;
  llm_model?: string;
  llm_custom_endpoint?: string;
  llm_thinking_effort?: string;
}

export interface PaginatedJobsResponse {
  items: JobStatusResponse[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface LLMProfile {
  id: string;
  name: string;
  provider: string;
  api_key?: string;
  model: string;
  custom_endpoint?: string;
  thinking_effort: string;
  is_active: boolean;
  last_test_status: string;
  last_test_message?: string;
  last_tested_at?: string;
  created_at: string;
  updated_at: string;
}

export interface LLMProfileCreateRequest {
  name: string;
  provider?: string;
  api_key?: string;
  model?: string;
  custom_endpoint?: string;
  thinking_effort?: string;
  is_active?: boolean;
}

export interface LLMProfileUpdateRequest {
  name?: string;
  provider?: string;
  api_key?: string;
  model?: string;
  custom_endpoint?: string;
  thinking_effort?: string;
  is_active?: boolean;
}

export interface TestLLMProfileResponse {
  status: string;
  message: string;
  latency_ms?: number;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${getApiBaseUrl()}${path}`;
  
  const token = localStorage.getItem("VITE_JWT_TOKEN");
  const headers = new Headers(options?.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  
  const newOptions = {
    ...options,
    headers
  };
  
  const response = await fetch(url, newOptions);
  
  if (!response.ok) {
    let errorDetail = "";
    try {
      const errData = await response.json();
      errorDetail = errData.detail || response.statusText;
    } catch {
      errorDetail = response.statusText;
    }
    throw new Error(errorDetail || `HTTP error! Status: ${response.status}`);
  }
  
  return response.json() as Promise<T>;
}

export interface OmniVoiceParams {
  denoise?: boolean;
  guidance_scale?: number;
  t_shift?: number;
  position_temperature?: number;
  class_temperature?: number;
  layer_penalty_factor?: number;
  duration?: number;
  preprocess_prompt?: boolean;
  postprocess_output?: boolean;
  audio_chunk_duration?: number;
  audio_chunk_threshold?: number;
  with_alignment?: boolean;
  language?: string;
  pad_duration?: number;
  fade_duration?: number;
}

export const api = {
  getApiBaseUrl,
  setApiBaseUrl,

  getHealth: async (): Promise<HealthResponse> => {
    return request<HealthResponse>("/v1/health");
  },
  
  uploadVoiceSample: async (file: File, refText?: string, name?: string, customId?: string): Promise<VoiceSampleUploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    if (refText) {
      formData.append("ref_text", refText);
    }
    if (name) {
      formData.append("name", name);
    }
    if (customId) {
      formData.append("custom_id", customId);
    }
    
    return request<VoiceSampleUploadResponse>("/v1/voice-samples", {
      method: "POST",
      body: formData,
    });
  },
  
  createVoiceDesignPreview: async (voiceRequest: string, previewText: string, speed?: number, numStep?: number, params?: OmniVoiceParams): Promise<VoiceDesignPreviewResponse> => {
    return request<VoiceDesignPreviewResponse>("/v1/voice-design/previews", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ 
        voice_request: voiceRequest, 
        preview_text: previewText,
        speed: speed !== undefined ? speed : 1.0,
        num_step: numStep !== undefined ? numStep : 32,
        ...params
      }),
    });
  },
  
  getPreviewInfo: async (previewId: string): Promise<VoiceDesignPreviewDetail> => {
    return request<VoiceDesignPreviewDetail>(`/v1/voice-design/previews/${previewId}?t=${Date.now()}`);
  },
  
  acceptPreview: async (previewId: string): Promise<AcceptPreviewResponse> => {
    return request<AcceptPreviewResponse>(`/v1/voice-design/previews/${previewId}/accept`, {
      method: "POST",
    });
  },
  
  createTTSJob: async (mode: string, text: string, voiceSampleId?: string, instruct?: string, speed?: number, numStep?: number, params?: OmniVoiceParams, refText?: string): Promise<TTSJobResponse> => {
    return request<TTSJobResponse>("/v1/tts/jobs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        mode,
        text,
        voice_sample_id: voiceSampleId || null,
        ref_text: refText || null,
        instruct: instruct || null,
        speed: speed !== undefined ? speed : 1.0,
        num_step: numStep !== undefined ? numStep : 32,
        ...params
      }),
    });
  },
  
  createASRJob: async (file: File): Promise<TTSJobResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    return request<TTSJobResponse>("/v1/asr", {
      method: "POST",
      body: formData,
    });
  },

  getASRAudioUrl: (jobId: string): string => {
    const token = localStorage.getItem("VITE_JWT_TOKEN");
    const baseUrl = getApiBaseUrl();
    return `${baseUrl}/v1/asr/jobs/${jobId}/audio?token=${token || ""}`;
  },
  
  getJobStatus: async (jobId: string): Promise<JobStatusResponse> => {
    return request<JobStatusResponse>(`/v1/jobs/${jobId}?t=${Date.now()}`);
  },
  
  listJobs: async (params?: {
    page?: number;
    page_size?: number;
    job_type?: string;
    status_filter?: string;
    search?: string;
  }): Promise<PaginatedJobsResponse> => {
    const query = new URLSearchParams();
    query.set("page", String(params?.page || 1));
    query.set("page_size", String(params?.page_size || 15));
    if (params?.job_type && params.job_type !== "all") query.set("job_type", params.job_type);
    if (params?.status_filter && params.status_filter !== "all") query.set("status_filter", params.status_filter);
    if (params?.search && params.search.trim()) query.set("search", params.search.trim());

    return request<PaginatedJobsResponse>(`/v1/jobs?${query.toString()}`);
  },

  deleteJob: async (jobId: string): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>(`/v1/jobs/${jobId}`, {
      method: "DELETE",
    });
  },

  getSettings: async (): Promise<SystemSettings> => {
    return request<SystemSettings>(`/v1/settings?t=${Date.now()}`);
  },

  updateSettings: async (payload: SettingsUpdateRequest): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>("/v1/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  },

  listLlmProfiles: async (): Promise<LLMProfile[]> => {
    return request<LLMProfile[]>("/v1/admin/llm-profiles");
  },

  createLlmProfile: async (payload: LLMProfileCreateRequest): Promise<LLMProfile> => {
    return request<LLMProfile>("/v1/admin/llm-profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  updateLlmProfile: async (profileId: string, payload: LLMProfileUpdateRequest): Promise<LLMProfile> => {
    return request<LLMProfile>(`/v1/admin/llm-profiles/${profileId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  deleteLlmProfile: async (profileId: string): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>(`/v1/admin/llm-profiles/${profileId}`, {
      method: "DELETE",
    });
  },

  activateLlmProfile: async (profileId: string): Promise<LLMProfile> => {
    return request<LLMProfile>(`/v1/admin/llm-profiles/${profileId}/activate`, {
      method: "POST",
    });
  },

  testLlmProfile: async (profileId: string): Promise<TestLLMProfileResponse> => {
    return request<TestLLMProfileResponse>(`/v1/admin/llm-profiles/${profileId}/test`, {
      method: "POST",
    });
  },

  testKaggleConnection: async (): Promise<{ success: boolean; message: string }> => {
    return request<{ success: boolean; message: string }>("/v1/settings/test-kaggle", {
      method: "POST",
    });
  },

  pushNotebook: async (): Promise<{ success: boolean; message: string; url?: string }> => {
    return request<{ success: boolean; message: string; url?: string }>("/v1/settings/push-notebook", {
      method: "POST",
    });
  },

  login: async (username: string, password: string): Promise<{ access_token: string; token_type: string }> => {
    return request<{ access_token: string; token_type: string }>("/v1/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password }),
    });
  },

  register: async (username: string, password: string, email: string): Promise<{ status: string; message: string; debug_code?: string }> => {
    return request<{ status: string; message: string; debug_code?: string }>("/v1/auth/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password, email }),
    });
  },

  verifyEmail: async (username: string, code: string): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>("/v1/auth/verify-email", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, code }),
    });
  },

  resendCode: async (username: string): Promise<{ status: string; message: string; debug_code?: string }> => {
    return request<{ status: string; message: string; debug_code?: string }>("/v1/auth/resend-code", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username }),
    });
  },

  oauthMock: async (email: string, username: string, oauthProvider: string, oauthId: string): Promise<{ access_token: string; token_type: string }> => {
    return request<{ access_token: string; token_type: string }>("/v1/auth/oauth/mock", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, username, oauth_provider: oauthProvider, oauth_id: oauthId }),
    });
  },

  oauthLogin: async (provider: string, redirectUri: string): Promise<{ auth_url: string }> => {
    return request<{ auth_url: string }>(`/v1/auth/oauth/login/${provider}?redirect_uri=${encodeURIComponent(redirectUri)}`);
  },

  oauthCallback: async (provider: string, code: string, redirectUri: string): Promise<{ access_token: string; token_type: string }> => {
    return request<{ access_token: string; token_type: string }>(`/v1/auth/oauth/callback/${provider}?code=${encodeURIComponent(code)}&redirect_uri=${encodeURIComponent(redirectUri)}`);
  },

  getMe: async (): Promise<UserMeResponse> => {
    return request<UserMeResponse>(`/v1/auth/me?t=${Date.now()}`);
  },

  // Multi-API Keys (User side)
  getUserApiKeys: async (): Promise<ApiKeyResponse[]> => {
    return request<ApiKeyResponse[]>("/v1/auth/apikeys");
  },

  createUserApiKey: async (name: string): Promise<ApiKeyResponse> => {
    return request<ApiKeyResponse>("/v1/auth/apikeys", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name }),
    });
  },

  deleteUserApiKey: async (keyId: string): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>(`/v1/auth/apikeys/${keyId}`, {
      method: "DELETE",
    });
  },

  // Deprecated single API key calls
  generateApiKey: async (): Promise<{ status: string; message: string; api_key: string }> => {
    return request<{ status: string; message: string; api_key: string }>("/v1/auth/apikey", {
      method: "POST",
    });
  },

  revokeApiKey: async (): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>("/v1/auth/apikey", {
      method: "DELETE",
    });
  },

  // Admin Portal endpoints
  getAdminUsers: async (): Promise<UserAdminResponse[]> => {
    return request<UserAdminResponse[]>("/v1/admin/users");
  },

  adminCreateUser: async (payload: UserCreateRequest): Promise<UserAdminResponse> => {
    return request<UserAdminResponse>("/v1/admin/users", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  },

  adminUpdateUser: async (userId: string, payload: UserUpdateRequest): Promise<UserAdminResponse> => {
    return request<UserAdminResponse>(`/v1/admin/users/${userId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  },

  // Deprecated simple update
  updateUser: async (userId: string, isVerified?: boolean, isAdmin?: boolean): Promise<UserAdminResponse> => {
    return request<UserAdminResponse>(`/v1/admin/users/${userId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ is_verified: isVerified, is_admin: isAdmin }),
    });
  },

  deleteUser: async (userId: string): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>(`/v1/admin/users/${userId}`, {
      method: "DELETE",
    });
  },

  adminGetUserApiKeys: async (userId: string): Promise<AdminApiKeyResponse[]> => {
    return request<AdminApiKeyResponse[]>(`/v1/admin/users/${userId}/apikeys`);
  },

  adminCreateUserApiKey: async (userId: string, name: string): Promise<AdminApiKeyResponse> => {
    return request<AdminApiKeyResponse>(`/v1/admin/users/${userId}/apikeys`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name }),
    });
  },

  adminDeleteApiKey: async (keyId: string): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>(`/v1/admin/apikeys/${keyId}`, {
      method: "DELETE",
    });
  },

  adminGetSystemSettings: async (): Promise<SystemSettingsResponse> => {
    return request<SystemSettingsResponse>("/v1/admin/settings");
  },

  adminUpdateSystemSettings: async (payload: SystemSettingsUpdateRequest): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>("/v1/admin/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  },

  scanLlmModels: async (provider?: string, apiKey?: string, customEndpoint?: string): Promise<{ status: string; models: string[]; count: number }> => {
    return request<{ status: string; models: string[]; count: number }>("/v1/admin/llm/scan-models", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider: provider || "gemini",
        api_key: apiKey || null,
        custom_endpoint: customEndpoint || null
      }),
    });
  },

  getAdminStats: async (): Promise<AdminStatsResponse> => {
    return request<AdminStatsResponse>("/v1/admin/stats");
  },

  getAdminLogs: async (statusCode?: number): Promise<ApiLogResponse[]> => {
    const url = statusCode !== undefined ? `/v1/admin/logs?status_code=${statusCode}` : "/v1/admin/logs";
    return request<ApiLogResponse[]>(url);
  },

  listVoiceSamples: async (tag?: string): Promise<VoiceSampleResponse[]> => {
    const params = tag ? `?tag=${encodeURIComponent(tag)}` : "";
    return request<VoiceSampleResponse[]>(`/v1/voice-samples${params}`);
  },

  saveFavoriteVoice: async (payload: { job_id?: string; preview_id?: string; name: string; is_public: boolean; ref_text: string; custom_id?: string; tags?: string[] }): Promise<VoiceSampleUploadResponse> => {
    return request<VoiceSampleUploadResponse>("/v1/voice-samples/save-favorite", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  },

  updateVoiceSample: async (voiceSampleId: string, payload: VoiceSampleUpdateRequest): Promise<VoiceSampleResponse> => {
    return request<VoiceSampleResponse>(`/v1/voice-samples/${voiceSampleId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  },

  deleteVoiceSample: async (voiceSampleId: string): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>(`/v1/voice-samples/${voiceSampleId}`, {
      method: "DELETE",
    });
  },

  createDubbingJob: async (file?: File, youtubeUrl?: string, targetLanguage?: string, uploadedJobId?: string, llmProfileId?: string): Promise<VideoDubbingJobResponse> => {
    const formData = new FormData();
    if (file) formData.append("file", file);
    if (youtubeUrl) formData.append("youtube_url", youtubeUrl);
    if (uploadedJobId) formData.append("uploaded_job_id", uploadedJobId);
    if (llmProfileId) formData.append("llm_profile_id", llmProfileId);
    formData.append("target_language", targetLanguage || "Vietnamese");
    return request<VideoDubbingJobResponse>("/v1/video-dubbing", {
      method: "POST",
      body: formData,
    });
  },

  uploadDubbingVideo: async (file: File, onProgress: (progress: number) => void): Promise<VideoDubbingJobResponse> => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const url = `${getApiBaseUrl()}/v1/video-dubbing/upload`;
      
      xhr.open("POST", url, true);
      
      // Add Authorization header if token exists
      const token = localStorage.getItem("VITE_JWT_TOKEN");
      if (token) {
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      }
      
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percentComplete = Math.round((event.loaded / event.total) * 100);
          onProgress(percentComplete);
        }
      };
      
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const res = JSON.parse(xhr.responseText) as VideoDubbingJobResponse;
            resolve(res);
          } catch (e) {
            reject(new Error("Không thể phân tích phản hồi từ server."));
          }
        } else {
          let errorMsg = "Tải video lên thất bại.";
          try {
            const errData = JSON.parse(xhr.responseText);
            errorMsg = errData.detail || errorMsg;
          } catch {}
          reject(new Error(errorMsg));
        }
      };
      
      xhr.onerror = () => {
        reject(new Error("Lỗi kết nối mạng khi tải video lên."));
      };
      
      const formData = new FormData();
      formData.append("file", file);
      xhr.send(formData);
    });
  },

  getDubbingCookieStatus: async (): Promise<{ has_cookies: boolean; size_bytes?: number; path?: string; modified_at?: number }> => {
    return request<{ has_cookies: boolean; size_bytes?: number; path?: string; modified_at?: number }>("/v1/video-dubbing/cookie-status");
  },

  uploadDubbingCookies: async (file?: File, cookieText?: string): Promise<{ status: string; message: string; size_bytes: number }> => {
    const formData = new FormData();
    if (file) formData.append("file", file);
    if (cookieText) formData.append("cookie_text", cookieText);
    return request<{ status: string; message: string; size_bytes: number }>("/v1/video-dubbing/upload-cookies", {
      method: "POST",
      body: formData,
    });
  },

  deleteDubbingCookies: async (): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>("/v1/video-dubbing/delete-cookies", {
      method: "DELETE",
    });
  },

  getYouTubeOAuthStatus: async (): Promise<{ connected: boolean; expires_at?: number; token_type?: string }> => {
    return request<{ connected: boolean; expires_at?: number; token_type?: string }>("/v1/video-dubbing/oauth/status");
  },

  startYouTubeOAuth: async (): Promise<{ user_code: string; device_code: string; verification_url: string; interval: number; expires_in: number }> => {
    return request<{ user_code: string; device_code: string; verification_url: string; interval: number; expires_in: number }>("/v1/video-dubbing/oauth/start", {
      method: "POST",
    });
  },

  pollYouTubeOAuth: async (deviceCode: string): Promise<{ status: "success" | "pending" | "error"; message?: string; error?: string }> => {
    return request<{ status: "success" | "pending" | "error"; message?: string; error?: string }>("/v1/video-dubbing/oauth/poll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_code: deviceCode }),
    });
  },

  disconnectYouTubeOAuth: async (): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>("/v1/video-dubbing/oauth/disconnect", {
      method: "DELETE",
    });
  },

  getDubbingJobLog: async (jobId: string): Promise<{ log: string }> => {
    return request<{ log: string }>(`/v1/video-dubbing/jobs/${jobId}/log?t=${Date.now()}`);
  },

  getDubbingJob: async (jobId: string): Promise<VideoDubbingJobResponse> => {
    return request<VideoDubbingJobResponse>(`/v1/video-dubbing/jobs/${jobId}?t=${Date.now()}`);
  },

  updateDubbingSubtitles: async (jobId: string, originalSubtitles?: SubtitleSegment[], translatedSubtitles?: SubtitleSegment[]): Promise<{ status: string; message: string }> => {
    return request<{ status: string; message: string }>(`/v1/video-dubbing/jobs/${jobId}/subtitles`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        original_subtitles: originalSubtitles || null,
        translated_subtitles: translatedSubtitles || null
      }),
    });
  },

  finalizeDubbingJob: async (jobId: string, vocalsVolume?: number, bgmVolume?: number): Promise<{ status: string; message: string }> => {
    const formData = new FormData();
    if (vocalsVolume !== undefined) formData.append("vocals_volume", String(vocalsVolume));
    if (bgmVolume !== undefined) formData.append("bgm_volume", String(bgmVolume));
    return request<{ status: string; message: string }>(`/v1/video-dubbing/jobs/${jobId}/finalize`, {
      method: "POST",
      body: formData,
    });
  },

  getDubbingFileUrl: (jobId: string, type: 'video' | 'vocals' | 'bgm' | 'output'): string => {
    const token = localStorage.getItem("VITE_JWT_TOKEN");
    const baseUrl = getApiBaseUrl();
    return `${baseUrl}/v1/video-dubbing/jobs/${jobId}/${type}?token=${token || ""}`;
  },
};

export interface UserMeResponse {
  id: string;
  username: string;
  email: string | null;
  is_verified: boolean;
  is_admin: boolean;
  has_api_key: boolean;
  api_key: string | null;
  created_at: string;
}

export interface UserAdminResponse {
  id: string;
  username: string;
  email: string | null;
  is_verified: boolean;
  is_approved: boolean;
  is_admin: boolean;
  oauth_provider: string | null;
  created_at: string;
}

export interface AdminStatsResponse {
  total_users: number;
  verified_users: number;
  active_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  total_api_calls: number;
}

export interface ApiLogResponse {
  id: string;
  user_id: string | null;
  username: string | null;
  endpoint: string;
  method: string;
  status_code: number;
  ip_address: string | null;
  duration_ms: number;
  created_at: string;
}

export interface SystemSettings {
  kaggle_username: string;
  kaggle_key_configured: boolean;
  kaggle_kernel_ref: string;
  kaggle_kernel_slug: string;
  kaggle_kernel_title: string;
  kaggle_accelerator: string;
  kaggle_timeout_seconds: number;
  kaggle_worker_dir: string;
  worker_mode: string;
  ui_layout: string;
}

export interface SettingsUpdateRequest {
  kaggle_username?: string;
  kaggle_key?: string;
  kaggle_kernel_ref?: string;
  kaggle_kernel_slug?: string;
  kaggle_kernel_title?: string;
  kaggle_accelerator?: string;
  kaggle_timeout_seconds?: number;
  kaggle_worker_dir?: string;
}

export interface SubtitleSegment {
  id: number;
  start: number;
  end: number;
  text: string;
}

export interface VideoDubbingJobResponse {
  id: string;
  status: string;
  progress: number;
  message: string | null;
  source_type: string;
  source_url: string | null;
  target_language: string;
  original_subtitles: SubtitleSegment[] | null;
  translated_subtitles: SubtitleSegment[] | null;
  vocals_audio_path: string | null;
  bgm_audio_path: string | null;
  output_video_url: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}
