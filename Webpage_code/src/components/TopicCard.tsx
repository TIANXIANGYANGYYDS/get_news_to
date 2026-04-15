import type { MainlineTopic } from '../data/mainlineData';
import './TopicCard.css';

interface TopicCardProps {
  topic: MainlineTopic;
  isExpanded: boolean;
  isActive: boolean;
  onToggle: (id: number) => void;
}

export function TopicCard({ topic, isExpanded, isActive, onToggle }: TopicCardProps) {
  return (
    <article
      className={`topic-card ${isActive ? 'topic-card--active' : ''}`}
      aria-label={`主线 ${topic.id}: ${topic.title}`}
    >
      <header className="topic-card__header">
        <span className="topic-card__rank">#{topic.id}</span>
        <h2 className="topic-card__title">
          {topic.title}（{topic.category}）
        </h2>
        <span className={`topic-card__badge ${topic.level === '次级主线' ? 'topic-card__badge--secondary' : ''}`}>
          {topic.level}
        </span>
        <button className="topic-card__toggle" type="button" onClick={() => onToggle(topic.id)}>
          {isExpanded ? '收起' : '展开'}
        </button>
      </header>
      <p className="topic-card__reason">
        理由： 排名 {topic.rank}， 综合分 {topic.score}， 资讯数 {topic.newsCount}， 最新时间 {topic.updatedAt}
      </p>
      {isExpanded && (
        <div className="topic-card__details">
          <span>交互态：卡片高亮</span>
          <span>排序依据：综合分 + 热度权重</span>
        </div>
      )}
    </article>
  );
}
