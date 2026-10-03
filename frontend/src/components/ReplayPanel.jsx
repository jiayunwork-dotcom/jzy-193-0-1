import React, { useState } from 'react'
import { api, formatNum } from '../api.js'

export default function ReplayPanel({ experimentId }) {
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  async function run() {
    setBusy(true); setErr(null)
    try {
      setReport(await api.replay(experimentId))
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h3>按事件流从头重放（确定性校验）</h3>
      <p className="muted small">
        系统按不可变事件流（新增 / 更正 / 重复忽略）的接收顺序重建批次表，
        并在每次历史查看触发时所对应的事件处截断，用与在线完全相同的冻结式
        算法重算 Z、信息比例与边界，逐字段比对持久化值。重启服务后得到的状态
        也应与在线记录一致。
      </p>
      <button className="btn primary" disabled={busy} onClick={run}>
        {busy ? '重放中…' : '开始重放并比对'}
      </button>
      {err && <div className="banner error">{err}</div>}
      {report && (
        <div className="replay-result">
          <div className={`banner ${report.match ? 'ok' : 'error'}`}>
            {report.match
              ? `✅ 重放 ${report.events_replayed} 个事件、${report.looks_replayed} 次查看，与在线记录逐项一致`
              : `❌ 发现 ${report.discrepancies.length} 处不一致`}
          </div>
          {!report.match && (
            <ul className="field-errors">
              {report.discrepancies.map((d, i) => <li key={i}>{d}</li>)}
            </ul>
          )}
          <h4>重放终态累计</h4>
          <div className="kv-row">
            <span>对照：{report.control_conversions}/{report.control_visits}</span>
            <span>实验：{report.treatment_conversions}/{report.treatment_visits}</span>
          </div>
          <h4>重放得到的各次查看</h4>
          <table className="data-table">
            <thead>
              <tr><th>#</th><th>t</th><th>Z</th><th>±边界</th><th>结论</th></tr>
            </thead>
            <tbody>
              {report.looks.map((l) => (
                <tr key={l.look_number}>
                  <td>{l.look_number}</td>
                  <td>{formatNum(l.info_time, 4)}</td>
                  <td>{formatNum(l.z_stat, 4)}</td>
                  <td>±{formatNum(l.boundary, 4)}</td>
                  <td>{l.decision}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
