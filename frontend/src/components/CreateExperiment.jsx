import React, { useState } from 'react'
import { api } from '../api.js'

const DEFAULTS = {
  name: '',
  baseline_rate: '0.10',
  target_rate: '0.12',
  alpha: '0.05',
  power: '0.8',
}

export default function CreateExperiment({ onCreated }) {
  const [form, setForm] = useState(DEFAULTS)
  const [errors, setErrors] = useState([])
  const [busy, setBusy] = useState(false)

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setErrors([])
    try {
      const body = {
        name: form.name.trim() || `实验 ${new Date().toLocaleString('zh-CN')}`,
        baseline_rate: Number(form.baseline_rate),
        target_rate: Number(form.target_rate),
        alpha: Number(form.alpha),
        power: Number(form.power),
      }
      const created = await api.createExperiment(body)
      setForm(DEFAULTS)
      onCreated(created)
    } catch (err) {
      setErrors(err.data?.fields || [{ field: 'body', message: err.message }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card create-form" onSubmit={submit}>
      <h3>新建实验</h3>
      <label>
        名称
        <input value={form.name} onChange={set('name')} placeholder="例如：落地页改版 A/B" />
      </label>
      <div className="grid-2">
        <label>
          基线转化率
          <input type="number" step="0.01" min="0" max="1" value={form.baseline_rate} onChange={set('baseline_rate')} />
        </label>
        <label>
          目标转化率
          <input type="number" step="0.01" min="0" max="1" value={form.target_rate} onChange={set('target_rate')} />
        </label>
        <label>
          双侧 α
          <input type="number" step="0.01" min="0" max="1" value={form.alpha} onChange={set('alpha')} />
        </label>
        <label>
          功效 1−β
          <input type="number" step="0.01" min="0" max="1" value={form.power} onChange={set('power')} />
        </label>
      </div>
      {errors.length > 0 && (
        <ul className="field-errors">
          {errors.map((f, i) => (
            <li key={i}><code>{f.field}</code>：{f.message}</li>
          ))}
        </ul>
      )}
      <button className="btn primary" disabled={busy}>{busy ? '提交中…' : '创建并计算样本量'}</button>
    </form>
  )
}
