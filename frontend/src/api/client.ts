/**
 * HTTP API 客户端
 *
 * 基于 axios 封装，统一处理 base URL、错误拦截和请求头。
 * 所有 API 调用通过此模块发起。
 */

import axios, { AxiosError } from 'axios';

const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
});

// 响应拦截器 - 统一错误处理
client.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const message = error.response?.data
      ? (error.response.data as { detail?: string }).detail || error.message
      : error.message;
    console.error('[API Error]', message);
    return Promise.reject(error);
  }
);

export default client;
