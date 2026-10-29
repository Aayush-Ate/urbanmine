// Dimension maths for the photo ruler.
// Millimetres are the only internal unit. Feet and metres are display choices.

export const MM_PER_FT = 304.8
const MM_PER_IN = 25.4
const SQFT_MM2 = MM_PER_FT * MM_PER_FT
const CUFT_MM3 = MM_PER_FT ** 3

// A known object in the photo sets the scale — the same idea as the reference
// sheet in the iPhone Measure app, except the reference is already on site.
export const REFERENCES = [
  { id: 'brick-190', label: 'Brick, long edge — 190 mm', mm: 190 },
  { id: 'brick-90', label: 'Brick, short edge — 90 mm', mm: 90 },
  { id: 'tile-600', label: 'Tile or paver — 600 mm', mm: 600 },
  { id: 'ply-2440', label: 'Plywood sheet, 8 ft — 2440 mm', mm: 2440 },
  { id: 'door-2130', label: 'Door height, 7 ft — 2130 mm', mm: 2130 },
  { id: 'window-1220', label: 'Window width, 4 ft — 1220 mm', mm: 1220 },
]

const round1 = (n) => Math.round(n * 10) / 10

export const toMm = (value, unit) => {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return 0
  return Math.round(unit === 'm' ? n * 1000 : n * MM_PER_FT)
}

export const fromMm = (mm, unit) => {
  const n = Number(mm)
  if (!Number.isFinite(n) || n <= 0) return ''
  const v = unit === 'm' ? n / 1000 : n / MM_PER_FT
  return String(round1(v))
}

export const sqFt = (l, w) => (l > 0 && w > 0 ? (l * w) / SQFT_MM2 : 0)
export const cuFt = (l, w, h) => (l > 0 && w > 0 && h > 0 ? (l * w * h) / CUFT_MM3 : 0)

// The quantity a listing stores, in the material's own unit.
export function measuredQuantity(mode, dims) {
  if (!dims) return null
  if (mode === 'area') {
    const v = sqFt(dims.length_mm, dims.width_mm)
    return v > 0 ? round1(v) : null
  }
  if (mode === 'volume') {
    const v = cuFt(dims.length_mm, dims.width_mm, dims.height_mm)
    return v > 0 ? round1(v) : null
  }
  if (mode === 'length') return dims.length_mm > 0 ? round1(dims.length_mm / 1000) : null
  if (mode === 'weight') return dims.kg > 0 ? round1(dims.kg) : null
  if (mode === 'pieces') return dims.pieces > 0 ? Math.round(dims.pieces) : null
  return null
}

// 7′ 2″ — the way a site talks about a plank.
export function fmtFeet(mm) {
  const n = Number(mm)
  if (!Number.isFinite(n) || n <= 0) return '—'
  const totalIn = n / MM_PER_IN
  const ft = Math.floor(totalIn / 12)
  const inch = Math.round(totalIn - ft * 12)
  if (inch === 12) return `${ft + 1}′`
  return ft ? `${ft}′ ${inch}″` : `${inch}″`
}

export const fmtMetres = (mm) => {
  const n = Number(mm)
  return Number.isFinite(n) && n > 0 ? `${(n / 1000).toFixed(2)} m` : '—'
}

// One short line for the listing card and the preview.
export function describeDims(mode, dims) {
  if (!dims) return ''
  if (mode === 'weight') return dims.kg > 0 ? `${round1(dims.kg)} kg` : ''
  if (mode === 'pieces') return dims.pieces > 0 ? `${Math.round(dims.pieces)} pcs` : ''
  const bits = [dims.length_mm, dims.width_mm]
  if (mode === 'volume') bits.push(dims.height_mm)
  if (!bits.every((v) => v > 0)) return ''
  return bits.map(fmtFeet).join(' × ')
}
