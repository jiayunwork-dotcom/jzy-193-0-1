import React, { useState } from 'react'
import { api } from '../api.js'

const EMPTY = {
  batch_no: '',
  control_visits: '',
  control_conversions: '',
  treatment_visits: '',
  treatment_conversions: '',
  is_correction: false,
}

export default function BatchPanel({ batches, events, experimentId, onChanged }) {
  const [form, setForm] = useState(EMPTY)
  const [msg, setMsg] = useState(null)
  const [errs, setErrs] = useState([])

  const set = (k) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm({ ...form, [k]: v })
  }

  async function submit(e) {
    e.preventDefault()
    setMsg(null); setErrs([])
    const body = {
      batch_no: Number(form.batch_no),
      control_visits: Number(form.control_visits),
      control_conversions: Number(form.control_conversions),
      treatment_visits: Number(form.treatment_visits),
      treatment_conversions: Number(form.treatment_conversions),
      is_correction: form.is_correction,
    }
    try {
      const r = await api.pushBatch(experimentId, body)
      setMsg({ ok: true, text: `${r.message}（事件 #${r.event_id}）` })
      setForm(EMPTY)
      onChanged()
    } catch (err) {
      if (err.data?.fields?.length) {
        setErrs(err.data.fields)
        setMsg({ ok: false, text: err.data.detail })
      } else {
        setMsg({ ok: false, text: err.message })
      }
    }
  }

  return (
    <div className="two-col">
      <form className="card" onSubmit={submit}>
        <h3>推送一批数据</h3>
        <p className="muted small">
          同一批次号重复推送且内容一致 → 幂等忽略；内容不同需勾选「这是更正」。
        </p>
        <label>批次号
          <input type="number" min="0" required value={form.batch_no} onChange={set('batch_no')} /></label>
        <div className="grid-2">
          <label>对照组访问数
            <input type="number" min="0" required value={form.control_visits} onChange={set('control_visits')} /></label>
          <label>对照组转化数
            <input type="number" min="0" required value={form.control_conversions} onChange={set('control_conversions')} /></label>
          <label>实验组访问数
            <input type="number" min="0" required value={form.treatment_visits} onChange={set('treatment_visits')} /></label>
          <label>实验组转化数
            <input type="number" min="0" required value={form.treatment_conversions} onChange={set('treatment_conversions')} /></label>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={form.is_correction} onChange={set('is_correction')} />
          这是对已推送批次的更正（将覆盖旧值，历史查看保持冻结）
        </label>
        {errs.length > 0 && (
          <ul className="field-errors">
            {errs.map((f, i) => <li key={i}><code>{f.field}</code>：{f.message}</li>)}
          </ul>
        )}
        {msg && <div className={msg.ok ? 'banner ok' : 'banner error'}>{msg.text}</div>}
        <button className="btn">推送</button>
      </form>

      <div className="card">
        <h3>当前批次（每个批次号一行最新值）</h3>
        <table className="data-table">
          <thead>
            <tr><th>批次号</th><th>对照 访/转</th><th>实验 访/转</th><th>更正次数</th><th>入库序号</th><th>最近更新</th></tr>
          </thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.batch_no} className={b.correction_count > 0 ? 'row-correction' : ''}>
                <td>{b.batch_no}</td>
                <td>{b.control_visits}/{b.control_conversions}</td>
                <td>{b.treatment_visits}/{b.treatment_conversions}</td>
                <td>{b.correction_count > 0 ? <span className="tag tag-warn">{b.correction_count}</span> : 0}</td>
                <td>{b.received_seq}</td>
                <td className="muted">{new Date(b.last_updated_at).toLocaleString('zh-CN')}</td>
              </tr>
            ))}
            {batches.length === 0 && <tr><td colSpan="6" className="muted">暂无批次</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
