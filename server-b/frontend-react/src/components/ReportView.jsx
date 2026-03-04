import { useState, useEffect, useRef } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { Send, Loader2, Download, BarChart3, ArrowDownToLine } from 'lucide-react'
import { apiUrl } from '../api'

function ReportView({
  analysisState,
  reportContent,
  setReportContent,
  onShowDashboard,
  onSaveHistory,
  onMeta,
  onMetrics,
  showDashboardButton = true,
}) {
  const [isLoading, setIsLoading] = useState(true)
  const [isStreaming, setIsStreaming] = useState(false)
  const [statusText, setStatusText] = useState('正在连接分析服务…')
  const [metaInfo, setMetaInfo] = useState(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const outputRef = useRef(null)
  const eventSourceRef = useRef(null)

  const { companyName, market, symbol, position, extraPrompt } = analysisState

  useEffect(() => {
    const params = new URLSearchParams()
    params.set('company_name', companyName)
    params.set('market', market)
    if (symbol) params.set('symbol', symbol)
    if (extraPrompt) params.set('extra_prompt', extraPrompt)
    if (position !== undefined && position !== null) {
      params.set('position', String(position))
    }

    const es = new EventSource(apiUrl(`/api/analyze_sse?${params.toString()}`))
    eventSourceRef.current = es
    setIsLoading(true)
    setIsStreaming(false)
    setStatusText('正在连接分析服务…')
    setReportContent('')

    let firstContent = true

    es.onopen = () => {}

    es.onmessage = (event) => {
      const raw = event.data || ''

      if (raw === '[DONE]') {
        setIsLoading(false)
        setIsStreaming(false)
        setStatusText('分析完成 ✅')
        es.close()
        return
      }

      if (raw.startsWith('{')) {
        try {
          const data = JSON.parse(raw)
          if (data.type === 'status') {
            setStatusText(data.message || '正在处理…')
            return
          }
          if (data.type === 'meta') {
            setMetaInfo(data)
            if (data.market && data.symbol) {
              onSaveHistory({
                companyName: data.company_name || companyName,
                market: data.market,
                symbol: data.symbol,
              })
            }
            if (onMeta) {
              onMeta(data)
            }
            setStatusText('正在获取公司信息…')
            return
          }
          if (data.type === 'metrics') {
            // 处理指标数据
            console.log('Metrics data:', data)
            // 可以在这里添加指标数据的处理逻辑
            // 例如：更新组件状态或传递给父组件
            if (onMetrics) {
              onMetrics(data)
            }
            return
          }
        } catch {
          // 不是有效 JSON，继续作为内容处理
        }
      }

      const text = raw.replace(/\\n/g, '\n')
      setReportContent(prev => prev + text)

      if (firstContent) {
        firstContent = false
        setIsLoading(false)
        setIsStreaming(true)
        setStatusText('正在深度分析中…')
      }
    }

    es.onerror = (err) => {
      console.error('SSE error', err)
      setIsLoading(false)
      setIsStreaming(false)
      setStatusText('分析中断，请重试')
      setReportContent(prev => prev + '\n[错误] 连接分析服务失败，请稍后重试。')
      es.close()
    }

    return () => {
      if (es.readyState !== EventSource.CLOSED) {
        es.close()
      }
    }
  // 只在分析参数变更时重新建立 SSE 连接，避免因为父组件函数引用变化导致频繁断开重连
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyName, market, symbol, position, extraPrompt])

  useEffect(() => {
    if (autoScroll && outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [reportContent, autoScroll])

  const handleScroll = (e) => {
    const { scrollTop, scrollHeight, clientHeight } = e.target
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100
    setAutoScroll(isNearBottom)
  }

  const handleDownload = () => {
    if (!reportContent) return
    const blob = new Blob([reportContent], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `analysis-${companyName}-${new Date().toISOString().slice(0, 10)}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const getHtml = () => {
    const html = marked.parse(reportContent)
    return DOMPurify.sanitize(html, { ADD_ATTR: ['target'] })
  }

  return (
    <div className="w-full">
      <div className="glass-panel flex flex-col h-[calc(100vh-140px)]">
        {/* Header */}
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-medium">分析结果</h2>
              {metaInfo && (
                <span className="text-xs text-slate-400">
                  {metaInfo.market?.toUpperCase()} {metaInfo.symbol}
                </span>
              )}
            </div>
            <span className="text-xs text-slate-500">{statusText}</span>
          </div>
          <div className="flex items-center gap-2">
            {(isLoading || isStreaming) && (
              <Loader2 className="w-4 h-4 animate-spin text-emerald-theme" />
            )}
            {showDashboardButton && metaInfo && (
              <button
                onClick={() => onShowDashboard(metaInfo)}
                className="btn-secondary text-xs py-1.5"
              >
                <BarChart3 className="w-4 h-4" />
                <span className="hidden sm:inline">财务看板</span>
              </button>
            )}
            {reportContent && (
              <button
                onClick={handleDownload}
                className="btn-secondary text-xs py-1.5"
              >
                <Download className="w-4 h-4" />
                <span className="hidden sm:inline">保存</span>
              </button>
            )}
          </div>
        </div>

        {/* Output */}
        <div
          ref={outputRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto rounded-xl bg-black/20 border border-white/10 p-6"
        >
          {!reportContent && (
            <div className="flex flex-col items-center justify-center h-full text-slate-400">
              <Loader2 className="w-8 h-8 animate-spin text-emerald-theme mb-3" />
              <p className="text-sm">{statusText}</p>
            </div>
          )}
          {reportContent && (
            <div
              className="markdown-body"
              dangerouslySetInnerHTML={{ __html: getHtml() }}
            />
          )}
        </div>

        {/* Scroll hint */}
        {isStreaming && !autoScroll && (
          <div className="flex justify-center mt-3">
            <button
              onClick={() => {
                setAutoScroll(true)
                outputRef.current?.scrollTo({
                  top: outputRef.current.scrollHeight,
                  behavior: 'smooth',
                })
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full
                       bg-emerald-theme/20 text-emerald-theme border border-emerald-theme/30"
            >
              <ArrowDownToLine className="w-3.5 h-3.5" />
              <span>自动滚动</span>
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default ReportView
