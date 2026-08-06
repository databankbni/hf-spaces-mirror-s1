/**
 * API客户端模块
 *
 * 封装HTTP请求，提供统一的API调用接口。
 * 处理请求/响应拦截、错误处理、认证等。
 */

import { ApiResponse } from '../types';

/**
 * API基础URL
 * - 生产模式（同源）：使用相对路径，请求发到当前 origin
 * - 开发模式（Vite proxy）：使用 /api/v1，由 vite proxy 转发到后端
 */
const API_BASE_URL = import.meta.env.PROD ? '/api/v1' : (import.meta.env.VITE_API_URL || '/api/v1');

/**
 * 请求配置选项
 */
interface RequestOptions extends RequestInit {
  /** 请求参数（自动拼接到URL） */
  params?: Record<string, string | number | boolean | undefined>;
}

/**
 * API错误类
 *
 * 用于封装API请求失败时的错误信息。
 */
export class ApiError extends Error {
  /** HTTP状态码 */
  status: number;
  /** 错误代码 */
  code: number;
  /** 错误详情 */
  details?: Record<string, unknown>;
  /** 请求URL（用于定位404等错误来源） */
  url: string;
  /** 请求方法 */
  method: string;

  constructor(
    message: string,
    status: number,
    code: number,
    details?: Record<string, unknown>,
    url: string = '',
    method: string = '',
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.url = url;
    this.method = method;
  }
}

/**
 * 构建URL查询参数
 *
 * @param params - 参数对象
 * @returns 查询字符串（不含?）
 */
function buildQueryString(params: Record<string, string | number | boolean | undefined>): string {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) {
      searchParams.append(key, String(value));
    }
  });
  return searchParams.toString();
}

/**
 * 发送API请求
 *
 * @template T - 响应数据类型
 * @param endpoint - API端点（不含基础URL）
 * @param options - 请求选项
 * @returns Promise<T> - 响应数据
 * @throws ApiError - 请求失败时抛出
 */
async function request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { params, ...fetchOptions } = options;

  // 构建完整URL
  let url = `${API_BASE_URL}${endpoint}`;
  if (params) {
    const queryString = buildQueryString(params);
    if (queryString) {
      url += `?${queryString}`;
    }
  }

  // 设置默认headers
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  }

  // 发送请求
  const response = await fetch(url, {
    ...fetchOptions,
    headers,
  });

  // 解析响应
  const data = await response.json();

  // 检查响应状态
  if (!response.ok) {
    throw new ApiError(
      data.detail || data.message || 'Request failed',
      response.status,
      response.status,
      data,
      url,
      fetchOptions.method || 'GET',
    );
  }

  return data as T;
}

/**
 * API客户端
 *
 * 提供HTTP方法封装，支持泛型响应类型。
 */
export const apiClient = {
  /**
   * GET请求
   *
   * @template T - 响应数据类型
   * @param endpoint - API端点
   * @param params - 查询参数
   * @returns Promise<ApiResponse<T>> - 响应数据
   */
  get<T>(endpoint: string, params?: Record<string, string | number | boolean | undefined>): Promise<ApiResponse<T>> {
    return request<ApiResponse<T>>(endpoint, { method: 'GET', params });
  },

  /**
   * POST请求
   *
   * @template T - 响应数据类型
   * @param endpoint - API端点
   * @param body - 请求体
   * @returns Promise<ApiResponse<T>> - 响应数据
   */
  post<T>(endpoint: string, body?: unknown): Promise<ApiResponse<T>> {
    return request<ApiResponse<T>>(endpoint, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  /**
   * PUT请求
   *
   * @template T - 响应数据类型
   * @param endpoint - API端点
   * @param body - 请求体
   * @returns Promise<ApiResponse<T>> - 响应数据
   */
  put<T>(endpoint: string, body?: unknown): Promise<ApiResponse<T>> {
    return request<ApiResponse<T>>(endpoint, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  /**
   * PATCH请求
   *
   * @template T - 响应数据类型
   * @param endpoint - API端点
   * @param body - 请求体
   * @returns Promise<ApiResponse<T>> - 响应数据
   */
  patch<T>(endpoint: string, body?: unknown): Promise<ApiResponse<T>> {
    return request<ApiResponse<T>>(endpoint, {
      method: 'PATCH',
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  /**
   * DELETE请求
   *
   * @template T - 响应数据类型
   * @param endpoint - API端点
   * @returns Promise<ApiResponse<T>> - 响应数据
   */
  delete<T>(endpoint: string): Promise<ApiResponse<T>> {
    return request<ApiResponse<T>>(endpoint, { method: 'DELETE' });
  },

  /**
   * 下载文件（用于导出）
   *
   * @param endpoint - API端点
   * @param filename - 文件名
   * @param params - 查询参数
   */
  async download(endpoint: string, filename: string, params?: Record<string, string | number | boolean | undefined>): Promise<void> {
    let url = `${API_BASE_URL}${endpoint}`;
    if (params) {
      const queryString = buildQueryString(params);
      if (queryString) {
        url += `?${queryString}`;
      }
    }

    const response = await fetch(url);
    if (!response.ok) {
      throw new ApiError('Download failed', response.status, response.status, undefined, url, 'GET');
    }

    const blob = await response.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(downloadUrl);
  },

  async postDownload(endpoint: string, body: unknown, filename: string): Promise<void> {
    const url = `${API_BASE_URL}${endpoint}`;
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      throw new ApiError('Download failed', response.status, response.status, undefined, url, 'POST');
    }

    const blob = await response.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(downloadUrl);
  },

  /**
   * 上传文件（用于导入）
   *
   * @template T - 响应数据类型
   * @param endpoint - API端点
   * @param file - 文件对象
   * @param additionalData - 额外表单数据
   * @returns Promise<ApiResponse<T>> - 响应数据
   */
  async upload<T>(endpoint: string, file: File, additionalData?: Record<string, string>): Promise<ApiResponse<T>> {
    const formData = new FormData();
    formData.append('file', file);

    if (additionalData) {
      Object.entries(additionalData).forEach(([key, value]) => {
        formData.append(key, value);
      });
    }

    const url = `${API_BASE_URL}${endpoint}`;
    const response = await fetch(url, {
      method: 'POST',
      body: formData,
    });

    const data = await response.json();

    if (!response.ok) {
      throw new ApiError(
        data.message || 'Upload failed',
        response.status,
        data.code || response.status,
        data.details,
        url,
        'POST',
      );
    }

    return data as ApiResponse<T>;
  },
};

export default apiClient;
