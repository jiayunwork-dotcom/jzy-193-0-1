import React from 'react'

// 纯 SVG 轨迹图：z 统计量随信息比例推进，叠加每次查看的 ±边界（步进折线）。
export default function TrajectoryChart({ points, fixedBoundary }) {
  const W = 860
  const H = 420
  const M = { top: 30, right: 24, bottom: 46, left: 52 }
  const iw = W - M.left - M.right
  const ih = H - M.top - M.bottom

  const xs = (t) => M.left + t * iw
  // 纵轴范围覆盖边界与 z
  const maxZ = Math.max(
    fixedBoundary,
    ...points.map((p) => Math.abs(p.z_value) || 0),
    ...points.map((p) => p.boundary || 0),
    0.5,
  )
  const yMax = Math.ceil(maxZ * 1.2 * 10) / 10
  const ys = (z) => M.top + ih / 2 - (z / yMax) * (ih / 2)

  const yTicks = []
  for (let v = -Math.ceil(yMax); v <= Math.ceil(yMax); v += 1) {
    if (Math.abs(v) <= yMax + 0.01) yTicks.push(v)
  }

  // 边界按「查看点之间水平延伸」的步进折线绘制（边界只在查看点上定义）
  const stepPath = (key, sign = 1) => {
    if (!points.length) return ''
    let d = ''
    points.forEach((p, i) => {
      const x = xs(p.info_fraction)
      const y = ys(sign * p[key])
      if (i === 0) {
        d += `M ${xs(0)} ${y} L ${x} ${y}`
      } else {
        d += ` L ${x} ${ys(sign * points[i - 1][key])} L ${x} ${y}`
      }
      if (i === points.length - 1) d += ` L ${xs(1)} ${y}`
    })
    return d
  }

  const zPath = points.length
    ? points
        .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xs(p.info_fraction)} ${ys(p.z_value)}`)
        .join(' ')
    : ''

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W }}>
      {/* 网格与 y 轴刻度 */}
      {yTicks.map((v) => (
        <g key={v}>
          <line
            x1={M.left} x2={M.left + iw} y1={ys(v)} y2={ys(v)}
            stroke={v === 0 ? '#9ca3af' : '#eef0f3'} strokeWidth={v === 0 ? 1.2 : 1}
          />
          <text x={M.left - 8} y={ys(v) + 4} textAnchor="end" fontSize="11" fill="#6b7280">
            {v}
          </text>
        </g>
      ))}
      {/* x 轴刻度 */}
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <g key={t}>
          <line x1={xs(t)} x2={xs(t)} y1={M.top} y2={M.top + ih} stroke="#f3f4f6" />
          <text x={xs(t)} y={H - M.bottom + 20} textAnchor="middle" fontSize="11" fill="#6b7280">
            {t.toFixed(2)}
          </text>
        </g>
      ))}
      <text x={M.left + iw / 2} y={H - 6} textAnchor="middle" fontSize="12" fill="#374151">
        信息比例 t
      </text>
      <text x={14} y={M.top + ih / 2} textAnchor="middle" fontSize="12" fill="#374151"
        transform={`rotate(-90 14 ${M.top + ih / 2})`}>
        z 统计量
      </text>

      {/* 固定样本参考 ±1.96 */}
      <line x1={M.left} x2={M.left + iw} y1={ys(fixedBoundary)} y2={ys(fixedBoundary)}
        stroke="#9ca3af" strokeDasharray="5 4" strokeWidth="1" />
      <line x1={M.left} x2={M.left + iw} y1={ys(-fixedBoundary)} y2={ys(-fixedBoundary)}
        stroke="#9ca3af" strokeDasharray="5 4" strokeWidth="1" />
      <text x={M.left + iw - 4} y={ys(fixedBoundary) - 5} textAnchor="end" fontSize="10" fill="#6b7280">
        固定样本 ±1.96
      </text>

      {/* 上下停止边界（步进） */}
      <path d={stepPath('boundary', 1)} fill="none" stroke="#dc2626" strokeWidth="2" />
      <path d={stepPath('boundary', -1)} fill="none" stroke="#dc2626" strokeWidth="2" />

      {/* z 轨迹 */}
      <path d={zPath} fill="none" stroke="#2563eb" strokeWidth="2.2" />
      {points.map((p) => (
        <g key={p.seq}>
          <circle cx={xs(p.info_fraction)} cy={ys(p.z_value)} r="4.5"
            fill={p.crossed ? '#dc2626' : '#2563eb'} stroke="#fff" strokeWidth="1.5" />
          <text x={xs(p.info_fraction)} y={ys(p.z_value) - 10} textAnchor="middle"
            fontSize="10" fill="#374151">
            #{p.seq}
          </text>
        </g>
      ))}

      {/* 图例 */}
      <g fontSize="11" fill="#374151">
        <line x1={M.left} x2={M.left + 22} y1={14} y2={14} stroke="#dc2626" strokeWidth="2" />
        <text x={M.left + 28} y={18}>停止边界 ±cₖ</text>
        <line x1={M.left + 130} x2={M.left + 152} y1={14} y2={14} stroke="#2563eb" strokeWidth="2.2" />
        <text x={M.left + 158} y={18}>z 统计量</text>
        <line x1={M.left + 230} x2={M.left + 252} y1={14} y2={14}
          stroke="#9ca3af" strokeDasharray="5 4" />
        <text x={M.left + 258} y={18}>±1.96 参考</text>
      </g>
    </svg>
  )
}
