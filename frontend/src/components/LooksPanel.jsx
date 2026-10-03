import React from 'react'
import { formatNum } from '../api.js'

const DECISION_TEXT = {
  continue: ['继续监测', 'tag-ok'],
  reject: ['拒绝 H0：实验组更优', 'tag-reject'],
  reject_negative: ['拒绝 H0：对照组更优', 'tag-reject'],
}

export default function LooksPanel({ looks, exp }) {
  return (
    <div className="card">
      <h3>查看记录（边界与结论均已冻结，永不改写）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>#</th><th>触发</th><th>t（原始）</th><th>t（有效）</th>
            <th>Z</th><th>±边界</th><th>累计消耗 α</th>
            <th>对照 转/访</th><th>实验 转/访</th>
            <th>结论</th><th>更正标记</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          {looks.map((l) => {
            const [text, cls] = DECISION_TEXT[l.decision]
            return (
              <tr key={l.look_number} className={l.decision !== 'continue' ? 'row-decision' : ''}>
                <td>{l.look_number}</td>
                <td>{l.trigger === 'manual' ? '手动' : '定时'}</td>
                <td>
                  {formatNum(l.raw_info_time, 4)}
                  {l.clipped && <span className="tag tag-warn" title="raw>1 或更正导致倒退，已截断/夹断">截断</span>}
                </td>
                <td><b>{formatNum(l.info_time, 4)}</b></td>
                <td className={Math.abs(l.z_stat) > l.boundary ? 'z-cross' : ''}>
                  {formatNum(l.z_stat, 4)}
                </td>
                <td>±{formatNum(l.boundary, 4)}</td>
                <td>{formatNum(l.cumulative_spend, 6)}</td>
                <td>{l.control_conversions}/{l.control_visits}</td>
                <td>{l.treatment_conversions}/{l.treatment_visits}</td>
                <td><span className={`tag ${cls}`}>{text}</span></td>
                <td>{l.correction_since_last && <span className="tag tag-warn">含更正</span>}</td>
                <td className="muted">{new Date(l.created_at).toLocaleString('zh-CN')}</td>
              </tr>
            )
          })}
          {looks.length === 0 && (
            <tr><td colSpan="12" className="muted">尚未查看，点击右上角「手动触发一次查看」。</td></tr>
          )}
        </tbody>
      </table>
      <p className="muted small">
        冻结策略说明：某一行一旦写入，其 Z、边界、累计消耗与结论即被冻结；
        之后收到的批次更正只影响后续查看。若更正后当前 Z 回到界内，
        系统会在手动查看的响应中给出「当前证据不再支持历史结论」的显著提示，
        但不会改写或撤回已宣布的历史结论。
      </p>
    </div>
  )
}
