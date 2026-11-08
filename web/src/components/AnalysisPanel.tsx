import type { AnalyzeResult, Generation } from '../api'
import { SCENARIOS } from '../chat'

const BUSINESS_LABELS: Record<string, string> = {
  needs_input: '需要补充资料',
  contact_blocked: '已停止：客户明确拒绝联系',
  technical_failure: '生成失败',
  interrupted: '生成任务已中断，未自动重试',
}

interface AnalysisPanelProps {
  analysis: AnalyzeResult | null
  scenario: string
  onScenarioChange: (scenario: string) => void
  analyzing: boolean
  analysisError: string | null
  onAnalyze: () => void
  generating: boolean
  generationError: string | null
  onGenerate: () => void
  generation: Generation | null
}

export default function AnalysisPanel({
  analysis,
  scenario,
  onScenarioChange,
  analyzing,
  analysisError,
  onAnalyze,
  generating,
  generationError,
  onGenerate,
  generation,
}: AnalysisPanelProps) {
  return (
    <section className="panel analysis-panel">
      <div className="panel-head">
        <h2>理解这轮需求</h2>
        <button className="btn primary" type="button" disabled={analyzing} onClick={onAnalyze}>
          {analyzing ? '分析中…' : '分析并提问'}
        </button>
      </div>
      {analysisError && <div className="alert error">{analysisError}（未自动重试）</div>}
      {analysis && (
        <div className="analysis-result">
          <label className="field">
            <span className="field-label">识别场景（可调整）</span>
            <select value={scenario} onChange={(event) => onScenarioChange(event.target.value)}>
              {SCENARIOS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <div className="analysis-block">
            <h3>本次需求摘要</h3>
            <p>{analysis.current_need || '（分析未给出摘要）'}</p>
          </div>
          <div className="analysis-block">
            <h3>待确认问题</h3>
            {analysis.missing_questions.length > 0 ? (
              <ul>
                {analysis.missing_questions.map((question, index) => (
                  <li key={index}>{question}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">本轮资料足够，暂无必须确认的问题。</p>
            )}
          </div>
          <p className="muted">把客户答复以「客户：…」补进上方对话后，再生成三条候选。</p>
          <div className="generate-row">
            <button className="btn primary wide" type="button" disabled={generating} onClick={onGenerate}>
              {generating ? '生成中…（不自动重试）' : '生成三条候选'}
            </button>
          </div>
          {generationError && <div className="alert error">{generationError}</div>}
          {generation && generation.business_status && generation.business_status !== 'success' && (
            <div className="alert error">
              <strong>{BUSINESS_LABELS[generation.business_status] ?? generation.business_status}</strong>
              {generation.missing_fields.length > 0 && <div>待补充：{generation.missing_fields.join('、')}</div>}
              {generation.error && <div>{generation.error}</div>}
            </div>
          )}
          {generation && generation.business_status === 'success' && generation.warnings.length > 0 && (
            <div className="alert warning">
              {generation.warnings.map((warning, index) => (
                <div key={index}>{warning}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
