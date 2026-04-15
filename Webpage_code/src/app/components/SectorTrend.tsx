import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface SectorTrendProps {
  onSectorClick: (sector: string | null) => void;
  selectedSector: string | null;
}

export function SectorTrend({ onSectorClick, selectedSector }: SectorTrendProps) {
  // 前10板块数据
  const topSectors = [
    { rank: 1, name: '科技板块', score: 92, change: 7.8, trend: 'up' as const },
    { rank: 2, name: '新能源', score: 90, change: 12.3, trend: 'up' as const },
    { rank: 3, name: '医药生物', score: 82, change: 10.2, trend: 'up' as const },
    { rank: 4, name: '消费板块', score: 75, change: 7.1, trend: 'up' as const },
    { rank: 5, name: '金融板块', score: 62, change: 7.0, trend: 'up' as const },
    { rank: 6, name: '军工板块', score: 58, change: -2.3, trend: 'down' as const },
    { rank: 7, name: '地产板块', score: 55, change: 5.2, trend: 'up' as const },
    { rank: 8, name: '有色金属', score: 52, change: -1.8, trend: 'down' as const },
    { rank: 9, name: '农业板块', score: 48, change: 2.1, trend: 'up' as const },
    { rank: 10, name: '传媒板块', score: 45, change: -0.5, trend: 'down' as const }
  ];

  // 前5板块的周度趋势数据
  const top5Sectors = topSectors.slice(0, 5);
  const chartData = [
    {
      date: '周一',
      [top5Sectors[0].name]: 85,
      [top5Sectors[1].name]: 78,
      [top5Sectors[2].name]: 72,
      [top5Sectors[3].name]: 68,
      [top5Sectors[4].name]: 55
    },
    {
      date: '周二',
      [top5Sectors[0].name]: 88,
      [top5Sectors[1].name]: 82,
      [top5Sectors[2].name]: 75,
      [top5Sectors[3].name]: 65,
      [top5Sectors[4].name]: 58
    },
    {
      date: '周三',
      [top5Sectors[0].name]: 82,
      [top5Sectors[1].name]: 85,
      [top5Sectors[2].name]: 78,
      [top5Sectors[3].name]: 70,
      [top5Sectors[4].name]: 52
    },
    {
      date: '周四',
      [top5Sectors[0].name]: 90,
      [top5Sectors[1].name]: 88,
      [top5Sectors[2].name]: 80,
      [top5Sectors[3].name]: 72,
      [top5Sectors[4].name]: 60
    },
    {
      date: '周五',
      [top5Sectors[0].name]: top5Sectors[0].score,
      [top5Sectors[1].name]: top5Sectors[1].score,
      [top5Sectors[2].name]: top5Sectors[2].score,
      [top5Sectors[3].name]: top5Sectors[3].score,
      [top5Sectors[4].name]: top5Sectors[4].score
    }
  ];

  const lineColors = ['#3b82f6', '#10b981', '#8b5cf6', '#f59e0b', '#64748b'];

  const displaySectors = selectedSector
    ? topSectors.filter(s => s.name === selectedSector)
    : top5Sectors;

  const displayChartData = selectedSector
    ? chartData.map(data => ({
        date: data.date,
        [selectedSector]: data[selectedSector]
      }))
    : chartData;

  return (
    <div className="bg-slate-900/50 backdrop-blur-xl rounded-2xl border border-slate-800/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-800/50">
        <h3 className="text-sm text-white">市场版块投资倾向</h3>
        <p className="text-xs text-slate-500 mt-1">基于资金流向、情绪指标综合评分 · 前5板块趋势</p>
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
                stroke={lineColors[selectedSector ? topSectors.findIndex(s => s.name === sector.name) : index]}
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
            <div className="px-3 py-2 bg-slate-800/50 text-xs text-slate-400 text-right">评分</div>
            <div className="px-3 py-2 bg-slate-800/50 text-xs text-slate-400 text-right">周涨幅</div>
          </div>
          <div className="divide-y divide-slate-700/30">
            {topSectors.map((sector) => (
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
                <div className="px-3 py-2.5 text-sm text-white text-right">{sector.score}</div>
                <div className={`px-3 py-2.5 text-sm text-right flex items-center justify-end gap-1 ${
                  sector.trend === 'up' ? 'text-red-400' : 'text-green-400'
                }`}>
                  {sector.trend === 'up' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                  {sector.change > 0 ? '+' : ''}{sector.change}%
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
