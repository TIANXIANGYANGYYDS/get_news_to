export type TopicCategory = '偏好' | '热度';

export interface MainlineTopic {
  id: number;
  title: string;
  category: TopicCategory;
  level: '核心主线' | '次级主线';
  rank: number;
  score: string;
  newsCount: number;
  updatedAt: string;
}

export const fallbackMainlineTopics: MainlineTopic[] = [
  {
    id: 1,
    title: '军工电子',
    category: '偏好',
    level: '核心主线',
    rank: 1,
    score: '91.04',
    newsCount: 34,
    updatedAt: '2026/4/4 21:23:43',
  },
  {
    id: 2,
    title: '光学光电子',
    category: '偏好',
    level: '核心主线',
    rank: 2,
    score: '90.45',
    newsCount: 9,
    updatedAt: '2026/4/4 18:53:03',
  },
  {
    id: 3,
    title: '电池',
    category: '偏好',
    level: '次级主线',
    rank: 3,
    score: '90.40',
    newsCount: 18,
    updatedAt: '2026/4/4 19:43:05',
  },
  {
    id: 4,
    title: '油气开采及服务',
    category: '热度',
    level: '核心主线',
    rank: 1,
    score: '94.50',
    newsCount: 103,
    updatedAt: '2026/4/4 21:00:47',
  },
  {
    id: 5,
    title: '军工装备',
    category: '热度',
    level: '次级主线',
    rank: 2,
    score: '94.25',
    newsCount: 66,
    updatedAt: '2026/4/4 21:23:43',
  },
];
