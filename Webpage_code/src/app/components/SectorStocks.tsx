import { TrendingUp, TrendingDown, Activity, Target, Zap } from 'lucide-react';
import { StockChart } from './StockChart';

interface SectorStocksProps {
  sectorName: string;
}

export function SectorStocks({ sectorName }: SectorStocksProps) {
  // Mock data for top 5 stocks in the sector
  const sectorStockData: Record<string, Array<{
    code: string;
    name: string;
    price: number;
    change: number;
    recommendation: string;
    level: 'strong' | 'moderate' | 'hold';
    reason: string;
  }>> = {
    '新能源汽车': [
      { code: 'SZ002594', name: '比亚迪', price: 256.88, change: 3.2, recommendation: '强烈推荐', level: 'strong', reason: '销量持续增长，新车型受市场欢迎' },
      { code: 'SZ300750', name: '宁德时代', price: 198.45, change: 2.8, recommendation: '强烈推荐', level: 'strong', reason: '电池技术领先，订单充足' },
      { code: 'SH688981', name: '中芯国际', price: 145.67, change: 1.9, recommendation: '推荐', level: 'moderate', reason: '芯片需求旺盛，业绩稳定增长' },
      { code: 'SZ002920', name: '德赛西威', price: 89.34, change: 1.5, recommendation: '推荐', level: 'moderate', reason: '智能座舱业务快速发展' },
      { code: 'SH603501', name: '韦尔股份', price: 67.23, change: 0.8, recommendation: '持有', level: 'hold', reason: '市场竞争加剧，关注业绩兑现' }
    ],
    '新能源': [
      { code: 'SZ002594', name: '比亚迪', price: 256.88, change: 3.2, recommendation: '强烈推荐', level: 'strong', reason: '销量持续增长，新车型受市场欢迎' },
      { code: 'SZ300750', name: '宁德时代', price: 198.45, change: 2.8, recommendation: '强烈推荐', level: 'strong', reason: '电池技术领先，订单充足' },
      { code: 'SZ300274', name: '阳光电源', price: 123.45, change: 2.3, recommendation: '推荐', level: 'moderate', reason: '光伏逆变器龙头企业' },
      { code: 'SH601012', name: '隆基绿能', price: 34.56, change: 1.8, recommendation: '推荐', level: 'moderate', reason: '光伏组件需求旺盛' },
      { code: 'SZ002812', name: '恩捷股份', price: 78.90, change: 1.2, recommendation: '持有', level: 'hold', reason: '锂电池隔膜市场领先' }
    ],
    '医药生物': [
      { code: 'SH600276', name: '恒瑞医药', price: 156.78, change: 2.5, recommendation: '强烈推荐', level: 'strong', reason: '创新药管线丰富，研发实力强' },
      { code: 'SH603259', name: '药明康德', price: 134.56, change: 2.1, recommendation: '强烈推荐', level: 'strong', reason: 'CDMO业务订单饱满' },
      { code: 'SZ300760', name: '迈瑞医疗', price: 298.34, change: 1.8, recommendation: '推荐', level: 'moderate', reason: '医疗器械龙头，出口业务增长' },
      { code: 'SH688180', name: '君实生物', price: 78.45, change: 1.4, recommendation: '推荐', level: 'moderate', reason: '创新药研发进展顺利' },
      { code: 'SZ300122', name: '智飞生物', price: 89.67, change: 0.9, recommendation: '持有', level: 'hold', reason: '疫苗业务稳定，关注新品推出' }
    ],
    '科技板块': [
      { code: 'SZ000063', name: '中兴通讯', price: 34.56, change: 2.8, recommendation: '强烈推荐', level: 'strong', reason: '5G建设持续推进，订单饱满' },
      { code: 'SZ002415', name: '海康威视', price: 45.67, change: 2.3, recommendation: '强烈推荐', level: 'strong', reason: '安防龙头，智能化转型顺利' },
      { code: 'SH600588', name: '用友网络', price: 23.45, change: 1.9, recommendation: '推荐', level: 'moderate', reason: '云服务转型成效显著' },
      { code: 'SZ002230', name: '科大讯飞', price: 56.78, change: 1.5, recommendation: '推荐', level: 'moderate', reason: 'AI技术应用前景广阔' },
      { code: 'SZ300059', name: '东方财富', price: 18.90, change: 1.1, recommendation: '持有', level: 'hold', reason: '互联网券商业务稳定' }
    ],
    '科技创新': [
      { code: 'SZ000063', name: '中兴通讯', price: 34.56, change: 2.8, recommendation: '强烈推荐', level: 'strong', reason: '5G建设持续推进，订单饱满' },
      { code: 'SZ002230', name: '科大讯飞', price: 56.78, change: 2.5, recommendation: '强烈推荐', level: 'strong', reason: 'AI技术应用前景广阔' },
      { code: 'SH688981', name: '中芯国际', price: 167.89, change: 2.1, recommendation: '推荐', level: 'moderate', reason: '国产替代加速，长期看好' },
      { code: 'SH688012', name: '中微公司', price: 234.56, change: 1.8, recommendation: '推荐', level: 'moderate', reason: '设备国产化受益标的' },
      { code: 'SZ300750', name: '宁德时代', price: 198.45, change: 1.4, recommendation: '持有', level: 'hold', reason: '电池技术创新领先' }
    ],
    '消费板块': [
      { code: 'SH600519', name: '贵州茅台', price: 1789.45, change: 1.8, recommendation: '强烈推荐', level: 'strong', reason: '高端白酒龙头，业绩确定性强' },
      { code: 'SZ000858', name: '五粮液', price: 178.34, change: 1.5, recommendation: '推荐', level: 'moderate', reason: '品牌价值高，渠道改革成效显现' },
      { code: 'SH600887', name: '伊利股份', price: 34.78, change: 1.2, recommendation: '推荐', level: 'moderate', reason: '乳制品龙头，业绩稳健' },
      { code: 'SZ002714', name: '牧原股份', price: 56.78, change: 0.9, recommendation: '持有', level: 'hold', reason: '生猪养殖规模优势明显' },
      { code: 'SZ000333', name: '美的集团', price: 67.89, change: 0.7, recommendation: '持有', level: 'hold', reason: '家电龙头，出口业务增长' }
    ],
    '消费升级': [
      { code: 'SH600519', name: '贵州茅台', price: 1789.45, change: 1.8, recommendation: '强烈推荐', level: 'strong', reason: '高端白酒龙头，业绩确定性强' },
      { code: 'SZ000858', name: '五粮液', price: 178.34, change: 1.5, recommendation: '推荐', level: 'moderate', reason: '品牌价值高，渠道改革成效显现' },
      { code: 'SZ000568', name: '泸州老窖', price: 189.56, change: 1.2, recommendation: '推荐', level: 'moderate', reason: '次高端白酒受益消费升级' },
      { code: 'SZ002304', name: '洋河股份', price: 112.34, change: 0.8, recommendation: '持有', level: 'hold', reason: '渠道调整中，关注改革进展' },
      { code: 'SZ000333', name: '美的集团', price: 67.89, change: 0.5, recommendation: '持有', level: 'hold', reason: '家电龙头，出口业务增长' }
    ],
    '金融板块': [
      { code: 'SH601318', name: '中国平安', price: 45.67, change: 1.5, recommendation: '强烈推荐', level: 'strong', reason: '综合金融龙头，估值修复' },
      { code: 'SH600036', name: '招商银行', price: 34.56, change: 1.3, recommendation: '推荐', level: 'moderate', reason: '零售银行龙头，资产质量优' },
      { code: 'SH601166', name: '兴业银行', price: 18.90, change: 1.1, recommendation: '推荐', level: 'moderate', reason: '同业业务领先' },
      { code: 'SH600030', name: '中信证券', price: 23.45, change: 0.9, recommendation: '持有', level: 'hold', reason: '券商龙头，业务多元化' },
      { code: 'SH601628', name: '中国人寿', price: 34.67, change: 0.7, recommendation: '持有', level: 'hold', reason: '保险龙头，长期价值显著' }
    ],
    '金融科技': [
      { code: 'SZ300059', name: '东方财富', price: 18.90, change: 2.3, recommendation: '强烈推荐', level: 'strong', reason: '互联网券商业务快速增长' },
      { code: 'SZ002230', name: '科大讯飞', price: 56.78, change: 2.1, recommendation: '推荐', level: 'moderate', reason: 'AI赋能金融科技' },
      { code: 'SH600588', name: '用友网络', price: 23.45, change: 1.8, recommendation: '推荐', level: 'moderate', reason: '云服务转型成效显著' },
      { code: 'SZ002410', name: '广联达', price: 45.67, change: 1.4, recommendation: '持有', level: 'hold', reason: '建筑信息化龙头' },
      { code: 'SZ300142', name: '沃森生物', price: 34.56, change: 1.0, recommendation: '持有', level: 'hold', reason: '疫苗研发持续投入' }
    ],
    '军工板块': [
      { code: 'SH600893', name: '航发动力', price: 45.67, change: 1.8, recommendation: '强烈推荐', level: 'strong', reason: '航空发动机唯一平台' },
      { code: 'SZ002049', name: '紫光国微', price: 178.90, change: 1.5, recommendation: '推荐', level: 'moderate', reason: '军用芯片核心供应商' },
      { code: 'SH600760', name: '中航沈飞', price: 56.78, change: 1.2, recommendation: '推荐', level: 'moderate', reason: '战斗机总装龙头' },
      { code: 'SH601989', name: '中国重工', price: 5.67, change: 0.8, recommendation: '持有', level: 'hold', reason: '船舶制造平台型企业' },
      { code: 'SZ000768', name: '中航西飞', price: 34.56, change: 0.5, recommendation: '持有', level: 'hold', reason: '大型运输机制造商' }
    ],
    '国防军工': [
      { code: 'SH600893', name: '航发动力', price: 45.67, change: -0.8, recommendation: '推荐', level: 'moderate', reason: '航空发动机唯一平台，短期调整' },
      { code: 'SZ002049', name: '紫光国微', price: 178.90, change: -1.2, recommendation: '推荐', level: 'moderate', reason: '军用芯片核心供应商' },
      { code: 'SH600760', name: '中航沈飞', price: 56.78, change: -0.5, recommendation: '持有', level: 'hold', reason: '战斗机总装龙头，等待订单兑现' },
      { code: 'SH601989', name: '中国重工', price: 5.67, change: -0.3, recommendation: '持有', level: 'hold', reason: '船舶制造平台型企业' },
      { code: 'SZ000768', name: '中航西飞', price: 34.56, change: -0.2, recommendation: '持有', level: 'hold', reason: '大型运输机制造商' }
    ],
    '地产板块': [
      { code: 'SZ000002', name: '万科A', price: 12.34, change: 1.5, recommendation: '推荐', level: 'moderate', reason: '地产龙头，政策回暖受益' },
      { code: 'SH600048', name: '保利发展', price: 15.67, change: 1.3, recommendation: '推荐', level: 'moderate', reason: '央企地产，业绩稳健' },
      { code: 'SZ001979', name: '招商蛇口', price: 11.23, change: 1.1, recommendation: '持有', level: 'hold', reason: '区位优势明显' },
      { code: 'SH600606', name: '绿地控股', price: 3.45, change: 0.8, recommendation: '持有', level: 'hold', reason: '债务压力较大，关注改善' },
      { code: 'SZ000736', name: '中交地产', price: 8.90, change: 0.5, recommendation: '持有', level: 'hold', reason: '央企背景，稳健经营' }
    ],
    '房地产': [
      { code: 'SZ000002', name: '万科A', price: 12.34, change: 1.5, recommendation: '推荐', level: 'moderate', reason: '地产龙头，政策回暖受益' },
      { code: 'SH600048', name: '保利发展', price: 15.67, change: 1.3, recommendation: '推荐', level: 'moderate', reason: '央企地产，业绩稳健' },
      { code: 'SZ001979', name: '招商蛇口', price: 11.23, change: 1.1, recommendation: '持有', level: 'hold', reason: '区位优势明显' },
      { code: 'SH600606', name: '绿地控股', price: 3.45, change: 0.8, recommendation: '持有', level: 'hold', reason: '债务压力较大，关注改善' },
      { code: 'SZ000736', name: '中交地产', price: 8.90, change: 0.5, recommendation: '持有', level: 'hold', reason: '央企背景，稳健经营' }
    ],
    '有色金属': [
      { code: 'SH601899', name: '紫金矿业', price: 14.56, change: 1.8, recommendation: '强烈推荐', level: 'strong', reason: '黄金铜矿双龙头，资源储量丰富' },
      { code: 'SZ002460', name: '赣锋锂业', price: 45.67, change: 1.5, recommendation: '推荐', level: 'moderate', reason: '锂资源储量丰富' },
      { code: 'SH600111', name: '北方稀土', price: 23.45, change: 1.2, recommendation: '推荐', level: 'moderate', reason: '稀土资源垄断优势' },
      { code: 'SH601600', name: '中国铝业', price: 5.67, change: 0.8, recommendation: '持有', level: 'hold', reason: '铝价波动影响业绩' },
      { code: 'SZ000878', name: '云南铜业', price: 12.34, change: 0.5, recommendation: '持有', level: 'hold', reason: '铜资源受益标的' }
    ],
    '新材料': [
      { code: 'SH600219', name: '南山铝业', price: 4.56, change: -0.5, recommendation: '推荐', level: 'moderate', reason: '铝材料龙头，长期成长性好' },
      { code: 'SZ002812', name: '恩捷股份', price: 78.90, change: -0.8, recommendation: '推荐', level: 'moderate', reason: '锂电池隔膜市场领先' },
      { code: 'SH603799', name: '华友钴业', price: 34.56, change: -1.2, recommendation: '持有', level: 'hold', reason: '钴资源价格波动影响' },
      { code: 'SZ002709', name: '天赐材料', price: 23.45, change: -0.7, recommendation: '持有', level: 'hold', reason: '电解液龙头企业' },
      { code: 'SH600673', name: '东阳光', price: 12.34, change: -0.3, recommendation: '持有', level: 'hold', reason: '铝箔业务稳定' }
    ],
    '农业板块': [
      { code: 'SZ002714', name: '牧原股份', price: 56.78, change: 1.5, recommendation: '强烈推荐', level: 'strong', reason: '生猪养殖规模优势明显' },
      { code: 'SZ000876', name: '新希望', price: 18.90, change: 1.2, recommendation: '推荐', level: 'moderate', reason: '饲料+养殖双主业' },
      { code: 'SZ002157', name: '正邦科技', price: 12.34, change: 1.0, recommendation: '推荐', level: 'moderate', reason: '养殖规模快速扩张' },
      { code: 'SZ002311', name: '海大集团', price: 45.67, change: 0.8, recommendation: '持有', level: 'hold', reason: '饲料行业龙头' },
      { code: 'SH600598', name: '北大荒', price: 15.67, change: 0.5, recommendation: '持有', level: 'hold', reason: '土地资源价值突出' }
    ],
    '农业科技': [
      { code: 'SZ002714', name: '牧原股份', price: 56.78, change: 1.2, recommendation: '推荐', level: 'moderate', reason: '智能化养殖技术领先' },
      { code: 'SZ002041', name: '登海种业', price: 23.45, change: 1.0, recommendation: '推荐', level: 'moderate', reason: '种业科技创新能力强' },
      { code: 'SZ000998', name: '隆平高科', price: 18.90, change: 0.8, recommendation: '持有', level: 'hold', reason: '种业龙头，转型中' },
      { code: 'SZ002311', name: '海大集团', price: 45.67, change: 0.7, recommendation: '持有', level: 'hold', reason: '饲料行业龙头' },
      { code: 'SZ300087', name: '荃银高科', price: 12.34, change: 0.5, recommendation: '持有', level: 'hold', reason: '种业科技企业' }
    ],
    '传媒板块': [
      { code: 'SZ300027', name: '华谊兄弟', price: 3.45, change: -0.3, recommendation: '持有', level: 'hold', reason: '影视行业复苏缓慢' },
      { code: 'SZ300104', name: '乐视网', price: 1.23, change: -0.5, recommendation: '持有', level: 'hold', reason: '业务转型中' },
      { code: 'SH601999', name: '出版传媒', price: 8.90, change: -0.2, recommendation: '持有', level: 'hold', reason: '传统出版业务稳定' },
      { code: 'SZ002343', name: '慈文传媒', price: 5.67, change: -0.1, recommendation: '持有', level: 'hold', reason: '内容制作业务调整' },
      { code: 'SZ300251', name: '光线传媒', price: 9.45, change: 0.1, recommendation: '持有', level: 'hold', reason: '动画电影业务亮眼' }
    ],
    '文化传媒': [
      { code: 'SZ300027', name: '华谊兄弟', price: 3.45, change: -0.3, recommendation: '持有', level: 'hold', reason: '影视行业复苏缓慢' },
      { code: 'SZ300251', name: '光线传媒', price: 9.45, change: -0.2, recommendation: '持有', level: 'hold', reason: '动画电影业务亮眼' },
      { code: 'SH601999', name: '出版传媒', price: 8.90, change: -0.1, recommendation: '持有', level: 'hold', reason: '传统出版业务稳定' },
      { code: 'SZ002343', name: '慈文传媒', price: 5.67, change: 0.1, recommendation: '持有', level: 'hold', reason: '内容制作业务调整' },
      { code: 'SZ300413', name: '芒果超媒', price: 23.45, change: 0.3, recommendation: '持有', level: 'hold', reason: '新媒体平台运营稳定' }
    ]
  };

  const stocks = sectorStockData[sectorName] || sectorStockData['科技板块'];

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'strong': return 'text-red-400 bg-red-500/10 border-red-500/30';
      case 'moderate': return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30';
      default: return 'text-slate-400 bg-slate-700/30 border-slate-600/30';
    }
  };

  const getLevelIcon = (level: string) => {
    switch (level) {
      case 'strong': return <Zap className="w-3.5 h-3.5" />;
      case 'moderate': return <Target className="w-3.5 h-3.5" />;
      default: return <Activity className="w-3.5 h-3.5" />;
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between px-1">
        <h3 className="text-sm text-slate-300">
          <span className="text-blue-400">{sectorName}</span> 板块前5股票
        </h3>
        <span className="text-xs text-slate-500">实时行情 & 投资建议</span>
      </div>

      <div className="grid grid-cols-5 gap-3">
        {stocks.map((stock) => (
          <div
            key={stock.code}
            className="bg-slate-900/50 backdrop-blur-xl rounded-xl border border-slate-800/50 overflow-hidden"
          >
            {/* Stock Chart */}
            <div className="h-[200px]">
              <StockChart
                stockCode={stock.code}
                stockName={stock.name}
              />
            </div>

            {/* Recommendation Section */}
            <div className="p-3 border-t border-slate-800/50 space-y-2">
              <div className="flex items-center justify-between">
                <div className={`flex items-center gap-1 px-2 py-1 rounded-lg border text-xs ${getLevelColor(stock.level)}`}>
                  {getLevelIcon(stock.level)}
                  <span>{stock.recommendation}</span>
                </div>
                <div className="flex items-center gap-1">
                  {stock.change >= 0 ? (
                    <TrendingUp className="w-3.5 h-3.5 text-red-400" />
                  ) : (
                    <TrendingDown className="w-3.5 h-3.5 text-green-400" />
                  )}
                  <span className={`text-xs ${stock.change >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                    {stock.change >= 0 ? '+' : ''}{stock.change}%
                  </span>
                </div>
              </div>

              <p className="text-xs text-slate-400 leading-relaxed">
                {stock.reason}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
