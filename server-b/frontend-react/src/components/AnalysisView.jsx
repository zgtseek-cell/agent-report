import { useState, useRef } from 'react'
import ReportView from './ReportView'
import FinancialDashboard from './FinancialDashboard'

const ANCHORS = [
  { id: 'report', label: '深度分析' },
  { id: 'valuation', label: '估值模型' },
  { id: 'metrics', label: '财务指标' },
]

function AnalysisView({
  analysisState,
  reportContent,
  setReportContent,
  onSaveHistory,
}) {
  const [metaInfo, setMetaInfo] = useState(null)
  const [metricsData, setMetricsData] = useState(null)
  const [dashboardTab, setDashboardTab] = useState('overview')
  const reportRef = useRef(null)
  const dashboardRef = useRef(null)

  const handleMetrics = (data) => {
    console.log('Metrics data:', data)
    setMetricsData(data)
  }

  const handleMeta = (data) => {
    setMetaInfo(data)
  }

  const scrollTo = (id) => {
    if (id === 'report') {
      reportRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return
    }
    if (id === 'valuation') {
      setDashboardTab('dcf')
      dashboardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return
    }
    if (id === 'metrics') {
      setDashboardTab('overview')
      dashboardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  return (
    <div className="w-full max-w-7xl mx-auto">
      {/* 锚点导航 */}
      <nav className="flex flex-wrap items-center gap-2 mb-4">
        {ANCHORS.map((a) => (
          <button
            key={a.id}
            type="button"
            onClick={() => scrollTo(a.id)}
            className="px-3 py-1.5 text-sm rounded-lg border border-white/10 text-slate-300
                       hover:bg-emerald-500/20 hover:text-emerald-400 hover:border-emerald-500/30 transition"
          >
            {a.label}
          </button>
        ))}
      </nav>

      {/* 双栏布局：桌面 4:6，移动端上下堆叠 */}
      <div className="grid grid-cols-1 lg:grid-cols-10 gap-6">
        {/* 左侧：报告流式渲染 */}
        <section
          ref={reportRef}
          className="lg:col-span-4 min-h-[400px]"
          id="section-report"
        >
          <ReportView
            analysisState={analysisState}
            reportContent={reportContent}
            setReportContent={setReportContent}
            onShowDashboard={() => {}}
            onSaveHistory={onSaveHistory}
            onMeta={handleMeta}
            onMetrics={handleMetrics}
            showDashboardButton={false}
          />
        </section>

        {/* 右侧：财务可视化看板 */}
        <section
          ref={dashboardRef}
          className="lg:col-span-6 min-h-[400px]"
          id="section-dashboard"
        >
          <FinancialDashboard
            marketData={metaInfo}
            analysisState={analysisState}
            metricsData={metricsData}
            activeTab={dashboardTab}
            onTabChange={setDashboardTab}
            triggerFetchOnMetaOnly
            skeletonWhenEmpty
          />
        </section>
      </div>
    </div>
  )
}

export default AnalysisView

