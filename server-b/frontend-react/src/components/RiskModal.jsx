import { AlertTriangle, X } from 'lucide-react'

function RiskModal({ isOpen, onClose, onConfirm }) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative glass-panel max-w-md w-full animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-500/20 flex items-center justify-center">
              <AlertTriangle className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <h3 className="font-semibold">风险提示</h3>
              <p className="text-xs text-slate-400">请认真阅读以下内容</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 transition"
          >
            <X className="w-4 h-4 text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="space-y-3 text-sm text-slate-300 mb-5">
          <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <p className="text-amber-300 font-medium text-xs mb-1">免责声明</p>
            <p className="text-xs">
              本工具提供的所有分析内容仅供学习和研究使用，<strong className="text-slate-100">不构成任何投资建议</strong>。
            </p>
          </div>

          <ul className="space-y-2 text-xs">
            <li className="flex items-start gap-2">
              <span className="text-emerald-theme mt-0.5">•</span>
              <span>股票投资存在风险，可能导致本金损失。</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-emerald-theme mt-0.5">•</span>
              <span>分析内容基于公开信息和 AI 生成，可能存在错误或滞后。</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-emerald-theme mt-0.5">•</span>
              <span>请独立做出投资决策，并自行承担相关风险。</span>
            </li>
          </ul>
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="btn-secondary flex-1"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="btn-primary flex-1"
          >
            我已了解并同意
          </button>
        </div>
      </div>
    </div>
  )
}

export default RiskModal
