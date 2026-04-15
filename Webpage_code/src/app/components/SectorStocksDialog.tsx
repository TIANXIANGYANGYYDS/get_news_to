import { X, TrendingUp, TrendingDown } from 'lucide-react';
import { useState } from 'react';
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ComposedChart, Line, Area } from 'recharts';

// K线图组件（简化版）
const CandlestickChart = ({ data }: { data: Array<{ date: string; open: number; high: number; low: number; close: number }> }) => {
  // 将数据转换为包含涨跌信息的格式
  const chartData = data.map((item, index) => ({
    ...item,
    isRising: item.close >= item.open,
    prevClose: index > 0 ? data[index - 1].close : item.open
  }));

  // 计算合适的Y轴范围
  const allValues = chartData.flatMap(d => [d.high, d.low]);
  const minValue = Math.min(...allValues);
  const maxValue = Math.max(...allValues);
  const range = maxValue - minValue;
  const padding = range * 0.1; // 10%的边距

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
        <defs>
          <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.05}/>
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.2} />
        <XAxis
          dataKey="date"
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 9 }}
          tickLine={false}
          interval="preserveStartEnd"
          height={25}
        />
        <YAxis
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 9 }}
          tickLine={false}
          domain={[minValue - padding, maxValue + padding]}
          width={45}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#1e293b',
            border: '1px solid #475569',
            borderRadius: '8px',
            fontSize: '11px',
            padding: '8px'
          }}
          labelStyle={{ color: '#94a3b8', marginBottom: '4px' }}
          formatter={(value: any, name: string) => {
            const labels: Record<string, string> = {
              open: '开',
              high: '高',
              low: '低',
              close: '收'
            };
            return [typeof value === 'number' ? `¥${value.toFixed(2)}` : value, labels[name] || name];
          }}
        />
        {/* 高低价区域 */}
        <Area
          type="monotone"
          dataKey="high"
          stroke="none"
          fill="url(#areaGradient)"
          fillOpacity={0.1}
        />
        {/* 最高价线 */}
        <Line
          type="monotone"
          dataKey="high"
          stroke="#f87171"
          strokeWidth={1}
          dot={false}
          opacity={0.3}
        />
        {/* 最低价线 */}
        <Line
          type="monotone"
          dataKey="low"
          stroke="#4ade80"
          strokeWidth={1}
          dot={false}
          opacity={0.3}
        />
        {/* 收盘价线 */}
        <Line
          type="monotone"
          dataKey="close"
          stroke="#3b82f6"
          strokeWidth={2}
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
};

interface Stock {
  股票代码: string;
  股票名称: string;
  交易日期: string;
  开盘价: number;
  最高价: number;
  最低价: number;
  收盘价: number;
  涨跌额: number;
  '涨跌幅(%)': number;
  '振幅(%)': number;
  '成交额(元)': number;
  '换手率(%)': number;
  analysis: string;
  recommendation: 'buy' | 'hold' | 'sell';
  历史数据?: Array<{
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
  }>;
}

interface SectorStocksDialogProps {
  isOpen: boolean;
  onClose: () => void;
  sectorName: string;
}

