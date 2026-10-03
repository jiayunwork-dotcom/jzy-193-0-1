import React, { useCallback, useEffect, useState } from 'react'
import { api, formatNum } from '../api.js'
import BatchPanel from './BatchPanel.jsx'
import TrajectoryPanel from './TrajectoryPanel.jsx'
import LooksPanel from './LooksPanel.jsx'
import ReplayPanel from './ReplayPanel.jsx'

export default function ExperimentDetail({ experiment, onChange }) {
  const [exp, setExp] = useState(experiment)
  const [batches, setBatches] = useState([])
  const [events, setEvents] = useState([])
  const [looks, setLooks] = useState([])
  const [trajectory, setTrajectory] = useState(null)
  const [tab, setTab] = useState('trajectory')
  const [lastWarning, setLastWarning] = useState(null)

  const refreshAll = useCallback(async () => {
    const [e, bs, ev, lk, tr] = await Promise.all([
      api.getExperiment(experiment.id),
      api.listBatches(experiment.id),
      api.listEvents(experiment.id),
      api.listLooks(experiment.id),
      api.trajectory(experiment.id),
    ])
    setExp(e)
    setBatches(bs)
    setEvents(ev)
    setLooks(lk)
    setTrajectory(tr)
  }, [experiment.id])

  useEffect(() => {
    refreshAll()
  }, [refreshAll])

  async function doLook() {
    try {
      const r = await api.createLook(experiment.id, 'manual')
      setLastWarning(r.correction_warning)
    } catch (err) {
      setLastWarning(err.data?.detail || err.message)
    }
    await refreshAll()
    onChange && onChange()
  }

  async function afterBatch() {
    await refreshAll()
    onChange && onChange()
  }

  return (
    <div>
      <div className="detail-head card">
        <div>
          <h2>#{exp.id} {exp.name}</h2>
          <div className="kv-row">
            <span><b>对照</b>：{exp.control_label}</span>
            <span><b>实验</b>：{exp.treatment_label}</span>
            <span><b>基线</b>：{formatNum(exp.baseline_rate, 4)}</span>
            <span><b>目标</b>：{formatNum(exp.target_rate, 4)}</span>
            <span><b>α</b>：{exp.alpha}</span>
            <span><b>功效</b>：{exp.power}</span>
            <span className="highlight">每组 N={exp.planned_n_per_group}</span>
            {exp.concluded && <em className="tag tag-concluded">已宣布结论（历史冻结）</em>}
          </div>
        </div>
        <div className="totals-box">
          <div>累计：对照 {exp.control_conversions}/{exp.control_visits} · 实验 {exp.treatment_conversions}/{exp.treatment_visits}</div>
          <div>
            信息比例 <b>{formatNum(exp.current_info_time, 4)}</b>
            {exp.raw_info_time > 1 && (
              <span className="tag tag-warn">raw={formatNum(exp.raw_info_time, 4)} 已截断为 1</span>
            )}
          </div>
          <button className="btn primary big" onClick={doLook}>手动触发一次查看</button>
        </div>
      </div>

      {lastWarning && (
        <div className="banner warn" onClick={() => setLastWarning(null)} title="点击关闭">
          ⚠ {lastWarning}
        </div>
      )}

      <nav className="tabs">
        {[
          ['trajectory', '统计量轨迹'],
          ['looks', `查看记录 (${looks.length})`],
          ['batches', `批次 (${batches.length})`],
          ['events', `推送/更正事件 (${events.length})`],
          ['replay', '按批次重放校验'],
        ].map(([k, label]) => (
          <button key={k} className={tab === k ? 'tab active' : 'tab'} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === 'trajectory' && <TrajectoryPanel trajectory={trajectory} looks={looks} />}
      {tab === 'looks' && <LooksPanel looks={looks} exp={exp} />}
      {tab === 'batches' && (
        <BatchPanel batches={batches} events={events} experimentId={exp.id} onChanged={afterBatch} />
      )}
      {tab === 'events' && <EventsPanel events={events} />}
      {tab === 'replay' && <ReplayPanel experimentId={exp.id} />}
    </div>
  )
}

function EventsPanel({ events }) {
  return (
    <div className="card">
      <h3>推送与更正事件（不可变事件流）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>#</th><th>批次号</th><th>类型</th>
            <th>对照 访/转</th><th>实验 访/转</th><th>旧值（对照→实验 转化）</th>
            <th>备注</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          {events.map((ev) => (
            <tr key={ev.id} className={ev.event_type === 'correction' ? 'row-correction' : ''}>
              <td>{ev.id}</td>
              <td>{ev.batch_no}</td>
              <td>
                <span className={`evt evt-${ev.event_type}`}>
                  {ev.event_type === 'insert' ? '新增'
                    : ev.event_type === 'correction' ? '更正'
                    : '重复忽略'}
                </span>
              </td>
              <td>{ev.control_visits}/{ev.control_conversions}</td>
              <td>{ev.treatment_visits}/{ev.treatment_conversions}</td>
              <td>
                {ev.prior_control_conversions !== null
                  ? `${ev.prior_control_conversions} → ${ev.control_conversions} / ${ev.prior_treatment_conversions} → ${ev.treatment_conversions}`
                  : '—'}
              </td>
              <td className="note">{ev.note || ''}</td>
              <td className="muted">{new Date(ev.created_at).toLocaleString('zh-CN')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
