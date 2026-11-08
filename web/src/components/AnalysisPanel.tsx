import { useState } from 'react'

import type { AnalyzeResult, Generation } from '../api'
import { SCENARIOS } from '../chat'

const BUSINESS_LABELS: Record<string, string> = {
  needs_input: '需要补充资料',
  contact_blocked: '已停止：客户明确拒绝联系',
  technical_failure: '生成失败',
  interrupted: '生成未完成，请重试',
}

function QuestionRow({ question }: { question: string }) {
  const [copied, setCopied] = useState(false)
  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(question)
      setCopied(true)
    } catch {
      // 剪贴板不可用时保持原文可见，用户可手动选中复制。
    }
  }
  return (
    <li className="question-row">
      <span className="question-text">{question}</span>
      <button className="btn mini" type="button" onClick={() => void handleCopy()}>
        {copied ? '已复制' : '复制'}
      </button>
    </li>
  )
}

interface AnalysisPanelProps {
  analysis: AnalyzeResult | null
  scenario: string
  onScenarioChange: (scenario: string) => void
  needText: string
  onNeedTextChange: (text: string) => void
  analyzing: boolean
  analysisError: string | null
  onRetryAnalysis: () => void
  generating: boolean
  generationError: string | null
  onGenerate: () => void
  generation: Generation | null
  hasMessages: boolean
}

export default function AnalysisPanel({
  analysis,
  scenario,
  onScenarioChange,
  needText,
  onNeedTextChange,
  analyzing,
  analysisError,
  onRetryAnalysis,
  generating,
  generationError,
  onGenerate,
  generation,
  hasMessages,
}: AnalysisPanelProps) {
  return (
    <section className="panel analysis-panel">
      <div className="analysis-top">
        <label className="field inline">
          <span className="field-label">识别场景</span>
          <select
            className="compact-select"
            value={scenario || SCENARIOS[0]}
            disabled={!analysis}
            onChange={(event) => onScenarioChange(event.target.value)}
          >
            {SCENARIOS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        {analyzing && <span className="muted">正在理解对话…</span>}
        {!analysis && !analyzing && !analysisError && (
          <span className="muted">{hasMessages ? '添加消息后自动分析' : '先添加对话消息'}</span>
        )}
        <span className="spacer" />
        <button className="btn primary" type="button" disabled={generating || !analysis} onClick={onGenerate}>
          {generating ? '生成中…' : '生成三条候选'}
        </button>
      </div>
      <input
        className="need-input"
        type="text"
        value={needText}
        disabled={!analysis}
        onChange={(event) => onNeedTextChange(event.target.value)}
        placeholder="一句话需求，可修改"
      />
      {analysis && analysis.missing_questions.length > 0 && (
        <details className="questions-toggle">
          <summary>待确认 {analysis.missing_questions.length} 条</summary>
          <ul className="question-list">
            {analysis.missing_questions.map((question, index) => (
              <QuestionRow key={index} question={question} />
            ))}
          </ul>
        </details>
      )}
      {analysisError && (
        <div className="alert error inline-alert">
          <span>分析失败：{analysisError}</span>
          <button className="btn mini" type="button" onClick={onRetryAnalysis}>
            重试
          </button>
        </div>
      )}
      {generationError && <div className="alert error inline-alert">{generationError}</div>}
      {generation && generation.business_status && generation.business_status !== 'success' && (
        <div className="alert error inline-alert">
          <strong>{BUSINESS_LABELS[generation.business_status] ?? generation.business_status}</strong>
          {generation.missing_fields.length > 0 && <span> · 待补充：{generation.missing_fields.join('、')}</span>}
        </div>
      )}
      {generation && generation.business_status === 'success' && generation.warnings.length > 0 && (
        <div className="alert warning inline-alert">
          {generation.warnings.map((warning, index) => (
            <div key={index}>{warning}</div>
          ))}
        </div>
      )}
    </section>
  )
}
