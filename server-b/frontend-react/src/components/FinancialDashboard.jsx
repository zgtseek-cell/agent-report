import { useState, useEffect, useCallback } from 'react'
import ReactECharts from 'echarts-for-react'
import { TrendingUp, DollarSign, Target, AlertTriangle, BarChart3, PieChart, LineChart } from 'lucide-react'
import { apiUrl } from '../api'

function FinancialDashboard({ marketData, analysisState, metricsData }) {
  const [financialData, setFinancialData] = useState(null)
  const [dcfData, setDcfData] = useState(null)
  const [pepbData, setPepbData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('overview') // overview | dcf | pepb

  const { symbol, market } = marketData || analysisState || {}

  const fetchFinancialData = useCallback(async () => {
    if (!symbol) return
    setLoading(true)
    try {
      const [financialsRes, dcfRes, pepbRes] = await Promise.allSettled([
        fetch(apiUrl(`/api/financials?symbol=${symbol}&market=${market || 'us'}`)),
        fetch(apiUrl(`/api/dcf?symbol=${symbol}&market=${market || 'us'}`)),
        fetch(apiUrl(`/api/pepb-band?symbol=${symbol}&market=${market || 'us'}`)),
      ])

      if (financialsRes.status === 'fulfilled' && financialsRes.value.ok) {
        const data = await financialsRes.value.json()
        setFinancialData(data)
      }

      if (dcfRes.status === 'fulfilled' && dcfRes.value.ok) {
        const data = await dcfRes.value.json()
        setDcfData(data)
      }

      if (pepbRes.status === 'fulfilled' && pepbRes.value.ok) {
        const data = await pepbRes.value.json()
        setPepbData(data)
      }
    } catch (err) {
      console.error('Failed to fetch financial data', err)
    } finally {
      setLoading(false)
    }
  }, [symbol, market])

  useEffect(() => {
    fetchFinancialData()
  }, [fetchFinancialData])

  // 营收利润图表
  const incomeChartOption = financialData?.chart?.income_statement ? {
    tooltip: { trigger: 'axis' },
    legend: { data: ['营收', '净利润', 'EBITDA'], textStyle: { color: '#94a3b8' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: financialData.chart.income_statement.labels,
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: { color: '#94a3b8' },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: { color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#1e293b' } },
    },
    series: financialData.chart.income_statement.datasets.map((ds, idx) => ({
      name: ds.label,
      type: 'line',
      smooth: true,
      data: ds.data,
      itemStyle: {
        color: idx === 0 ? '#10B981' : idx === 1 ? '#3b82f6' : '#f59e0b',
      },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: idx === 0 ? 'rgba(16,185,129,0.3)' : idx === 1 ? 'rgba(59,130,246,0.3)' : 'rgba(245,158,11,0.3)' },
            { offset: 1, color: 'rgba(0,0,0,0)' },
          ],
        },
      },
    })),
  } : null

  // DCF 估值图表
  const dcfChartOption = dcfData?.chart ? {
    tooltip: { trigger: 'axis' },
    legend: { data: ['未来现金流', '折现现值'], textStyle: { color: '#94a3b8' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: dcfData.chart.labels,
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: { color: '#94a3b8' },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: { color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#1e293b' } },
    },
    series: dcfData.chart.datasets.map((ds, idx) => ({
      name: ds.label,
      type: 'bar',
      data: ds.data,
      itemStyle: {
        color: idx === 0 ? '#10B981' : '#3b82f6',
      },
    })),
  } : null

  // PE Band 图表
  const peChartOption = pepbData?.chart?.pe_band ? {
    tooltip: { trigger: 'axis' },
    legend: {
      data: ['股价', 'PE Min', 'PE 25%', 'PE 50%', 'PE 75%', 'PE Max'],
      textStyle: { color: '#94a3b8' },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: pepbData.chart.pe_band.labels,
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: { color: '#94a3b8' },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: { color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#1e293b' } },
    },
    series: pepbData.chart.pe_band.datasets.map((ds, idx) => ({
      name: ds.label,
      type: 'line',
      smooth: true,
      data: ds.data,
      itemStyle: { color: ds.borderColor || '#94a3b8' },
      lineStyle: {
        type: ds.borderDash ? 'dashed' : 'solid',
      },
    })),
  } : null

  const tabs = [
    { id: 'overview', label: '概览', icon: BarChart3 },
    { id: 'dcf', label: 'DCF 估值', icon: Target },
    { id: 'pepb', label: 'PE/PB Band', icon: LineChart },
  ]

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="glass-panel">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-emerald-theme" />
              财务可视化看板
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              {symbol} · {market?.toUpperCase()}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {loading && <div className="w-4 h-4 border-2 border-emerald-theme border-t-transparent rounded-full animate-spin" />}
            <button
              onClick={fetchFinancialData}
              disabled={loading}
              className="btn-secondary text-xs py-1.5"
            >
              刷新数据
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 border-b border-white/10 pb-3 mb-4">
          {tabs.map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition
                  ${activeTab === tab.id
                    ? 'bg-emerald-theme/20 text-emerald-theme'
                    : 'text-slate-400 hover:text-slate-200'
                  }`}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard
              title="营收增长"
              value={metricsData?.revenue_growth || '—'}
              icon={TrendingUp}
              color="emerald"
            />
            <KpiCard
              title="现金流评分"
              value={metricsData?.cashflow_score || '—'}
              icon={DollarSign}
              color="blue"
            />
            <KpiCard
              title="风险等级"
              value={metricsData?.risk_level || '—'}
              icon={AlertTriangle}
              color={metricsData?.risk_level === '高' ? 'red' : metricsData?.risk_level === '中' ? 'yellow' : 'green'}
            />
            <KpiCard
              title="估值状态"
              value={metricsData?.valuation_status || '—'}
              icon={Target}
              color={metricsData?.valuation_status === '低估' ? 'green' : metricsData?.valuation_status === '合理' ? 'yellow' : 'red'}
            />
            <KpiCard
              title="仓位建议"
              value={metricsData?.position_recommendation || '—'}
              icon={Target}
              color="slate"
            />
            <KpiCard
              title="当前股价"
              value={dcfData?.raw && (dcfData.raw.current_price ?? '') !== '' ? `${Number(dcfData.raw.current_price).toFixed(2)} ${dcfData.raw?.currency || 'USD'}` : '—'}
              icon={DollarSign}
              color="emerald"
            />
            <KpiCard
              title="内在价值"
              value={dcfData?.valuation && (dcfData.valuation.intrinsic_value ?? '') !== '' ? `${Number(dcfData.valuation.intrinsic_value).toFixed(2)} ${dcfData.raw?.currency || 'USD'}` : '—'}
              icon={Target}
              color="blue"
            />
            <KpiCard
              title="安全边际"
              value={dcfData?.valuation && (dcfData.valuation.margin_of_safety ?? '') !== '' ? `${Number(dcfData.valuation.margin_of_safety).toFixed(1)}%` : '—'}
              icon={TrendingUp}
              color={dcfData?.valuation?.margin_of_safety > 20 ? 'green' : dcfData?.valuation?.margin_of_safety > 0 ? 'yellow' : 'red'}
            />
          </div>

          {/* 营收利润图表 */}
          {incomeChartOption && (
            <div className="glass-panel">
              <h3 className="text-sm font-medium mb-4 flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-emerald-theme" />
                财务趋势
              </h3>
              <ReactECharts
                option={incomeChartOption}
                style={{ height: '300px' }}
                theme="dark"
              />
            </div>
          )}
        </>
      )}

      {/* DCF Tab */}
      {activeTab === 'dcf' && (
        <>
          {/* DCF 参数 */}
          {dcfData?.parameters && (
            <div className="glass-panel mb-4">
              <h3 className="text-sm font-medium mb-3">估值参数</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <p className="text-slate-400 text-xs">增长率</p>
                  <p className="font-medium">{(dcfData.parameters.growth_rate * 100).toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-slate-400 text-xs">终值增长率</p>
                  <p className="font-medium">{(dcfData.parameters.terminal_growth * 100).toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-slate-400 text-xs">折现率</p>
                  <p className="font-medium">{(dcfData.parameters.discount_rate * 100).toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-slate-400 text-xs">预测年数</p>
                  <p className="font-medium">{dcfData.parameters.years} 年</p>
                </div>
              </div>
            </div>
          )}

          {/* DCF 图表 */}
          {dcfChartOption && (
            <div className="glass-panel">
              <h3 className="text-sm font-medium mb-4 flex items-center gap-2">
                <Target className="w-4 h-4 text-blue-400" />
                DCF 现金流
              </h3>
              <ReactECharts
                option={dcfChartOption}
                style={{ height: '300px' }}
                theme="dark"
              />
            </div>
          )}
        </>
      )}

      {/* PE/PB Tab */}
      {activeTab === 'pepb' && (
        <div className="glass-panel">
          <h3 className="text-sm font-medium mb-4 flex items-center gap-2">
            <LineChart className="w-4 h-4 text-yellow-400" />
            PE Band
          </h3>
          {peChartOption ? (
            <ReactECharts
              option={peChartOption}
              style={{ height: '350px' }}
              theme="dark"
            />
          ) : (
            <div className="flex items-center justify-center h-64 text-slate-400">
              {loading ? '加载中…' : '暂无数据'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function KpiCard({ title, value, icon: Icon, color }) {
  const colorClasses = {
    emerald: 'text-emerald-theme bg-emerald-theme/20',
    blue: 'text-blue-400 bg-blue-400/20',
    green: 'text-emerald-theme bg-emerald-theme/20',
    yellow: 'text-yellow-400 bg-yellow-400/20',
    red: 'text-red-400 bg-red-400/20',
    slate: 'text-slate-300 bg-slate-300/20',
  }

  return (
    <div className="glass-panel">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs text-slate-400">{title}</p>
        <div className={`w-8 h-8 rounded-lg ${colorClasses[color] || colorClasses.slate} flex items-center justify-center`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      <p className={`text-lg font-semibold ${colorClasses[color]?.split(' ')[0] || ''}`}>
        {value}
      </p>
    </div>
  )
}

export default FinancialDashboard
