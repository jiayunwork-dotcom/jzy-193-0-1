import React from 'react'
import {
  ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ReferenceLine, ResponsiveContainer, Scatter,
} from 'recharts'
import { formatNum } from '../api.js'

export default function TrajectoryPanel({ trajectory, looks }) {
  if (!trajectory) return <div className="card">加载中…</div>

  // 计划预览曲线（0.1..1.0 等距点的 LD-OBF 边界）+ 实际查看点
  const preview = trajectory.planned_preview.map((p) => ({
    t: p.info_time,
    upper: p.boundary,
    lower: p.lower_boundary,
    spend: p.cumulative_spend,
  }))

  // 实际查看轨迹单独成线
  const actual = looks.map((l) => ({
    t: l.info_time,
    z: l.z_stat,
    boundary: l.boundary,
    n: l.look_number,
    decision: l.decision,
  }))

  // 合并显示：在每个实际查看点绘制该次真实边界
  const points = actual.map((l) => ({
    t: l.t,
    z: l.z,
    actualUpper: l.boundary,
    actualLower: -l.boundary,
    label: `#${l.n}`,
    rejected: l.decision !== 'continue',
  }))

  return (
    <div className="card">
      <h3>Z 统计量轨迹与停止边界</h3>
      <p className="muted small">
        虚线为 LD-OBF 计划边界预览（不实际消耗 α）；红点为各次查看实际使用的边界
        （基于冻结的历史信息时点计算）。蓝点为当次 Z；越出红界即下结论。
        末期仅查看一次时边界严格等于 1.95996。
      </p>
      <div style={{ width: '100%', height: 460 }}>
        <ResponsiveContainer>
          <ComposedChart margin={{ top: 20, right: 30, bottom: 20, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e8e8ee" />
            <XAxis
              type="number"
              dataKey="t"
              domain={[0, 1]}
              name="信息比例"
              label={{ value: '信息比例 t', position: 'insideBottom', offset: -10 }}
            />
            <YAxis name="Z" domain={[-6, 6]} />
            <Tooltip formatter={(v, name) => [formatNum(v, 4), name]}
              labelFormatter={(t) => `t = ${formatNum(t, 4)}`} />
            <Legend />
            <ReferenceLine y={0} stroke="#999" />
            <Line
              data={preview}
              dataKey="upper"
              type="monotone"
              stroke="#d08a2e"
              strokeDasharray="6 4"
              dot={false}
              name="计划上边界（预览）"
              isAnimationActive={false}
            />
            <Line
              data={preview}
              dataKey="lower"
              type="monotone"
              stroke="#d08a2e"
              strokeDasharray="6 4"
              dot={false}
              name="计划下边界（预览）"
              isAnimationActive={false}
            />
            <Line
              data={points}
              dataKey="actualUpper"
              type="stepAfter"
              stroke="#c0392b"
              dot
              name="实际查看上边界（冻结）"
              isAnimationActive={false}
            />
            <Line
              data={points}
              dataKey="actualLower"
              type="stepAfter"
              stroke="#c0392b"
              dot
              name="实际查看下边界（冻结）"
              isAnimationActive={false}
            />
            <Line
              data={points}
              dataKey="z"
              type="monotone"
              stroke="#1f66c1"
              strokeWidth={2.5}
              name="Z 统计量"
              isAnimationActive={false}
              label={{ dataKey: 'label', position: 'top', fontSize: 11, fill: '#1f66c1' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <h4>累计 α 消耗预览</h4>
      <div style={{ width: '100%', height: 200 }}>
        <ResponsiveContainer>
          <ComposedChart data={preview} margin={{ top: 10, right: 30, bottom: 20, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e8e8ee" />
            <XAxis dataKey="t" type="number" domain={[0, 1]}
              label={{ value: '信息比例 t', position: 'insideBottom', offset: -10 }} />
            <YAxis domain={[0, trajectory.alpha]} tickFormatter={(v) => v.toFixed(3)} />
            <Tooltip formatter={(v) => formatNum(v, 6)} labelFormatter={(t) => `t = ${t}`} />
            <ReferenceLine y={trajectory.alpha} stroke="#c0392b" strokeDasharray="4 4"
              label={{ value: `总 α=${trajectory.alpha}`, position: 'right' }} />
            <Line dataKey="spend" stroke="#2e7d32" dot name="累计消耗 α*(t)" isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
