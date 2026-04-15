import type { LatestNewsItem } from '../types/api';
import './NewsFeed.css';

interface NewsFeedProps {
  items: LatestNewsItem[];
}

function formatTime(ts?: number): string {
  if (!ts) {
    return '--';
  }
  const date = new Date(ts * 1000);
  if (Number.isNaN(date.getTime())) {
    return '--';
  }
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${d} ${hh}:${mm}`;
}

function scoreClass(score: number): string {
  if (score > 0) {
    return 'news-score news-score--positive';
  }
  if (score < 0) {
    return 'news-score news-score--negative';
  }
  return 'news-score news-score--neutral';
}

export function NewsFeed({ items }: NewsFeedProps) {
  return (
    <div className="news-feed">
      {items.map((item, index) => {
        const score = Number(item.llm_analysis?.score ?? 0);
        const scoreLabel = score > 0 ? `+${score}` : String(score);
        const title = item.content?.slice(0, 38) || `资讯 ${index + 1}`;
        const sectors = item.llm_analysis?.sectors ?? [];

        return (
          <article className="news-item" key={item.event_id ?? `${title}-${index}`}>
            <header className="news-item__header">
              <h3 className="news-item__title">{title}</h3>
              <span className={scoreClass(score)}>{scoreLabel}</span>
            </header>
            <p className="news-item__desc">{item.content || '暂无内容'}</p>
            <footer className="news-item__meta">
              <span>{sectors.length > 0 ? sectors.join(' / ') : '未识别板块'}</span>
              <span>{formatTime(item.publish_ts)}</span>
            </footer>
          </article>
        );
      })}
    </div>
  );
}
