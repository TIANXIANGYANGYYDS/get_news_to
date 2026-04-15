import { useEffect, useMemo, useState } from 'react';
import type { ChangeEvent } from 'react';
import { TopicCard } from '../components/TopicCard';
import { NewsFeed } from '../components/NewsFeed';
import { fallbackMainlineTopics } from '../data/mainlineData';
import type { MainlineTopic } from '../data/mainlineData';
import { fetchLatestNews } from '../services/newsApi';
import type { LatestNewsItem } from '../types/api';
import { buildMainlineTopics } from '../utils/mainlineRankings';
import '../styles/mainlinePage.css';

type CategoryFilter = '全部' | '偏好' | '热度';
type SortMode = '默认' | '综合分' | '资讯数' | '最新时间';
type SceneMode = '实时数据' | '加载态' | '空态' | '错误态';

export function MainlinePage() {
  const [newsItems, setNewsItems] = useState<LatestNewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('全部');
  const [searchKeyword, setSearchKeyword] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('默认');
  const [expandedIds, setExpandedIds] = useState<number[]>([]);
  const [activeCardId, setActiveCardId] = useState<number | null>(null);
  const [activeSector, setActiveSector] = useState('全部');
  const [sceneMode, setSceneMode] = useState<SceneMode>('实时数据');

  async function loadMainline(activeRef: { active: boolean }) {
    setLoading(true);
    setError('');

    try {
      const data = await fetchLatestNews(100);
      if (!activeRef.active) {
        return;
      }
      setNewsItems(data);
    } catch (err) {
      if (!activeRef.active) {
        return;
      }
      const message = err instanceof Error ? err.message : '加载失败';
      setError(`接口异常：${message}，已使用设计稿示例数据。`);
      setNewsItems([]);
    } finally {
      if (activeRef.active) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    const activeRef = { active: true };
    void loadMainline(activeRef);

    return () => {
      activeRef.active = false;
    };
  }, []);

  const topics = useMemo(() => {
    const computed = buildMainlineTopics(newsItems);
    return computed.length > 0 ? computed : fallbackMainlineTopics;
  }, [newsItems]);

  const filteredTopics = useMemo<MainlineTopic[]>(() => {
    const base = topics.filter((item) => {
      const hitCategory = categoryFilter === '全部' || item.category === categoryFilter;
      const hitKeyword = searchKeyword.trim().length === 0 || item.title.includes(searchKeyword.trim());
      return hitCategory && hitKeyword;
    });

    if (sortMode === '综合分') {
      return [...base].sort((a, b) => Number(b.score) - Number(a.score));
    }

    if (sortMode === '资讯数') {
      return [...base].sort((a, b) => b.newsCount - a.newsCount);
    }

    if (sortMode === '最新时间') {
      return [...base].sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1));
    }

    return base;
  }, [topics, categoryFilter, searchKeyword, sortMode]);

  const stats = useMemo(() => {
    return {
      total: filteredTopics.length,
      preferenceCount: filteredTopics.filter((item) => item.category === '偏好').length,
      heatCount: filteredTopics.filter((item) => item.category === '热度').length,
    };
  }, [filteredTopics]);

  const sectorOptions = useMemo(() => {
    const set = new Set<string>(['全部']);
    newsItems.forEach((item) => {
      (item.llm_analysis?.sectors ?? []).forEach((sector) => set.add(sector));
    });
    return Array.from(set).slice(0, 8);
  }, [newsItems]);

  const filteredNews = useMemo(() => {
    const keyword = searchKeyword.trim();
    return newsItems
      .filter((item) => {
        const sectors = item.llm_analysis?.sectors ?? [];
        const hitSector = activeSector === '全部' || sectors.includes(activeSector);
        const haystack = `${item.content ?? ''} ${sectors.join(' ')}`.toLowerCase();
        const hitKeyword = keyword.length === 0 || haystack.includes(keyword.toLowerCase());
        return hitSector && hitKeyword;
      })
      .slice(0, 20);
  }, [newsItems, activeSector, searchKeyword]);

  const renderedTopics = useMemo(() => {
    if (sceneMode === '空态') {
      return [];
    }
    if (sceneMode === '错误态') {
      return fallbackMainlineTopics.slice(0, 2);
    }
    return filteredTopics;
  }, [sceneMode, filteredTopics]);

  const renderedNews = useMemo(() => {
    if (sceneMode === '空态') {
      return [];
    }
    if (sceneMode === '错误态') {
      return [];
    }
    return filteredNews;
  }, [sceneMode, filteredNews]);

  const sentiment = useMemo(() => {
    const scores = filteredNews.map((item) => Number(item.llm_analysis?.score ?? 0));
    const positive = scores.filter((score) => score > 0).length;
    const neutral = scores.filter((score) => score === 0).length;
    const negative = scores.filter((score) => score < 0).length;
    const total = Math.max(filteredNews.length, 1);
    return {
      positive,
      neutral,
      negative,
      positivePct: Math.round((positive / total) * 100),
      neutralPct: Math.round((neutral / total) * 100),
      negativePct: Math.round((negative / total) * 100),
    };
  }, [filteredNews]);

  function handleToggle(id: number) {
    setActiveCardId(id);
    setExpandedIds((prev: number[]) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));
  }

  function handleSortChange(event: ChangeEvent<HTMLSelectElement>) {
    setSortMode(event.target.value as SortMode);
  }

  function handleSearchChange(event: ChangeEvent<HTMLInputElement>) {
    setSearchKeyword(event.target.value);
  }

  return (
    <main className="mainline-layout">
      <header className="mainline-toolbar">
        <div className="mainline-title">主线分析</div>
        <div className="mainline-status" role="status" aria-live="polite">
          {loading ? '正在对接后端接口 /api/news/latest ...' : error || '接口对接成功：/api/news/latest'}
        </div>
      </header>
      <section className="mainline-controls" aria-label="主线筛选工具栏">
        <div className="mainline-tabs">
          {(['全部', '偏好', '热度'] as CategoryFilter[]).map((tab) => (
            <button
              key={tab}
              type="button"
              className={`mainline-tab ${categoryFilter === tab ? 'is-active' : ''}`}
              onClick={() => setCategoryFilter(tab)}
            >
              {tab}
            </button>
          ))}
        </div>
        <input
          className="mainline-search"
          value={searchKeyword}
          onChange={handleSearchChange}
          placeholder="搜索板块名称"
          aria-label="搜索板块名称"
        />
        <select
          className="mainline-sort"
          value={sortMode}
          onChange={handleSortChange}
          aria-label="排序方式"
        >
          <option value="默认">默认排序</option>
          <option value="综合分">综合分优先</option>
          <option value="资讯数">资讯数优先</option>
          <option value="最新时间">最新时间优先</option>
        </select>
        <button className="mainline-refresh" type="button" onClick={() => void loadMainline({ active: true })}>
          刷新
        </button>
      </section>
      <section className="scene-switcher" aria-label="页面状态切换">
        {(['实时数据', '加载态', '空态', '错误态'] as SceneMode[]).map((mode) => (
          <button
            key={mode}
            className={`scene-switcher__btn ${sceneMode === mode ? 'is-active' : ''}`}
            type="button"
            onClick={() => setSceneMode(mode)}
          >
            {mode}
          </button>
        ))}
      </section>
      <section className="mainline-indexes" aria-label="指数概览">
        <article className="index-card">
          <div className="index-card__name">上证指数</div>
          <div className="index-card__value">3346.72 <span className="index-card__delta">+0.68%</span></div>
        </article>
        <article className="index-card">
          <div className="index-card__name">深证成指</div>
          <div className="index-card__value">10816.34 <span className="index-card__delta">+0.54%</span></div>
        </article>
        <article className="index-card">
          <div className="index-card__name">创业板指</div>
          <div className="index-card__value">2212.18 <span className="index-card__delta">+0.73%</span></div>
        </article>
      </section>
      <section className="mainline-metrics" aria-label="统计信息">
        <span>当前主线 {stats.total} 条</span>
        <span>偏好 {stats.preferenceCount} 条</span>
        <span>热度 {stats.heatCount} 条</span>
      </section>
      <section className="dashboard-grid">
        <aside className="left-panel">
          <div className="sentiment-row">
            <div className="sentiment-card sentiment-card--good">
              <div className="sentiment-card__pct">利好 {sentiment.positivePct}%</div>
              <div className="sentiment-card__count">{sentiment.positive} 条</div>
            </div>
            <div className="sentiment-card sentiment-card--neutral">
              <div className="sentiment-card__pct">中性 {sentiment.neutralPct}%</div>
              <div className="sentiment-card__count">{sentiment.neutral} 条</div>
            </div>
            <div className="sentiment-card sentiment-card--bad">
              <div className="sentiment-card__pct">利空 {sentiment.negativePct}%</div>
              <div className="sentiment-card__count">{sentiment.negative} 条</div>
            </div>
          </div>
          <div className="sector-filter-row">
            {sectorOptions.map((sector) => (
              <button
                key={sector}
                type="button"
                className={`sector-filter ${activeSector === sector ? 'is-active' : ''}`}
                onClick={() => setActiveSector(sector)}
              >
                {sector}
              </button>
            ))}
          </div>
          {sceneMode === '加载态' ? <div className="panel-placeholder">资讯加载中...</div> : <NewsFeed items={renderedNews} />}
        </aside>
        <section className="right-panel mainline-list" aria-label="主线分析列表">
          {sceneMode === '加载态' && <div className="panel-placeholder">主线加载中...</div>}
          {sceneMode === '错误态' && <div className="panel-placeholder panel-placeholder--error">接口异常，已回退到示例主线。</div>}
          {sceneMode === '空态' && <div className="panel-placeholder">当前筛选下暂无主线数据。</div>}
          {renderedTopics.map((topic) => (
            <TopicCard
              key={topic.id}
              topic={topic}
              isExpanded={expandedIds.includes(topic.id)}
              isActive={activeCardId === topic.id}
              onToggle={handleToggle}
            />
          ))}
        </section>
      </section>
    </main>
  );
}
