import type { LatestNewsItem, LatestNewsResponse } from '../types/api';

const DEFAULT_API_BASE = 'http://127.0.0.1:8092';

function getApiBase() {
  const value = import.meta.env.VITE_API_BASE_URL;
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : DEFAULT_API_BASE;
}

export async function fetchLatestNews(limit = 100): Promise<LatestNewsItem[]> {
  const base = getApiBase();
  const url = `${base}/api/news/latest?limit=${encodeURIComponent(String(limit))}`;

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`请求失败（${response.status}）`);
  }

  const payload = (await response.json()) as LatestNewsResponse;

  if (payload.code !== 0 || !Array.isArray(payload.data)) {
    throw new Error(payload.message || '返回数据格式错误');
  }

  return payload.data;
}