export function SectorStocksDialog({ isOpen, onClose, sectorName }: SectorStocksDialogProps) {
  const [currentIndex, setCurrentIndex] = useState(0);

  // 生成K线历史数据
  const generateKlineData = (basePrice: number, days: number = 30) => {
    const data = [];
    let price = basePrice * 0.85; // 从较低价格开始
    for (let i = days; i >= 0; i--) {
      const date = new Date();
      date.setDate(date.getDate() - i);
      const change = (Math.random() - 0.48) * price * 0.05;
      const open = price;
      const close = price + change;
      const high = Math.max(open, close) * (1 + Math.random() * 0.03);
      const low = Math.min(open, close) * (1 - Math.random() * 0.03);
      data.push({
        date: date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }),
        open,
        high,
        low,
        close
      });
      price = close;
    }
    return data;
  };

  // 模拟数据：每个板块的前20只股票
  const mockStocks: Record<string, Stock[]> = {
    '油气开采及服务': [
      {
        股票代码: '600028',
        股票名称: '中国石化',
        交易日期: '2026-04-14',
        开盘价: 6.50,
        最高价: 6.89,
        最低价: 6.45,
        收盘价: 6.78,
        涨跌额: 0.45,
        '涨跌幅(%)': 7.11,
        '振幅(%)': 6.76,
        '成交额(元)': 1590000000,
        '换手率(%)': 3.21,
        recommendation: 'buy',
        analysis: '公司为国内最大的炼化一体化企业，受益于油价上涨和炼化利润扩张。当前PE处于历史低位，估值安全边际高。地缘冲突推升原油价格，公司上游开采业务盈利能力显著增强，建议积极关注。',
        历史数据: generateKlineData(6.78)
      },
      ...Array.from({ length: 19 }, (_, i) => {
        const stockData = [
          { code: '600157', name: '永泰能源', price: 2.34, changePercent: 9.86, rec: 'buy' as const, analysis: '公司煤炭资源储量丰富，受益于能源安全主线。近期煤价上涨趋势明显，公司盈利能力持续改善。技术面看，股价突破前期平台，资金流入明显，短期有望继续走强。' },
          { code: '600688', name: '上海石化', price: 4.12, changePercent: 8.42, rec: 'buy' as const, analysis: '作为中石化旗下炼化企业，公司受益于油价上涨和炼化价差扩大。一季度业绩预告超预期，净利润同比增长超80%。当前估值合理，建议逢低布局。' },
          { code: '601857', name: '中国石油', price: 8.56, changePercent: 7.27, rec: 'buy' as const, analysis: '公司为国内最大的油气生产商，油价上涨直接增厚业绩。上游勘探开采业务盈利能力强，中游管道运输稳定贡献现金流。PB低于1，股息率超5%，配置价值凸显。' },
          { code: '002207', name: '准油股份', price: 12.89, changePercent: 9.98, rec: 'hold' as const, analysis: '公司主营油田技术服务，受益于油价上涨带来的上游开采投资增加。近期订单量明显提升，但估值已处于历史高位，建议等待回调后再行介入。' },
          { code: '600339', name: '中油工程', price: 5.67, changePercent: 10.10, rec: 'buy' as const, analysis: '公司承接大量油气工程项目，在手订单充足。受益于国内油气勘探开发力度加大，业绩增长确定性强。昨日涨停封板坚决，资金认可度高。' },
          { code: '600387', name: '海越能源', price: 8.23, changePercent: 10.03, rec: 'hold' as const, analysis: '公司从事石油化工产品生产销售，短期受益于油价上涨预期。但公司基本面一般，主要靠题材炒作，追高风险较大，建议观望为主。' },
          { code: '000096', name: '广聚能源', price: 7.45, changePercent: 10.05, rec: 'hold' as const, analysis: '公司主营成品油零售业务，受益于油价上涨预期。但下游零售环节议价能力有限，利润弹性不如上游开采企业。短线可参与，中线持谨慎态度。' },
          { code: '603727', name: '博迈科', price: 15.34, changePercent: 9.96, rec: 'hold' as const, analysis: '公司专注海洋油气模块建造，受益于海上油气开发投资增加。在手订单饱满，但估值偏高，性价比一般，建议等待调整机会。' },
          { code: '002353', name: '杰瑞股份', price: 32.56, changePercent: 10.00, rec: 'hold' as const, analysis: '公司为油服设备龙头，受益于油气开采投资景气度提升。技术实力强，市场份额稳定，但当前估值较高，追涨风险较大。' },
          { code: '600583', name: '海油工程', price: 6.89, changePercent: 10.08, rec: 'buy' as const, analysis: '公司为海洋石油工程龙头，受益于海上油气田开发提速。中海油资本开支增加直接利好公司订单。估值合理，业绩增长确定性强。' },
          { code: '300084', name: '海默科技', price: 4.78, changePercent: 9.89, rec: 'sell' as const, analysis: '公司主营油气开采设备，概念纯正但基本面较弱。近期涨幅过大，估值严重透支，追高风险极大，建议逢高减仓。' },
          { code: '002554', name: '惠博普', price: 3.56, changePercent: 9.88, rec: 'sell' as const, analysis: '公司主营油田技术服务，短期跟随板块炒作。但公司财务状况一般，盈利能力弱，主要靠题材支撑，不建议追高。' },
          { code: '600968', name: '海油发展', price: 3.89, changePercent: 9.89, rec: 'buy' as const, analysis: '公司为中海油旗下综合服务企业，业务涵盖钻井、油田服务等多个领域。受益于中海油资本开支增加，业绩增长稳健，估值合理。' },
          { code: '300164', name: '通源石油', price: 5.23, changePercent: 10.11, rec: 'hold' as const, analysis: '公司从事油田技术服务，受益于上游开采景气度提升。但公司规模较小，抗风险能力弱，建议轻仓参与。' },
          { code: '002490', name: '山东墨龙', price: 4.67, changePercent: 9.88, rec: 'hold' as const, analysis: '公司主营石油钻采设备，受益于油气开采投资增加。但公司业绩波动较大，估值偏高，谨慎参与。' },
          { code: '600815', name: '鲁银投资', price: 6.12, changePercent: 10.07, rec: 'hold' as const, analysis: '公司参股油气资产，间接受益于油价上涨。但参股比例较小，弹性有限，主要跟随板块情绪波动。' },
          { code: '600759', name: '洲际油气', price: 2.89, changePercent: 9.89, rec: 'sell' as const, analysis: '公司拥有海外油气资产，概念纯正。但公司长期亏损，基本面较差，主要靠题材炒作，风险较大。' },
          { code: '603619', name: '中曼石油', price: 8.45, changePercent: 10.03, rec: 'hold' as const, analysis: '公司从事油气勘探开发服务，受益于行业景气度提升。但估值偏高，业绩不确定性较大，建议观望。' },
          { code: '002828', name: '贝肯能源', price: 7.23, changePercent: 10.05, rec: 'sell' as const, analysis: '公司主营油田技术服务，短期受益于板块炒作。但公司基本面一般，估值过高，不建议追高，逢高减仓为宜。' }
        ][i];

        const changeAmount = stockData.price * (stockData.changePercent / 100);
        const openPrice = stockData.price - changeAmount * 0.3;
        const amplitude = Math.abs(stockData.changePercent) * 1.5;

        return {
          股票代码: stockData.code,
          股票名称: stockData.name,
          交易日期: '2026-04-14',
          开盘价: parseFloat(openPrice.toFixed(2)),
          最高价: parseFloat((stockData.price * (1 + Math.random() * 0.02)).toFixed(2)),
          最低价: parseFloat((openPrice * (1 - Math.random() * 0.02)).toFixed(2)),
          收盘价: stockData.price,
          涨跌额: parseFloat(changeAmount.toFixed(2)),
          '涨跌幅(%)': stockData.changePercent,
          '振幅(%)': parseFloat(amplitude.toFixed(2)),
          '成交额(元)': Math.floor((500000000 + Math.random() * 2000000000)),
          '换手率(%)': parseFloat((2 + Math.random() * 8).toFixed(2)),
          recommendation: stockData.rec,
          analysis: stockData.analysis,
          历史数据: generateKlineData(stockData.price)
        };
      })
    ],
    '养殖业': Array.from({ length: 20 }, (_, i) => {
      const price = 10 + Math.random() * 20;
      const changePercent = -5 + Math.random() * 15;
      const changeAmount = price * (changePercent / 100);
      return {
        股票代码: `60${String(i + 1).padStart(4, '0')}`,
        股票名称: `养殖股${i + 1}`,
        交易日期: '2026-04-14',
        开盘价: parseFloat((price - changeAmount * 0.3).toFixed(2)),
        最高价: parseFloat((price * (1 + Math.random() * 0.02)).toFixed(2)),
        最低价: parseFloat((price * (1 - Math.random() * 0.03)).toFixed(2)),
        收盘价: parseFloat(price.toFixed(2)),
        涨跌额: parseFloat(changeAmount.toFixed(2)),
        '涨跌幅(%)': parseFloat(changePercent.toFixed(2)),
        '振幅(%)': parseFloat((Math.abs(changePercent) * 1.5).toFixed(2)),
        '成交额(元)': Math.floor(500000000 + Math.random() * 2000000000),
        '换手率(%)': parseFloat((2 + Math.random() * 8).toFixed(2)),
        recommendation: ['buy', 'hold', 'sell'][Math.floor(Math.random() * 3)] as 'buy' | 'hold' | 'sell',
        analysis: '该股票在养殖业板块中表现稳健，受生猪价格波动影响。公司养殖规模持续扩大，成本控制能力较强。当前猪价处于上行周期，公司盈利能力有望持续改善。建议关注季度出栏量数据。',
        历史数据: generateKlineData(price)
      };
    }),
    '石油加工贸易': Array.from({ length: 20 }, (_, i) => {
      const price = 8 + Math.random() * 15;
      const changePercent = -3 + Math.random() * 10;
      const changeAmount = price * (changePercent / 100);
      return {
        股票代码: `60${String(i + 100).padStart(4, '0')}`,
        股票名称: `石化股${i + 1}`,
        交易日期: '2026-04-14',
        开盘价: parseFloat((price - changeAmount * 0.3).toFixed(2)),
        最高价: parseFloat((price * (1 + Math.random() * 0.02)).toFixed(2)),
        最低价: parseFloat((price * (1 - Math.random() * 0.03)).toFixed(2)),
        收盘价: parseFloat(price.toFixed(2)),
        涨跌额: parseFloat(changeAmount.toFixed(2)),
        '涨跌幅(%)': parseFloat(changePercent.toFixed(2)),
        '振幅(%)': parseFloat((Math.abs(changePercent) * 1.5).toFixed(2)),
        '成交额(元)': Math.floor(400000000 + Math.random() * 1500000000),
        '换手率(%)': parseFloat((1.5 + Math.random() * 6).toFixed(2)),
        recommendation: ['buy', 'hold', 'sell'][Math.floor(Math.random() * 3)] as 'buy' | 'hold' | 'sell',
        analysis: '公司为石油化工下游企业，受益于原油价格上涨带来的成品油价格提升。炼化价差扩大有利于改善盈利。但需关注环保政策和产能过剩风险。',
        历史数据: generateKlineData(price)
      };
    }),
    '生物制品': Array.from({ length: 20 }, (_, i) => {
      const price = 25 + Math.random() * 50;
      const changePercent = -4 + Math.random() * 12;
      const changeAmount = price * (changePercent / 100);
      return {
        股票代码: `30${String(i + 1).padStart(4, '0')}`,
        股票名称: `生物股${i + 1}`,
        交易日期: '2026-04-14',
        开盘价: parseFloat((price - changeAmount * 0.3).toFixed(2)),
        最高价: parseFloat((price * (1 + Math.random() * 0.02)).toFixed(2)),
        最低价: parseFloat((price * (1 - Math.random() * 0.03)).toFixed(2)),
        收盘价: parseFloat(price.toFixed(2)),
        涨跌额: parseFloat(changeAmount.toFixed(2)),
        '涨跌幅(%)': parseFloat(changePercent.toFixed(2)),
        '振幅(%)': parseFloat((Math.abs(changePercent) * 1.5).toFixed(2)),
        '成交额(元)': Math.floor(800000000 + Math.random() * 3000000000),
        '换手率(%)': parseFloat((2 + Math.random() * 7).toFixed(2)),
        recommendation: ['buy', 'hold', 'sell'][Math.floor(Math.random() * 3)] as 'buy' | 'hold' | 'sell',
        analysis: '公司专注创新药研发，产品管线丰富。受益于人口老龄化和医保支付能力提升，长期成长空间广阔。需关注研发进展和药品集采影响。',
        历史数据: generateKlineData(price)
      };
    }),
    '工业金属': Array.from({ length: 20 }, (_, i) => {
      const price = 6 + Math.random() * 12;
      const changePercent = -5 + Math.random() * 8;
      const changeAmount = price * (changePercent / 100);
      return {
        股票代码: `60${String(i + 200).padStart(4, '0')}`,
        股票名称: `金属股${i + 1}`,
        交易日期: '2026-04-14',
        开盘价: parseFloat((price - changeAmount * 0.3).toFixed(2)),
        最高价: parseFloat((price * (1 + Math.random() * 0.02)).toFixed(2)),
        最低价: parseFloat((price * (1 - Math.random() * 0.03)).toFixed(2)),
        收盘价: parseFloat(price.toFixed(2)),
        涨跌额: parseFloat(changeAmount.toFixed(2)),
        '涨跌幅(%)': parseFloat(changePercent.toFixed(2)),
        '振幅(%)': parseFloat((Math.abs(changePercent) * 1.5).toFixed(2)),
        '成交额(元)': Math.floor(600000000 + Math.random() * 1800000000),
        '换手率(%)': parseFloat((2.5 + Math.random() * 7).toFixed(2)),
        recommendation: ['buy', 'hold', 'sell'][Math.floor(Math.random() * 3)] as 'buy' | 'hold' | 'sell',
        analysis: '公司主营有色金属冶炼加工，受全球大宗商品价格影响较大。当前金属价格处于周期底部，公司成本优势明显。关注海外需求复苏情况。',
        历史数据: generateKlineData(price)
      };
    })
  };

  const stocks = mockStocks[sectorName] || [];
  const currentStock = stocks[currentIndex];

  const getRecommendationStyle = (recommendation: string) => {
    switch (recommendation) {
      case 'buy':
        return {
          bg: 'bg-red-500/10 border-red-500/30',
          text: 'text-red-400',
          label: '买入'
        };
      case 'hold':
        return {
          bg: 'bg-yellow-500/10 border-yellow-500/30',
          text: 'text-yellow-400',
          label: '观望'
        };
      default:
        return {
          bg: 'bg-green-500/10 border-green-500/30',
          text: 'text-green-400',
          label: '卖出'
        };
    }
  };

  if (!isOpen || !currentStock) return null;

  const recStyle = getRecommendationStyle(currentStock.recommendation);
  const isPositive = currentStock.涨跌额 >= 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-[1400px] max-h-[90vh] bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-gradient-to-r from-slate-800/50 to-slate-900/50 flex-shrink-0">
          <div>
            <h2 className="text-lg text-white mb-0.5">{sectorName} - 个股分析</h2>
            <p className="text-xs text-slate-400">共 {stocks.length} 只股票 · {currentStock.交易日期}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="grid grid-cols-3 gap-4 mb-3 items-start">
            {/* Left: Stock Info */}
            <div className="flex flex-col">
              {/* Stock Header */}
              <div className="mb-2">
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="text-xl text-white">{currentStock.股票名称}</h3>
                  <span className="text-sm text-slate-500">{currentStock.股票代码}</span>
                  <div className={`px-2 py-0.5 rounded border ${recStyle.bg}`}>
                    <span className={`text-xs ${recStyle.text}`}>{recStyle.label}</span>
                  </div>
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl text-white">¥{currentStock.收盘价.toFixed(2)}</span>
                  <div className={`flex items-center gap-1 ${isPositive ? 'text-red-400' : 'text-green-400'}`}>
                    {isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                    <span className="text-lg">{isPositive ? '+' : ''}{currentStock.涨跌额.toFixed(2)}</span>
                    <span className="text-sm">({isPositive ? '+' : ''}{currentStock['涨跌幅(%)'].toFixed(2)}%)</span>
                  </div>
                </div>
              </div>

              {/* Stats Grid */}
              <div className="grid grid-cols-2 gap-2">
                <div className="px-2 py-1.5 bg-slate-800/30 border border-slate-700/50 rounded">
                  <div className="text-xs text-slate-500 mb-0.5">开盘</div>
                  <div className="text-sm text-white">¥{currentStock.开盘价.toFixed(2)}</div>
                </div>
                <div className="px-2 py-1.5 bg-slate-800/30 border border-slate-700/50 rounded">
                  <div className="text-xs text-slate-500 mb-0.5">最高</div>
                  <div className="text-sm text-red-400">¥{currentStock.最高价.toFixed(2)}</div>
                </div>
                <div className="px-2 py-1.5 bg-slate-800/30 border border-slate-700/50 rounded">
                  <div className="text-xs text-slate-500 mb-0.5">最低</div>
                  <div className="text-sm text-green-400">¥{currentStock.最低价.toFixed(2)}</div>
                </div>
                <div className="px-2 py-1.5 bg-slate-800/30 border border-slate-700/50 rounded">
                  <div className="text-xs text-slate-500 mb-0.5">振幅</div>
                  <div className="text-sm text-white">{currentStock['振幅(%)'].toFixed(2)}%</div>
                </div>
                <div className="px-2 py-1.5 bg-slate-800/30 border border-slate-700/50 rounded">
                  <div className="text-xs text-slate-500 mb-0.5">成交额</div>
                  <div className="text-sm text-white">{(currentStock['成交额(元)'] / 100000000).toFixed(2)}亿</div>
                </div>
                <div className="px-2 py-1.5 bg-slate-800/30 border border-slate-700/50 rounded">
                  <div className="text-xs text-slate-500 mb-0.5">换手率</div>
                  <div className="text-sm text-white">{currentStock['换手率(%)'].toFixed(2)}%</div>
                </div>
              </div>
            </div>

            {/* Right: Candlestick Chart */}
            <div className="col-span-2 bg-slate-800/30 border border-slate-700/50 rounded-xl p-3 h-[240px] flex flex-col overflow-hidden">
              <h4 className="text-xs text-slate-400 mb-2">K线走势 (30天)</h4>
              <div className="flex-1 overflow-hidden">
                <CandlestickChart data={currentStock.历史数据 || []} />
              </div>
            </div>
          </div>

          {/* Analysis - Larger Section */}
          <div className="p-5 bg-gradient-to-br from-blue-500/10 to-indigo-500/10 border border-blue-500/30 rounded-xl">
            <h4 className="text-base text-blue-400 mb-3 flex items-center gap-2">
              <span>📊</span>
              <span>个股分析</span>
            </h4>
            <p className="text-base text-slate-300 leading-relaxed">
              {currentStock.analysis}
            </p>
          </div>
        </div>

        {/* Footer Stock List */}
        <div className="border-t border-slate-800 bg-slate-900/80 flex-shrink-0">
          <div className="px-4 py-2">
            <div className="flex items-center gap-1.5 overflow-x-auto scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-800">
              {stocks.map((stock, index) => {
                const stockIsPositive = stock.涨跌额 >= 0;
                return (
                  <button
                    key={stock.股票代码}
                    onClick={() => setCurrentIndex(index)}
                    className={`flex-shrink-0 px-2.5 py-1.5 rounded border transition-all ${
                      currentIndex === index
                        ? 'bg-blue-500/20 border-blue-500/50 text-white'
                        : 'bg-slate-800/50 border-slate-700/50 text-slate-400 hover:bg-slate-800 hover:text-slate-300'
                    }`}
                  >
                    <div className="text-xs font-medium mb-0.5">{stock.股票名称}</div>
                    <div className={`text-xs ${stockIsPositive ? 'text-red-400' : 'text-green-400'}`}>
                      {stockIsPositive ? '+' : ''}{stock['涨跌幅(%)'].toFixed(2)}%
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
