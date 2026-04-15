import type { MainlineTopic } from '../data/mainlineData';
import type { LatestNewsItem } from '../types/api';

interface SectorStat {
  sector: string;
  newsCount: number;
  scoreTotal: number;
  latestPublishTs: number;
  positiveCount: number;
}

function scoreOf(item: LatestNewsItem): number {
  const score = Number(item.llm_analysis?.score ?? 0);
  return Number.isFinite(score) ? score : 0;
}

function sectorsOf(item: LatestNewsItem): string[] {
  const sectors = item.llm_analysis?.sectors;
  if (!Array.isArray(sectors) || sectors.length === 0) {
    return [];
  }
  return sectors.map((sector) => String(sector).trim()).filter(Boolean);
}

function buildSectorStats(newsItems: LatestNewsItem[]): Map<string, SectorStat> {
  const stats = new Map<string, SectorStat>();

  newsItems.forEach((item) => {
    const sectors = sectorsOf(item);
    if (sectors.length === 0) {
      return;
    }

    const publishTs = Number(item.publish_ts ?? 0);
    const score = scoreOf(item);

    sectors.forEach((sector) => {
      const previous = stats.get(sector) ?? {
        sector,
        newsCount: 0,
        scoreTotal: 0,
        latestPublishTs: 0,
        positiveCount: 0,
      };

      previous.newsCount += 1;
      previous.scoreTotal += score;
      previous.latestPublishTs = Math.max(previous.latestPublishTs, publishTs);
      previous.positiveCount += score > 0 ? 1 : 0;

      stats.set(sector, previous);
    });
  });

  return stats;
}

function formatDate(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) {
    return '--';
  }

  const date = new Date(ts * 1000);
  if (Number.isNaN(date.getTime())) {
    return '--';
  }

  const y = date.getFullYear();
  const m = date.getMonth() + 1;
  const d = date.getDate();
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  return `${y}/${m}/${d} ${hh}:${mm}:${ss}`;
}

function toTopics(
  rows: SectorStat[],
  category: '偏好' | '热度',
  startId: number,
): MainlineTopic[] {
  return rows.map((item, index) => {
    const avgScore = item.newsCount > 0 ? item.scoreTotal / item.newsCount : 0;
    const finalScore = category === '偏好' ? avgScore + item.positiveCount * 0.35 : item.newsCount * 1.5 + Math.max(avgScore, 0);

    return {
      id: startId + index,
      title: item.sector,
      category,
      level: finalScore >= 90 || index === 0 ? '核心主线' : '次级主线',
      rank: index + 1,
      score: finalScore.toFixed(2),
      newsCount: item.newsCount,
      updatedAt: formatDate(item.latestPublishTs),
    };
  });
}

export function buildMainlineTopics(newsItems: LatestNewsItem[]): MainlineTopic[] {
  const stats = Array.from(buildSectorStats(newsItems).values()).filter((row) => row.newsCount > 0);

  const preference = [...stats]
    .sort((a, b) => {
      const left = a.scoreTotal / a.newsCount + a.positiveCount * 0.35;
      const right = b.scoreTotal / b.newsCount + b.positiveCount * 0.35;
      return right - left;
    })
    .slice(0, 3);

  const selectedSectors = new Set(preference.map((row) => row.sector));

  const heat = [...stats]
    .filter((row) => !selectedSectors.has(row.sector))
    .sort((a, b) => {
      if (b.newsCount !== a.newsCount) {
        return b.newsCount - a.newsCount;
      }
      return b.latestPublishTs - a.latestPublishTs;
    })
    .slice(0, 2);

  return [...toTopics(preference, '偏好', 1), ...toTopics(heat, '热度', 4)];
}
