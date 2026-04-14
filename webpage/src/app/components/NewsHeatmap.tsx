import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { Flame } from 'lucide-react';

interface NewsHeatmapProps {
  onSectorClick: (sector: string | null) => void;
  selectedSector: string | null;
}

export function NewsHeatmap({ onSectorClick, selectedSector }: NewsHeatmapProps) {
  // 前10热门板块数据
  const hotSectors = [
    { rank: 1, name: '科技创新', count: 195, growth: 25.0, avgSentiment: 'positive' as const },
    { rank: 2, name: '新能源汽车', count: 178, growth: 32.8, avgSentiment: 'positive' as const },
    { rank: 3, name: '医药生物', count: 142, growth: 44.9, avgSentiment: 'positive' as const },
    { rank: 4, name: '消费升级', count: 102, growth: 17.2, avgSentiment: 'neutral' as const },
    { rank: 5, name: '金融科技', count: 80, growth: 23.1, avgSentiment: 'positive' as const },
    { rank: 6, name: '国防军工', count: 72, growth: -8.9, avgSentiment: 'negative' as const },
    { rank: 7, name: '房地产', count: 68, growth: 15.3, avgSentiment: 'neutral' as const },
    { rank: 8, name: '新材料', count: 58, growth: -5.2, avgSentiment: 'negative' as const },
    { rank: 9, name: '农业科技', count: 52, growth: 8.3, avgSentiment: 'neutral' as const },
    { rank: 10, name: '文化传媒', count: 45, growth: -2.2, avgSentiment: 'negative' as const }
  ];

  // 前5板块的周度新闻数量趋势
  const top5Sectors = hotSectors.slice(0, 5);
  const chartData = [
    {
      date: '周一',
      [top5Sectors[0].name]: 156,
      [top5Sectors[1].name]: 134,
      [top5Sectors[2].name]: 98,
      [top5Sectors[3].name]: 87,
      [top5Sectors[4].name]: 65
    },
    {
      date: '周二',
      [top5Sectors[0].name]: 168,
      [top5Sectors[1].name]: 142,
      [top5Sectors[2].name]: 105,
      [top5Sectors[3].name]: 92,
      [top5Sectors[4].name]: 70
    },
    {
      date: '周三',
      [top5Sectors[0].name]: 145,
      [top5Sectors[1].name]: 158,
      [top5Sectors[2].name]: 112,
      [top5Sectors[3].name]: 88,
      [top5Sectors[4].name]: 62
    },
    {
      date: '周四',
      [top5Sectors[0].name]: 182,
      [top5Sectors[1].name]: 165,
      [top5Sectors[2].name]: 128,
      [top5Sectors[3].name]: 95,
      [top5Sectors[4].name]: 75
    },
    {
      date: '周五',
      [top5Sectors[0].name]: top5Sectors[0].count,
      [top5Sectors[1].name]: top5Sectors[1].count,
      [top5Sectors[2].name]: top5Sectors[2].count,
      [top5Sectors[3].name]: top5Sectors[3].count,
      [top5Sectors[4].name]: top5Sectors[4].count
    }
  ];

  const lineColors = ['#3b82f6', '#10b981', '#8b5cf6', '#f59e0b', '#64748b'];

  const displaySectors = selectedSector
    ? hotSectors.filter(s => s.name === selectedSector)
    : top5Sectors;

  const displayChartData = selectedSector
    ? chartData.map(data => ({
        date: data.date,
        [selectedSector]: data[selectedSector]
      }))
    : chartData;

  const getSentimentBadge = (sentiment: string) => {
    switch (sentiment) {
      case 'positive':
        return <span className="px-2 py-0.5 bg-green-500/10 border border-green-500/30 text-green-400 rounded text-xs">利好</span>;
      case 'negative':
        return <span className="px-2 py-0.5 bg-red-500/10 border border-red-500/30 text-red-400 rounded text-xs">利空</span>;
      default:
        return <span className="px-2 py-0.5 bg-slate-700/30 border border-slate-600/30 text-slate-400 rounded text-xs">中性</span>;
    }
  };

  return (
    <div className="bg-slate-900/50 backdrop-blur-xl rounded-2xl border border-slate-800/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <Flame className="w-4 h-4 text-orange-400" />
          <h3 className="text-sm text-white">版块新闻热度</h3>
        </div>
        <p className="text-xs text-slate-500 mt-1">统计各板块相关资讯数量及情绪 · 前5板块趋势</p>
      </div>

      <div className="p-5">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={displayChartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.3} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: '#64748b' }}
              stroke="#334155"
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#64748b' }}
              stroke="#334155"
              tickLine={false}
              width={35}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1e293b',
                border: '1px solid #334155',
                borderRadius: '8px',
                fontSize: '11px',
                color: '#e2e8f0'
              }}
            />
            <Legend wrapperStyle={{ fontSize: '11px' }} />
            {displaySectors.map((sector, index) => (
              <Line
                key={sector.name}
                type="monotone"
                dataKey={sector.name}
                stroke={lineColors[selectedSector ? hotSectors.findIndex(s => s.name === sector.name) : index]}
                strokeWidth={2}
                dot={{ r: 3 }}
                name={sector.name}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="px-5 pb-5">
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="grid grid-cols-5 gap-px bg-slate-700/30">
            <div className="px-3 py-2 bg-slate-800/50 text-xs text-slate-400">排名</div>
            <div className="px-3 py-2 bg-slate-800/50 text-xs text-slate-400 col-span-2">板块</div>
            <div className="px-3 py-2 bg-slate-800/50 text-xs text-slate-400 text-right">资讯数</div>
            <div className="px-3 py-2 bg-slate-800/50 text-xs text-slate-400 text-center">周情绪</div>
          </div>
          <div className="divide-y divide-slate-700/30">
            {hotSectors.map((sector) => (
              <div
                key={sector.rank}
                className={`grid grid-cols-5 gap-px cursor-pointer transition-colors ${
                  selectedSector === sector.name
                    ? 'bg-blue-500/20'
                    : 'bg-slate-800/20 hover:bg-slate-800/40'
                }`}
                onClick={() => onSectorClick(selectedSector === sector.name ? null : sector.name)}
              >
                <div className="px-3 py-2.5 text-xs text-slate-400">#{sector.rank}</div>
                <div className={`px-3 py-2.5 text-sm col-span-2 ${
                  selectedSector === sector.name ? 'text-blue-300' : 'text-slate-200'
                }`}>{sector.name}</div>
                <div className="px-3 py-2.5 text-right">
                  <div className="text-sm text-white">{sector.count}</div>
                  <div className={`text-xs ${sector.growth > 0 ? 'text-red-400' : 'text-green-400'}`}>
                    {sector.growth > 0 ? '+' : ''}{sector.growth}%
                  </div>
                </div>
                <div className="px-3 py-2.5 flex items-center justify-center">
                  {getSentimentBadge(sector.avgSentiment)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
