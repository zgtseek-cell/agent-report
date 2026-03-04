import { useState, Component } from 'react'
import { ChevronRight, TrendingUp, BarChart3, AlertCircle, Home, ArrowLeft } from 'lucide-react'
import InputForm from './components/InputForm'
import ReportView from './components/ReportView'
import FinancialDashboard from './components/FinancialDashboard'
import RiskModal from './components/RiskModal'

// 错误边界：避免未捕获错误导致整页空白
class ErrorBoundary extends Component {
  state = { hasError: false, error: null }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center p-6">
          <div className="max-w-md text-center space-y-3">
            <h2 className="text-lg font-semibold">页面加载异常</h2>
            <p className="text-sm text-slate-400">
              请按 F12 打开开发者工具，在 Console 和 Network 中查看是否有报错或 404。
            </p>
            <p className="text-xs text-slate-500 break-all">
              {this.state.error?.message || ''}
            </p>
            <button
              type="button"
              className="px-4 py-2 bg-emerald-600 rounded text-sm"
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              重试
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

const RISK_ACK_KEY = 'stock_advisor_risk_ack'
const HISTORY_KEY = 'stock_advisor_history'

function App() {
  const [view, setView] = useState('form') // 'form' | 'report' | 'dashboard'
  const [showRiskModal, setShowRiskModal] = useState(false)
  const [analysisState, setAnalysisState] = useState({
    companyName: '',
    market: 'auto',
    symbol: '',
    position: 0,
  })
  const [reportContent, setReportContent] = useState('')
  const [marketData, setMarketData] = useState(null)
  const [metricsData, setMetricsData] = useState(null)
  const [history, setHistory] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
    } catch {
      return []
    }
  })

  const hasRiskAck = localStorage.getItem(RISK_ACK_KEY)

  const saveHistory = (item) => {
    const newHistory = [item, ...history.filter(
      h => !(h.market === item.market && h.symbol === item.symbol)
    )].slice(0, 20)
    setHistory(newHistory)
    localStorage.setItem(HISTORY_KEY, JSON.stringify(newHistory))
  }

  const handleStartAnalysis = (data) => {
    if (!hasRiskAck) {
      setShowRiskModal(true)
      return
    }
    startAnalysis(data)
  }

  const startAnalysis = (data) => {
    setAnalysisState(data)
    setView('report')
    setReportContent('')
    setMarketData(null)
  }

  const handleRiskConfirm = () => {
    localStorage.setItem(RISK_ACK_KEY, '1')
    setShowRiskModal(false)
  }

  const handleBackToForm = () => {
    setView('form')
    setReportContent('')
    setMarketData(null)
  }

  const handleShowDashboard = (data) => {
    setMarketData(data)
    setView('dashboard')
  }

  const handleMetrics = (data) => {
    console.log('Received metrics data:', data)
    setMetricsData(data)
  }

  return (
    <ErrorBoundary>
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="sticky top-0 z-20 bg-slate-950/95 backdrop-blur-md border-b border-white/10">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          {view !== 'form' ? (
            <button
              onClick={handleBackToForm}
              className="flex items-center gap-2 text-slate-300 hover:text-slate-100 transition"
            >
              <ArrowLeft className="w-5 h-5" />
              <span className="text-sm font-medium">返回</span>
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-emerald-theme/20 flex items-center justify-center">
                <TrendingUp className="w-5 h-5 text-emerald-theme" />
              </div>
              <div>
                <h1 className="text-lg font-semibold">股票智能顾问</h1>
                <p className="text-xs text-slate-400">价值投资分析</p>
              </div>
            </div>
          )}
          <div className="flex items-center gap-2">
            {view === 'report' && marketData && (
              <button
                onClick={() => setView('dashboard')}
                className="btn-secondary text-xs py-1.5"
              >
                <BarChart3 className="w-4 h-4" />
                <span>财务看板</span>
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-4 py-6">
        {view === 'form' && (
          <InputForm
            history={history}
            onStartAnalysis={handleStartAnalysis}
            onSelectHistory={(item) => {
              setAnalysisState(item)
              startAnalysis(item)
            }}
          />
        )}

        {view === 'report' && (
          <ReportView
            analysisState={analysisState}
            reportContent={reportContent}
            setReportContent={setReportContent}
            onShowDashboard={handleShowDashboard}
            onSaveHistory={saveHistory}
            onMetrics={handleMetrics}
          />
        )}

        {view === 'dashboard' && (
          <FinancialDashboard
            marketData={marketData}
            analysisState={analysisState}
            metricsData={metricsData}
          />
        )}
      </main>

      {/* Risk Modal */}
      <RiskModal
        isOpen={showRiskModal}
        onClose={() => setShowRiskModal(false)}
        onConfirm={handleRiskConfirm}
      />
    </div>
    </ErrorBoundary>
  )
}

export default App
