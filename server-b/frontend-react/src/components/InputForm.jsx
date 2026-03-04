import { useState, useRef, useEffect } from 'react'
import { Search, Clock, TrendingUp, Zap, ChevronDown } from 'lucide-react'

function InputForm({ history, onStartAnalysis, onSelectHistory }) {
  const [companyName, setCompanyName] = useState('')
  const [market, setMarket] = useState('auto')
  const [symbol, setSymbol] = useState('')
  const [position, setPosition] = useState(0)
  const [extraPrompt, setExtraPrompt] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const historyDropdownRef = useRef(null)
  const [marketOpen, setMarketOpen] = useState(false)
  const marketDropdownRef = useRef(null)

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (historyDropdownRef.current && !historyDropdownRef.current.contains(e.target)) {
        setHistoryOpen(false)
      }
      if (marketDropdownRef.current && !marketDropdownRef.current.contains(e.target)) {
        setMarketOpen(false)
      }
    }
    document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [])

  const quickTags = [
    '侧重短线机会',
    '深度财务剖析',
    '对标竞品分析',
  ]

  const marketOptions = [
    { value: 'auto', label: '自动识别' },
    { value: 'hk', label: '港股' },
    { value: 'us', label: '美股' },
    { value: 'cn', label: 'A股' },
  ]

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!companyName.trim()) return
    onStartAnalysis({
      companyName: companyName.trim(),
      market,
      symbol: symbol.trim(),
      position,
      extraPrompt: extraPrompt.trim(),
    })
  }

  const handleTagClick = (tag) => {
    setExtraPrompt(prev => prev ? prev + '；' + tag : tag)
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="glass-panel">
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* 公司名称 */}
          <div className="relative p-4 -mx-1 rounded-xl bg-white/3 ring-1 ring-white/5 ring-inset">
            <label className="flex items-center gap-2 text-sm font-medium mb-2">
              <Search className="w-4 h-4 text-emerald-theme/90" />
              <span>公司名称</span>
            </label>
            <div className="relative">
              <input
                type="text"
                value={companyName}
                onChange={(e) => {
                  setCompanyName(e.target.value)
                  if (e.target.value) setSymbol('')
                }}
                placeholder="例如：泡泡玛特、Apple、腾讯控股"
                className="input-glow border-emerald-theme/40"
                autoFocus
              />
            </div>
          </div>

          {/* 历史记录 - 自定义下拉（深色可见） */}
          {history.length > 0 && (
            <div ref={historyDropdownRef} className="relative">
              <label className="block text-sm font-medium mb-2 text-slate-400">
                <Clock className="w-4 h-4 inline mr-1" />
                历史查询
              </label>
              <button
                type="button"
                onClick={() => setHistoryOpen((o) => !o)}
                className="input-glow w-full flex items-center justify-between text-left text-sm text-white"
              >
                <span className="text-slate-300">选择历史记录</span>
                <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${historyOpen ? 'rotate-180' : ''}`} />
              </button>
              {historyOpen && (
                <ul
                  className="absolute z-50 mt-1 w-full rounded-lg border border-white/10 backdrop-blur-md bg-slate-800/95 py-1 shadow-xl"
                  role="listbox"
                >
                  {history.map((item, idx) => (
                    <li key={idx} role="option">
                      <button
                        type="button"
                        onClick={() => {
                          onSelectHistory(item)
                          setHistoryOpen(false)
                        }}
                        className="w-full px-3 py-2.5 text-left text-sm text-white hover:bg-emerald-500/20 transition-colors rounded-none first:rounded-t-lg last:rounded-b-lg"
                      >
                        {item.companyName} ({item.market?.toUpperCase() ?? '—'})
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* 市场和代码 + 仓位 */}
          <div className="grid grid-cols-2 gap-3">
            <div ref={marketDropdownRef} className="relative">
              <label className="block text-sm font-medium mb-1">市场</label>
              <button
                type="button"
                onClick={() => {
                  setMarketOpen(!marketOpen)
                }}
                className="input-glow w-full flex items-center justify-between text-left text-sm text-white"
              >
                <span className="text-slate-300">
                  {marketOptions.find((m) => m.value === market)?.label || '自动识别'}
                </span>
                <ChevronDown
                  className={`w-4 h-4 text-slate-400 transition-transform ${
                    marketOpen ? 'rotate-180' : ''
                  }`}
                />
              </button>
              {marketOpen && (
                <ul
                  className="absolute z-50 mt-1 w-full rounded-lg border border-white/10 backdrop-blur-md bg-slate-800/95 py-1 shadow-xl"
                  role="listbox"
                >
                  {marketOptions.map((opt) => (
                    <li key={opt.value} role="option">
                      <button
                        type="button"
                        onClick={() => {
                          setMarket(opt.value)
                          setMarketOpen(false)
                        }}
                        className="w-full px-3 py-2.5 text-left text-sm text-white hover:bg-emerald-500/20 transition-colors rounded-none first:rounded-t-lg last:rounded-b-lg"
                      >
                        {opt.label}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">股票代码</label>
              <input
                type="text"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                placeholder="如：700 / AAPL / 600519"
                className="input-glow"
              />
            </div>
          </div>

          {/* 仓位 */}
          <div>
            <label className="block text-sm font-medium mb-2 flex items-center gap-2">
              <Zap className="w-4 h-4 text-emerald-theme" />
              当前仓位：<span className="text-emerald-theme font-semibold">{position}%</span>
            </label>
            <input
              type="range"
              min="0"
              max="100"
              value={position}
              onChange={(e) => setPosition(Number(e.target.value))}
              className="w-full h-2 bg-white/10 rounded-lg appearance-none cursor-pointer accent-emerald-theme"
            />
            <div className="flex justify-between text-xs text-slate-500 mt-1">
              <span>空仓</span>
              <span>轻仓</span>
              <span>中仓</span>
              <span>重仓</span>
              <span>满仓</span>
            </div>
          </div>

          {/* 补充要求 */}
          <div>
            <label className="block text-sm font-medium mb-1">补充要求（可选）</label>
            <textarea
              value={extraPrompt}
              onChange={(e) => setExtraPrompt(e.target.value)}
              placeholder="例如：更关注估值安全边际；侧重短线交易机会…"
              className="input-glow h-24 resize-none"
            />
            <div className="flex flex-wrap gap-2 mt-2">
              {quickTags.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  onClick={() => handleTagClick(tag)}
                  className="px-3 py-1.5 text-xs rounded border border-white/10 text-slate-400
                           hover:border-emerald-theme/40 hover:text-emerald-theme/90 transition"
                >
                  {tag}
                </button>
              ))}
            </div>
          </div>

          {/* 提交按钮 */}
          <button
            type="submit"
            disabled={!companyName.trim()}
            className="btn-primary w-full"
          >
            <TrendingUp className="w-4 h-4" />
            <span>开始分析</span>
          </button>
        </form>

        {/* 免责声明 */}
        <p className="text-[11px] text-slate-500 mt-4">
          提示：本工具仅用于研究学习，所有内容基于公开信息生成，不构成任何投资建议。
        </p>
      </div>
    </div>
  )
}

export default InputForm
