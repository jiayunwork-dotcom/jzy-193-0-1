import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { api, formatNum } from './api.js'
import CreateExperiment from './components/CreateExperiment.jsx'
import ExperimentDetail from './components/ExperimentDetail.jsx'

export default function App() {
  const [experiments, setExperiments] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const list = await api.listExperiments()
      setExperiments(list)
      setError(null)
      if (selectedId !== null && !list.some((e) => e.id === selectedId)) {
        setSelectedId(null)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [selectedId])

  useEffect(() => {
    refresh()
  }, [])

  const selected = useMemo(
    () => experiments.find((e) => e.id === selectedId) || null,
    [experiments, selectedId],
  )

  return (
    <div className="app">
      <header className="topbar">
        <h1>成组序贯实验监测</h1>
        <span className="subtitle">
          Lan-DeMets O'Brien-Fleming α 消耗 · 双侧 · 历史查看冻结
        </span>
      </header>

      {error && <div className="banner error">接口错误：{error}</div>}

      <div className="layout">
        <aside className="sidebar">
          <CreateExperiment onCreated={async (e) => {
            await refresh()
            setSelectedId(e.id)
          }} />
          <div className="exp-list">
            <h3>实验列表</h3>
            {loading && <div className="muted">加载中…</div>}
            {!loading && experiments.length === 0 && (
              <div className="muted">还没有实验，先在上方创建一个。</div>
            )}
            {experiments.map((e) => (
              <button
                key={e.id}
                className={`exp-item ${selectedId === e.id ? 'active' : ''}`}
                onClick={() => setSelectedId(e.id)}
              >
                <span className="exp-name">#{e.id} {e.name}</span>
                <span className="exp-meta">
                  N={e.planned_n_per_group}/组 · {e.looks_done} 次查看
                  {e.concluded && <em className="tag tag-concluded">已越界</em>}
                </span>
              </button>
            ))}
          </div>
        </aside>

        <main className="content">
          {selected ? (
            <ExperimentDetail key={selected.id} experiment={selected} onChange={refresh} />
          ) : (
            <div className="empty">
              <h2>使用说明</h2>
              <ol>
                <li>左侧录入基线/目标转化率、α 与功效，系统给出每组所需样本量（参考：10%→12%、α=0.05、功效 0.8 → <b>3841</b>）。</li>
                <li>在实验详情页按批次推送两组的新增访问/转化数；同批次号重复推送幂等忽略，更正需显式声明。</li>
                <li>手动触发查看，轨迹图叠加停止边界与各次查看点；信息比例 &gt;1 自动截断并标注。</li>
                <li>所有边界计算在后端完成，结果确定可重复；可用「按批次重放」逐项比对。</li>
              </ol>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
