import { Search, TrendingUp, TrendingDown, Minus } from 'lucide-react';

interface FilterPanelProps {
  onSearchChange: (value: string) => void;
  onSentimentFilter: (sentiment: string) => void;
  onStockFilter: (stock: string) => void;
}

export function FilterPanel({ onSearchChange, onSentimentFilter }: FilterPanelProps) {
  return (
    <div className="space-y-3">
      {/* Stats Overview */}
      <div className="grid grid-cols-3 gap-2">
        <div className="p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-green-400">利好资讯</span>
            <TrendingUp className="w-3.5 h-3.5 text-green-400" />
          </div>
          <div className="text-xl text-green-400">45%</div>
          <div className="text-xs text-green-500/70 mt-0.5">较昨日 +3%</div>
        </div>

        <div className="p-3 bg-slate-700/30 border border-slate-600/30 rounded-lg">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-slate-400">中性资讯</span>
            <Minus className="w-3.5 h-3.5 text-slate-400" />
          </div>
          <div className="text-xl text-slate-300">30%</div>
          <div className="text-xs text-slate-500 mt-0.5">较昨日 -1%</div>
        </div>

        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-red-400">利空资讯</span>
            <TrendingDown className="w-3.5 h-3.5 text-red-400" />
          </div>
          <div className="text-xl text-red-400">25%</div>
          <div className="text-xs text-red-500/70 mt-0.5">较昨日 -2%</div>
        </div>
      </div>

      {/* Search Bar */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text"
          placeholder="搜索新闻、股票..."
          className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-slate-800/50 border border-slate-700/50 text-slate-200 placeholder:text-slate-500 focus:border-blue-500/50 focus:outline-none transition-colors text-sm"
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>

      {/* Sentiment Filters */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => onSentimentFilter('positive')}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/20 text-green-400 hover:bg-green-500/20 transition-colors text-xs"
        >
          <TrendingUp className="w-3.5 h-3.5" />
          利好
        </button>

        <button
          onClick={() => onSentimentFilter('negative')}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 hover:bg-red-500/20 transition-colors text-xs"
        >
          <TrendingDown className="w-3.5 h-3.5" />
          利空
        </button>

        <button
          onClick={() => onSentimentFilter('neutral')}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-slate-700/30 border border-slate-600/30 text-slate-400 hover:bg-slate-700/50 transition-colors text-xs"
        >
          <Minus className="w-3.5 h-3.5" />
          中性
        </button>
      </div>
    </div>
  );
}
