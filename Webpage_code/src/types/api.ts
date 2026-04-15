export interface NewsLlmAnalysis {
  score?: number;
  reason?: string;
  sectors?: string[];
  companies?: string[];
}

export interface LatestNewsItem {
  event_id?: string;
  content?: string;
  publish_ts?: number;
  subjects?: string[];
  llm_analysis?: NewsLlmAnalysis;
}

export interface LatestNewsResponse {
  code: number;
  message: string;
  data: LatestNewsItem[];
}
