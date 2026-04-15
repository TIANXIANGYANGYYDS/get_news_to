import { Flame, TrendingUp } from 'lucide-react';
import { useState } from 'react';
import { SectorStocksDialog } from './SectorStocksDialog';

export function MarketAnalysis() {
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [selectedSector, setSelectedSector] = useState('');

  const handleSectorClick = (sectorName: string) => {
    setSelectedSector(sectorName);
    setIsDialogOpen(true);
  };
  const analysis = {
    date: '2026年4月4日',
    mainLines: [
      {
        rank: 1,
        title: '油气开采及服务',
        priority: 'high',
        reason: '昨日板块已强势领涨5.36%，中油工程等3股涨停形成明确板块联动，封板效率高且ETF领涨6.51%，验证资金避险抱团逻辑；今晨WTI原油暴涨至112美元/桶（单日+11.93%），布伦特突破109美元，地缘冲突直接强化能源安全主线，A股资金将优先承接昨日已验证的油气开采及服务板块而非下游加工；因霍尔木兹海峡风险升级，资金今日更可能主攻上游开采环节（弹性更大、涨停标的集中），而非石油加工贸易等衍生方向，属于风险偏好回落下的核心进攻主线。'
      },
      {
        rank: 2,
        title: '养殖业',
        priority: 'medium',
        reason: '昨日巨星农牧涨停带动板块逆势走强，商务部收储政策已形成初步交易基础，但涨幅弱于油气且缺乏中军标的共振；今晨生猪价格异动提示及收储持续属于政策延续性催化，未新增强刺激，A股资金将视其为防守型承接方向而非主攻；在指数缩量下跌环境中，养殖业作为政策托底的刚需板块，承接昨日猪肉逻辑的避险资金，但弹性受限于猪周期位置，今日定位为油气主线外的次级防守承接方向。'
      },
      {
        rank: 3,
        title: '石油加工贸易',
        priority: 'medium',
        reason: '昨日板块上涨1.86%且ETF跟涨5.73%，作为油气上游的延伸方向已有联动基础，但涨幅和涨停家数弱于开采环节；今晨原油暴涨将传导至炼化利润改善预期，但资金更倾向攻击上游开采（弹性更高），石油加工贸易仅作为跟风支线；因炼化企业成本传导存在时滞，且昨日银行等权重护盘消耗资金，今日该板块更可能跟随油气开采及服务被动走强，属于主攻主线的卫星支线而非独立方向。'
      },
      {
        rank: 4,
        title: '生物制品',
        priority: 'low',
        reason: '美国对进口药加征100%关税属突发催化，但昨日医药商业仅微涨2.38%且算力板块大跌，未形成医药板块联动；A股资金可能将逻辑映射至生物制品（创新药国产替代核心承载板块），但属于推测逻辑——券商虽推创新药，但昨日无资金验证且医药IT受挫；今日更可能作为事件驱动的观察级支线，若开盘高开则易被证伪（因关税实际利空进口依赖企业），仅当油气主线分歧时才有轮动机会。'
      },
      {
        rank: 5,
        title: '工业金属',
        priority: 'low',
        reason: '美国对钢铁铝铜加征25%关税理论上利好内需，但昨日工业金属无异动（钢铁跌1.66%），且今晨白银大跌3.17%压制大宗商品情绪；A股历史上更倾向交易"资源涨价"而非"关税博弈"，资金可能忽略该消息或转向油气；因缺乏昨日盘面基础且与当前避险风格错配，仅作为地缘风险下的观察方向，若原油持续暴涨或带动铜铝跟风，但承接力度弱于油气主线。'
      }
    ]
  };

  const getPriorityStyle = (priority: string) => {
    switch (priority) {
      case 'high':
        return {
          badge: 'bg-red-500/10 border-red-500/30 text-red-400',
          border: 'border-red-500/30',
          icon: 'text-red-400'
        };
      case 'medium':
        return {
          badge: 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400',
          border: 'border-yellow-500/30',
          icon: 'text-yellow-400'
        };
      default:
        return {
          badge: 'bg-slate-700/30 border-slate-600/30 text-slate-400',
          border: 'border-slate-700/50',
          icon: 'text-slate-400'
        };
    }
  };

  const getPriorityLabel = (priority: string) => {
    switch (priority) {
      case 'high': return '核心主线';
      case 'medium': return '次级主线';
      default: return '观察主线';
    }
  };

  return (
    <>
      <SectorStocksDialog
        isOpen={isDialogOpen}
        onClose={() => setIsDialogOpen(false)}
        sectorName={selectedSector}
      />
      <div className="bg-slate-900/50 backdrop-blur-xl rounded-2xl border border-slate-800/50 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/50 bg-gradient-to-r from-slate-800/30 to-slate-900/30">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-gradient-to-br from-orange-500 to-red-600 rounded-lg">
            <Flame className="w-4 h-4 text-white" />
          </div>
          <div>
            <h3 className="text-sm text-white">每日盘前分析</h3>
            <p className="text-xs text-slate-400">{analysis.date}</p>
          </div>
        </div>
        <div className="px-2.5 py-1 bg-blue-500/10 border border-blue-500/30 rounded-lg">
          <span className="text-xs text-blue-400">AI 智能分析</span>
        </div>
      </div>

      {/* Main Lines */}
      <div className="p-4 space-y-3">
        {analysis.mainLines.map((line) => {
          const style = getPriorityStyle(line.priority);
          return (
            <div
              key={line.rank}
              onClick={() => handleSectorClick(line.title)}
              className={`p-3 bg-slate-800/20 border-2 ${style.border} rounded-xl hover:bg-slate-800/40 transition-all cursor-pointer hover:scale-[1.01]`}
            >
              {/* Title Row */}
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <div className="flex items-center justify-center w-7 h-7 bg-slate-900/50 border border-slate-700/50 rounded-lg">
                    <span className={`text-xs ${style.icon}`}>#{line.rank}</span>
                  </div>
                  <div>
                    <h4 className="text-sm text-white mb-0.5 flex items-center gap-2">
                      {line.title}
                      {line.rank === 1 && <TrendingUp className="w-3.5 h-3.5 text-red-400" />}
                    </h4>
                    <div className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs ${style.badge}`}>
                      {getPriorityLabel(line.priority)}
                    </div>
                  </div>
                </div>
              </div>

              {/* Reason */}
              <div className="pl-9">
                <p className="text-xs text-slate-400 leading-relaxed">
                  <span className="text-slate-500 mr-1.5">理由：</span>
                  {line.reason}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer Tips */}
      <div className="px-4 pb-4">
        <div className="p-2.5 bg-gradient-to-r from-blue-500/10 to-indigo-500/10 border border-blue-500/30 rounded-xl">
          <div className="flex items-start gap-2">
            <div className="w-5 h-5 bg-blue-500/20 rounded flex items-center justify-center flex-shrink-0">
              <span className="text-xs">💡</span>
            </div>
            <div>
              <p className="text-xs text-blue-400 mb-0.5">操作建议</p>
              <p className="text-xs text-slate-400 leading-relaxed">
                重点关注油气开采及服务板块的强势延续，次级关注养殖业和石油加工贸易的联动机会。生物制品和工业金属作为观察方向，需等待市场验证后再行跟进。
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
    </>
  );
}
