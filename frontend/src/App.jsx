import React, { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import TrajectoryChart from './TrajectoryChart.jsx'

const fmt = (x, d = 4) =>
  x === null || x === undefined ? '—' : Number(x).toFixed(d)
const pct = (x, d = 2) => (x === null || x === undefined ? '—' : `${(Number(x) * 100).toFixed(d)}%`)

function StatusBadge({ exp }) {
  if (exp.status !== 'stopped') return <span className="badge running">监测中</span>
  const cls = exp.conclusion === 'a_wins' ? 'stopped-a' : 'stopped-b'
  const label = exp.conclusion === 'a_wins' ? 'A 组胜出' : 'B 组胜出'
  return <span className={`badge ${cls}`}>已停止 · {label}</span>
}

function ErrorText({ errors, field }) {
  return errors?.[field] ? <div className="field-err">{errors[field]}</div> : null
}

// ---------------------------------------------------------------------------
// 新建实验
// ---------------------------------------------------------------------------

function CreateExperiment({ onCreated }) {
  const [form, setForm] = useState({
    name: '', baseline_rate: '0.10', target_rate: '0.12',
    alpha: '0.05', power: '0.80',
  })
  const [errors, setErrors] = useState(null)
  const [busy, setBusy] = useState(false)

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setErrors(null)
    try {
      const payload = {
        name: form.name,
        baseline_rate: parseFloat(form.baseline_rate),
        target_rate: parseFloat(form.target_rate),
        alpha: parseFloat(form.alpha),
        power: parseFloat(form.power),
        spending_rule: 'obf',
      }
      const created = await api.createExperiment(payload)
      onCreated(created.id)
    } catch (err) {
      setErrors(err.errors || { form: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <h2>新建实验</h2>
      <form onSubmit={submit}>
        <label>实验名称</label>
        <input className={errors?.name ? 'invalid' : ''} value={form.name}
          onChange={set('name')} placeholder="例如：落地页改版-10月" />
        <ErrorText errors={errors} field="name" />
        <label>基线转化率 (0,1)</label>
        <input className={errors?.baseline_rate ? 'invalid' : ''}
          value={form.baseline_rate} onChange={set('baseline_rate')} />
        <ErrorText errors={errors} field="baseline_rate" />
        <label>目标转化率 (0,1，不能等于基线)</label>
        <input className={errors?.target_rate ? 'invalid' : ''}
          value={form.target_rate} onChange={set('target_rate')} />
        <ErrorText errors={errors} field="target_rate" />
        <div className="row">
          <div style={{ flex: 1 }}>
            <label>双侧显著性水平 α</label>
            <input className={errors?.alpha ? 'invalid' : ''}
              value={form.alpha} onChange={set('alpha')} />
            <ErrorText errors={errors} field="alpha" />
          </div>
          <div style={{ flex: 1 }}>
            <label>功效 1-β</label>
            <input className={errors?.power ? 'invalid' : ''}
              value={form.power} onChange={set('power')} />
            <ErrorText errors={errors} field="power" />
          </div>
        </div>
        <div style={{ marginTop: 14 }}>
          <button disabled={busy} type="submit">
            {busy ? '计算样本量并创建…' : '计算样本量并创建'}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          α 消耗规则：O'Brien-Fleming（Lan-DeMets 近似）——早期保守，
          t=0.5 累计消耗约 0.00557；终局 t=1 恰好 0.05。
        </p>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 推送批次
// ---------------------------------------------------------------------------

function BatchForm({ experimentId, onPushed }) {
  const empty = { batch_no: '', group_a_visits: '', group_a_conv: '',
    group_b_visits: '', group_b_conv: '', note: '' }
  const [form, setForm] = useState(empty)
  const [errors, setErrors] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErrors(null); setNotice(null)
    try {
      const payload = {
        batch_no: parseInt(form.batch_no, 10),
        group_a_visits: parseInt(form.group_a_visits, 10),
        group_a_conv: parseInt(form.group_a_conv, 10),
        group_b_visits: parseInt(form.group_b_visits, 10),
        group_b_conv: parseInt(form.group_b_conv, 10),
        note: form.note || undefined,
      }
      const r = await api.pushBatch(experimentId, payload)
      setNotice(r)
      if (r.action !== 'duplicate_ignored') setForm(empty)
      onPushed()
    } catch (err) {
      if (err.status === 422) setErrors(err.errors)
      else setErrors({ form: err.message })
    } finally {
      setBusy(false)
    }
  }

  const fields = [
    ['group_a_visits', 'A 组新增访问数'], ['group_a_conv', 'A 组新增转化数'],
    ['group_b_visits', 'B 组新增访问数'], ['group_b_conv', 'B 组新增转化数'],
  ]

  return (
    <div className="panel">
      <h2>推送批次 / 更正</h2>
      {notice && (
        <div className={`alert ${notice.action === 'corrected' ? 'warn' : 'info'}`}>
          <div>{notice.message ||
            (notice.action === 'created' ? `批次 ${notice.batch_no} 已接收（第 1 版）。` : '')}</div>
          {notice.frozen && (
            <div style={{ marginTop: 4 }}>
              ⚠ 该实验已冻结结论；更正不改变历史查看，只影响后续查看。
            </div>
          )}
        </div>
      )}
      {errors?.experiment_id && <div className="alert error">{errors.experiment_id}</div>}
      <form onSubmit={submit}>
        <label>批次号（同号重推幂等；不同内容视为更正）</label>
        <input className={errors?.batch_no ? 'invalid' : ''}
          value={form.batch_no} onChange={set('batch_no')} />
        <ErrorText errors={errors} field="batch_no" />
        <div className="row" style={{ alignItems: 'flex-start' }}>
          {fields.map(([k, label]) => (
            <div key={k} style={{ flex: 1, minWidth: 130 }}>
              <label>{label}</label>
              <input className={errors?.[k] ? 'invalid' : ''}
                value={form[k]} onChange={set(k)} />
              <ErrorText errors={errors} field={k} />
            </div>
          ))}
        </div>
        <label>备注（可选，更正时建议填写原因）</label>
        <input value={form.note} onChange={set('note')} />
        <div style={{ marginTop: 12 }}>
          <button disabled={busy} type="submit">
            {busy ? '推送中…' : '推送批次'}
          </button>
        </div>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 实验详情
// ---------------------------------------------------------------------------

function ExperimentDetail({ expId, onChanged }) {
  const [tab, setTab] = useState('trajectory')
  const [traj, setTraj] = useState(null)
  const [batches, setBatches] = useState([])
  const [corrections, setCorrections] = useState([])
  const [replayResult, setReplayResult] = useState(null)
  const [viewNotice, setViewNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const [t, b, c] = await Promise.all([
        api.trajectory(expId), api.listBatches(expId), api.listCorrections(expId),
      ])
      setTraj(t); setBatches(b); setCorrections(c)
      onChanged()
    } catch (e) { setError(e.message) }
  }, [expId, onChanged])

  useEffect(() => { refresh() }, [refresh])

  const doView = async () => {
    setBusy(true); setViewNotice(null)
    try {
      const v = await api.createView(expId, 'manual')
      setViewNotice(v)
      await refresh()
    } catch (e) {
      if (e.status === 409) setViewNotice({ conflict: e.message })
      else setError(e.message)
    } finally { setBusy(false) }
  }

  const doReplay = async () => {
    setReplayResult(null)
    const r = await api.replay(expId)
    setReplayResult(r)
  }

  if (!traj) return <div className="panel">加载中… {error}</div>
  const points = traj.points

  return (
    <div>
      <div className="panel">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div>
            <h2 style={{ marginBottom: 6 }}>实验 {expId}</h2>
            <StatusBadge exp={traj} />
          </div>
          <div className="row">
            <button disabled={busy} onClick={doView}>
              {busy ? '计算中…' : '手动触发一次查看'}
            </button>
            <button className="ghost" onClick={doReplay}>从头重放校验</button>
            <button className="ghost" onClick={refresh}>刷新</button>
          </div>
        </div>
        {viewNotice?.conflict && <div className="alert error">{viewNotice.conflict}</div>}
        {viewNotice && !viewNotice.conflict && (
          <div className={`alert ${viewNotice.crossed ? 'ok' : 'info'}`} style={{ marginTop: 12 }}>
            第 {viewNotice.seq} 次查看：t={fmt(viewNotice.info_fraction, 4)}
            {viewNotice.capped ? '（超过 1，已按 1 处理）' : ''}
            ，z = <span className="mono">{fmt(viewNotice.z_value, 4)}</span>
            ，边界 ±<span className="mono">{fmt(viewNotice.boundary, 4)}</span>
            {viewNotice.crossed
              ? ` → 越过边界，结论：${viewNotice.conclusion === 'a_wins' ? 'A 组胜出' : 'B 组胜出'}`
              : ' → 未越过边界'}
          </div>
        )}
        {(viewNotice?.warnings || []).map((w, i) => (
          <div key={i} className="alert warn">{w}</div>
        ))}
        {replayResult && (
          <div className={`alert ${replayResult.all_match ? 'ok' : 'error'}`}>
            重放完成：{replayResult.replayed_batches} 条批次事件、
            {replayResult.replayed_views} 次查看，
            {replayResult.all_match
              ? '每次查看的边界、z 与结论与在线时逐项一致 ✔'
              : '存在不一致，请核对 views 明细！'}
          </div>
        )}
      </div>

      <div className="tabs">
        <button className={tab === 'trajectory' ? 'active' : ''}
          onClick={() => setTab('trajectory')}>统计量轨迹 / 查看记录</button>
        <button className={tab === 'batches' ? 'active' : ''}
          onClick={() => setTab('batches')}>批次明细</button>
        <button className={tab === 'corrections' ? 'active' : ''}
          onClick={() => setTab('corrections')}>推送与更正流水</button>
      </div>

      {tab === 'trajectory' && (
        <>
          <div className="panel">
            <h2>统计量轨迹（信息比例 t → z）</h2>
            {points.length === 0 ? (
              <div className="muted">还没有查看记录。先推送批次，再点「手动触发一次查看」。</div>
            ) : (
              <>
                <TrajectoryChart points={points} fixedBoundary={traj.fixed_boundary} />
                <div className="kv" style={{ marginTop: 10 }}>
                  <div className="item">
                    <div className="k">每组计划样本量</div>
                    <div className="v">{traj.n_per_group}</div>
                  </div>
                  <div className="item">
                    <div className="k">总显著性水平 α</div>
                    <div className="v">{traj.total_alpha}</div>
                  </div>
                  <div className="item">
                    <div className="k">已消耗 α（最后查看）</div>
                    <div className="v mono">
                      {points.length ? fmt(points[points.length - 1].spent_at, 5) : '—'}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
          <div className="panel">
            <h2>每次查看明细</h2>
            <table>
              <thead>
                <tr>
                  <th>#</th><th>触发</th><th>累计 (A/B 访问·转化)</th>
                  <th>t (原值/使用)</th><th>z</th><th>已用 α</th><th>边界 ±c</th>
                  <th>判定</th><th>时间 (UTC)</th>
                </tr>
              </thead>
              <tbody>
                {points.map((p) => (
                  <tr key={p.seq}>
                    <td>{p.seq}</td>
                    <td>{p.trigger === 'manual' ? '手动' : '定时'}</td>
                    <td className="mono">
                      {p.total_a_visits}·{p.total_a_conv} / {p.total_b_visits}·{p.total_b_conv}
                    </td>
                    <td className="mono">
                      {fmt(p.info_fraction_raw, 4)}
                      {p.capped
                        ? ' ⚠超1→1.0000'
                        : p.info_fraction - p.info_fraction_raw > 1e-9
                          ? ` ↩回落→${fmt(p.info_fraction, 4)}`
                          : ` / ${fmt(p.info_fraction, 4)}`}
                    </td>
                    <td className={`mono ${p.z_value >= 0 ? 'pos' : 'neg'}`}>
                      {fmt(p.z_value, 4)}
                    </td>
                    <td className="mono">{fmt(p.spent_at, 5)}</td>
                    <td className="mono">{fmt(p.boundary, 4)}</td>
                    <td>
                      {p.crossed
                        ? <span className={p.z_value > 0 ? 'pos' : 'neg'}>
                            越界 · {p.conclusion === 'a_wins' ? 'A 胜' : 'B 胜'}
                          </span>
                        : <span className="muted">继续</span>}
                    </td>
                    <td className="muted">{p.created_at?.replace('T', ' ').slice(0, 19)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === 'batches' && (
        <div>
          <BatchForm experimentId={expId} onPushed={refresh} />
          <div className="panel">
            <h2>批次当前生效数据</h2>
          <table>
            <thead>
              <tr>
                <th>批次号</th><th>A 访问</th><th>A 转化</th><th>A 转化率</th>
                <th>B 访问</th><th>B 转化</th><th>B 转化率</th><th>当前版本</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => (
                <tr key={b.batch_no} className={b.version > 1 ? 'correction' : ''}>
                  <td>{b.batch_no}</td>
                  <td>{b.group_a_visits}</td><td>{b.group_a_conv}</td>
                  <td>{pct(b.group_a_conv / b.group_a_visits)}</td>
                  <td>{b.group_b_visits}</td><td>{b.group_b_conv}</td>
                  <td>{pct(b.group_b_conv / b.group_b_visits)}</td>
                  <td>v{b.version}{b.version > 1 ? '（含更正）' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}

      {tab === 'corrections' && (
        <div className="panel">
          <h2>推送与更正流水（不可变审计记录）</h2>
          <table>
            <thead>
              <tr>
                <th>批次号</th><th>版本</th><th>类型</th>
                <th>A 访问</th><th>A 转化</th><th>B 访问</th><th>B 转化</th>
                <th>备注</th><th>时间 (UTC)</th>
              </tr>
            </thead>
            <tbody>
              {corrections.map((v) => (
                <tr key={`${v.batch_no}-${v.version}`}
                  className={v.kind === 'correction' ? 'correction' : ''}>
                  <td>{v.batch_no}</td>
                  <td>v{v.version}</td>
                  <td>{v.kind === 'push' ? '首次推送' : <b>更正</b>}</td>
                  <td>{v.group_a_visits}</td><td>{v.group_a_conv}</td>
                  <td>{v.group_b_visits}</td><td>{v.group_b_conv}</td>
                  <td>{v.note || '—'}</td>
                  <td className="muted">{v.created_at?.replace('T', ' ').slice(0, 19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const [experiments, setExperiments] = useState([])
  const [selected, setSelected] = useState(null)

  const loadList = useCallback(async () => {
    const list = await api.listExperiments()
    setExperiments(list)
  }, [])

  useEffect(() => { loadList() }, [loadList])

  return (
    <div>
      <header className="topbar">
        <h1>A/B 实验监测系统</h1>
        <span className="sub">
          预设 α 与样本量 · O'Brien-Fleming α 消耗 · 多查看相关边界 · 结论冻结
        </span>
      </header>
      <div className="layout">
        <aside className="sidebar">
          <CreateExperiment onCreated={(id) => { setSelected(id); loadList() }} />
          <h2 style={{ fontSize: 14, margin: '16px 0 8px' }}>实验列表</h2>
          {experiments.map((e) => (
            <div key={e.id}
              className={`exp-item ${selected === e.id ? 'active' : ''}`}
              onClick={() => setSelected(e.id)}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <span className="name">{e.name}</span>
                <StatusBadge exp={e} />
              </div>
              <div className="meta mono">
                {e.id} · 每组 n={e.n_per_group} · α={e.alpha}
              </div>
            </div>
          ))}
          {experiments.length === 0 && <div className="muted">还没有实验。</div>}
        </aside>
        <main className="content">
          {selected ? (
            <ExperimentDetail
              key={selected}
              expId={selected}
              onChanged={loadList}
            />
          ) : (
            <div className="panel muted">
              从左侧创建实验，或选择一个实验查看轨迹、推送批次、手动触发查看。
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
