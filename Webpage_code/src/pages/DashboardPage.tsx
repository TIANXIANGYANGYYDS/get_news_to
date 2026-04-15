import { useState, useEffect } from 'react';
import { NewsCard } from '../components/NewsCard';
import { NewsDialog } from '../components/NewsDialog';
import { FilterPanel } from '../components/FilterPanel';
import { MarketAnalysis } from '../components/MarketAnalysis';
import { SectorTrend } from '../components/SectorTrend';
import { NewsHeatmap } from '../components/NewsHeatmap';
import { BarChart3, TrendingUp, Settings, ArrowUp } from 'lucide-react';

export default function App() {
  const [selectedNewsId, setSelectedNewsId] = useState('1');
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [selectedSector, setSelectedSector] = useState<string | null>(null);
  const [showScrollTop, setShowScrollTop] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      const scrollTop = window.scrollY || document.documentElement.scrollTop;
      setShowScrollTop(scrollTop > 300);
    };

    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const mockNews = [
    {
      id: '1',
      title: '央行宣布降准0.5个百分点，释放长期资金约1万亿元',
      summary: '中国人民银行决定于2026年4月15日下调金融机构存款准备金率0.5个百分点，此次降准将释放长期资金约1万亿元，旨在保持流动性合理充裕。',
      content: '中国人民银行今日宣布，为保持流动性合理充裕，促进货币信贷合理增长，决定于2026年4月15日下调金融机构存款准备金率0.5个百分点（不含已执行5%存款准备金率的金融机构）。\n\n此次降准为全面降准，除已执行5%存款准备金率的部分县域法人金融机构外，对其他金融机构普遍下调存款准备金率0.5个百分点。本次降准共计释放长期资金约1万亿元。\n\n央行有关负责人表示，此次降准是为了保持流动性合理充裕，促进货币信贷合理增长，为实体经济发展营造适宜的货币金融环境。降准后，金融机构的资金成本将有所降低，有利于降低实体经济融资成本，支持经济高质量发展。',
      source: '新华财经',
      time: '2小时前',
      author: '财经编辑部',
      sentiment: 'positive' as const,
      relatedStocks: ['上证指数', '银行板块', '地产板块'],
      impact: 2.3,
      keyPoints: [
        '全面降准0.5个百分点，释放长期资金约1万亿元',
        '有利于降低实体经济融资成本',
        '为经济高质量发展营造适宜的货币金融环境',
        '预计将带动银行、地产等板块上涨'
      ]
    },
    {
      id: '2',
      title: '新能源汽车销量创历史新高，3月同比增长42%',
      summary: '据中国汽车工业协会数据，2026年3月新能源汽车销量达到105万辆，同比增长42%，环比增长28%，创历史新高。',
      content: '中国汽车工业协会最新数据显示，2026年3月，新能源汽车产销分别完成108万辆和105万辆，同比分别增长40%和42%，环比分别增长25%和28%。\n\n其中，纯电动汽车产销分别完成78万辆和76万辆，同比分别增长38%和40%；插电式混合动力汽车产销分别完成30万辆和29万辆，同比分别增长45%和48%。\n\n业内专家表示，随着新能源汽车技术不断进步、产品日益丰富、配套设施逐步完善，消费者对新能源汽车的接受度持续提升。预计2026年全年新能源汽车销量将突破1200万辆，市场渗透率有望达到45%。',
      source: '证券时报',
      time: '4小时前',
      author: '汽车行业分析师',
      sentiment: 'positive' as const,
      relatedStocks: ['比亚迪', '宁德时代', '新能源板块'],
      impact: 3.1,
      keyPoints: [
        '3月新能源汽车销量105万辆，创历史新高',
        '同比增长42%，环比增长28%',
        '预计2026年全年销量将突破1200万辆',
        '市场渗透率有望达到45%'
      ]
    },
    {
      id: '3',
      title: '芯片板块遭遇回调，多只龙头股跌停',
      summary: '受国际贸易摩擦升级影响，今日芯片板块大幅回调，多只龙头股跌停，板块整体跌幅超过6%。',
      content: '今日A股市场芯片板块遭遇重挫，截至收盘，芯片指数下跌6.2%，板块内超过30只个股跌停。其中，某国产芯片龙头企业跌停，成交额放大至50亿元。\n\n市场分析认为，此次芯片板块大跌主要受以下因素影响：一是国际贸易摩擦升级，市场担忧芯片供应链安全；二是近期芯片板块涨幅较大，存在获利回吐压力；三是部分机构投资者主动降低仓位。\n\n不过，多位分析师表示，从中长期看，国产芯片替代是大势所趋，当前的回调为长期投资者提供了较好的布局机会。',
      source: '第一财经',
      time: '5小时前',
      author: '科技行业记者',
      sentiment: 'negative' as const,
      relatedStocks: ['中芯国际', '芯片板块', '科技股'],
      impact: -4.5,
      keyPoints: [
        '芯片板块整体跌幅超过6%',
        '超过30只个股跌停',
        '主要受国际贸易摩擦影响',
        '长期看国产替代仍是趋势'
      ]
    },
    {
      id: '4',
      title: 'A股三大指数集体收涨，沪指重返3400点',
      summary: '今日A股三大指数集体收涨，沪指涨1.2%重返3400点，深成指涨1.5%，创业板指涨1.8%。',
      content: 'A股三大指数今日集体收涨，截至收盘，上证指数报3425.67点，涨1.2%；深证成指报13567.89点，涨1.5%；创业板指报2789.45点，涨1.8%。\n\n盘面上，新能源、医药、消费等板块领涨，芯片、军工等板块走弱。北向资金全天净流入82亿元，连续5日净流入。\n\n分析人士指出，近期市场情绪明显回暖，主要得益于政策面的积极信号和基本面数据的改善。随着年报和一季报逐步披露，业绩确定性较强的优质公司有望获得资金青睐。',
      source: '东方财富',
      time: '6小时前',
      author: '市场分析师',
      sentiment: 'positive' as const,
      relatedStocks: ['上证指数', '深证成指', '创业板指'],
      impact: 1.5,
      keyPoints: [
        '三大指数集体收涨，沪指重返3400点',
        '新能源、医药、消费板块领涨',
        '北向资金净流入82亿元',
        '市场情绪明显回暖'
      ]
    },
    {
      id: '5',
      title: '医药板块持续活跃，创新药企业受关注',
      summary: '医药板块今日持续活跃，多只创新药概念股涨停，板块整体涨幅超过3%。',
      content: '医药板块今日表现强势，截至收盘，医药生物指数上涨3.2%，板块内超过20只个股涨停。其中，创新药概念股表现尤为突出，多只龙头企业涨停。\n\n业内人士分析，医药板块走强主要有以下原因：一是近期多个创新药获批上市，市场对创新药企业的发展前景充满信心；二是人口老龄化趋势下，医药需求持续增长；三是医保谈判政策逐步明朗，利好创新药企业。\n\n多家券商研报指出，随着创新药研发投入加大和审批加速，中国创新药行业将迎来黄金发展期。建议关注研发实力强、产品管线丰富的优质创新药企业。',
      source: '财新网',
      time: '7小时前',
      author: '医药行业研究员',
      sentiment: 'positive' as const,
      relatedStocks: ['恒瑞医药', '药明康德', '医药板块'],
      impact: 2.8,
      keyPoints: [
        '医药板块整体涨幅超过3%',
        '超过20只个股涨停',
        '创新药概念股表现突出',
        '人口老龄化推动医药需求增长'
      ]
    }
  ];

  const selectedNews = mockNews.find(news => news.id === selectedNewsId) || mockNews[0];

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="px-6 py-2.5 border-b border-slate-800/50 backdrop-blur-xl bg-slate-900/50">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-2 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-lg">
              <BarChart3 className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-base text-white">A股资讯分析</h1>
              <p className="text-xs text-slate-400">实时市场追踪</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 px-2.5 py-1 bg-slate-800/50 rounded-lg border border-slate-700/50">
              <div className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
              <span className="text-xs text-slate-300">实时</span>
            </div>
            <button className="p-2 bg-slate-800/50 rounded-lg border border-slate-700/50 hover:bg-slate-700/50 transition-colors">
              <Settings className="w-4 h-4 text-slate-400" />
            </button>
          </div>
        </div>
      </header>

      {/* Market Stats Bar */}
      <div className="px-6 py-2 border-b border-slate-800/50 bg-gradient-to-r from-slate-900/50 via-slate-800/30 to-slate-900/50">
        <div className="grid grid-cols-5 gap-2.5">
          <div className="p-2 bg-gradient-to-br from-red-500/10 to-red-600/5 border border-red-500/20 rounded-lg">
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-xs text-slate-400">上证指数</span>
              <TrendingUp className="w-3.5 h-3.5 text-red-400" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-lg text-white">3425.67</span>
              <span className="text-xs text-red-400">+1.2%</span>
            </div>
            <div className="text-xs text-slate-500 mt-0.5">+41.23</div>
          </div>

          <div className="p-2 bg-gradient-to-br from-red-500/10 to-red-600/5 border border-red-500/20 rounded-lg">
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-xs text-slate-400">深证成指</span>
              <TrendingUp className="w-3.5 h-3.5 text-red-400" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-lg text-white">13567.89</span>
              <span className="text-xs text-red-400">+1.5%</span>
            </div>
            <div className="text-xs text-slate-500 mt-0.5">+200.77</div>
          </div>

          <div className="p-2 bg-gradient-to-br from-red-500/10 to-red-600/5 border border-red-500/20 rounded-lg">
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-xs text-slate-400">创业板指</span>
              <TrendingUp className="w-3.5 h-3.5 text-red-400" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-lg text-white">2789.45</span>
              <span className="text-xs text-red-400">+1.8%</span>
            </div>
            <div className="text-xs text-slate-500 mt-0.5">+49.28</div>
          </div>

          <div className="p-2 bg-gradient-to-br from-red-500/10 to-red-600/5 border border-red-500/20 rounded-lg">
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-xs text-slate-400">科创50</span>
              <TrendingUp className="w-3.5 h-3.5 text-red-400" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-lg text-white">1256.34</span>
              <span className="text-xs text-red-400">+2.1%</span>
            </div>
            <div className="text-xs text-slate-500 mt-0.5">+25.82</div>
          </div>

          <div className="p-2 bg-gradient-to-br from-red-500/10 to-red-600/5 border border-red-500/20 rounded-lg">
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-xs text-slate-400">北证50</span>
              <TrendingUp className="w-3.5 h-3.5 text-red-400" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-lg text-white">945.78</span>
              <span className="text-xs text-red-400">+1.3%</span>
            </div>
            <div className="text-xs text-slate-500 mt-0.5">+12.14</div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="p-3">
        <div className="grid grid-cols-12 gap-3">
          {/* News Feed */}
          <div className="col-span-4 flex flex-col bg-slate-900/50 backdrop-blur-xl rounded-2xl border border-slate-800/50 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800/50">
              <h3 className="text-sm text-white mb-2">实时资讯</h3>
              <FilterPanel
                onSearchChange={(value) => console.log('Search:', value)}
                onSentimentFilter={(sentiment) => console.log('Sentiment:', sentiment)}
                onStockFilter={(stock) => console.log('Stock:', stock)}
              />
            </div>

            <div className="p-3 space-y-2">
              {mockNews.map((news) => (
                <NewsCard
                  key={news.id}
                  {...news}
                  isActive={selectedNewsId === news.id}
                  onClick={() => {
                    setSelectedNewsId(news.id);
                    setIsDialogOpen(true);
                  }}
                />
              ))}
              {mockNews.map((news) => (
                <NewsCard
                  key={`duplicate-${news.id}`}
                  {...news}
                  isActive={false}
                  onClick={() => {
                    setSelectedNewsId(news.id);
                    setIsDialogOpen(true);
                  }}
                />
              ))}
            </div>
          </div>

          {/* News Dialog */}
          <NewsDialog
            news={selectedNews}
            isOpen={isDialogOpen}
            onClose={() => setIsDialogOpen(false)}
          />

          {/* Main Content Area */}
          <div className="col-span-8 space-y-3">
            {/* Market Analysis */}
            <MarketAnalysis />

            {/* Sector Trend */}
            <SectorTrend onSectorClick={setSelectedSector} selectedSector={selectedSector} />

            {/* News Heatmap */}
            <NewsHeatmap onSectorClick={setSelectedSector} selectedSector={selectedSector} />
          </div>
        </div>
      </div>

      {/* Scroll to Top Button */}
      {showScrollTop && (
        <button
          onClick={scrollToTop}
          className="fixed bottom-6 right-6 p-3 bg-blue-600 hover:bg-blue-700 text-white rounded-full shadow-lg transition-all hover:scale-110 z-50"
          aria-label="回到顶端"
        >
          <ArrowUp className="w-5 h-5" />
        </button>
      )}
    </div>
  );
}