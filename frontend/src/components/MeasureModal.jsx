import { useEffect, useMemo, useRef, useState } from 'react'
import { REFERENCES, fmtFeet, fmtMetres } from '../lib/measureMath.js'

// MeasureModal is a photo ruler: a known object sets the scale, then two taps
// give a length. Same two-tap interaction as the iPhone Measure app — a web
// page cannot reach LiDAR, so the reference object replaces it.
//
// Points are stored as fractions of the image, so a resize never moves them.
export default function MeasureModal({ src, material, mode, calib, onCalib, initial, onApply, onClose }) {
  const imgRef = useRef(null)
  const [step, setStep] = useState(calib ? 'length' : 'calibrate')
  const [refId, setRefId] = useState('brick-190')
  const [customLength, setCustomLength] = useState('')
  const [customUnit, setCustomUnit] = useState('mm')
  const [pending, setPending] = useState([])
  const [ref, setRef] = useState(calib || null)
  const [length, setLength] = useState(initial?.length_mm ? initial.length_mm : null)
  const [width, setWidth] = useState(initial?.width_mm ? initial.width_mm : null)
  const [lengthLine, setLengthLine] = useState(null)
  const [widthLine, setWidthLine] = useState(null)

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // A custom reference is typed in whatever the tape said. Millimetres are the
  // only unit the maths uses, so convert here instead of trusting the number.
  const UNIT_MM = { mm: 1, cm: 10, in: 25.4 }
  const customMm = Number(customLength) * (UNIT_MM[customUnit] || 1)
  const refMm = refId === 'custom'
    ? (Number.isFinite(customMm) && customMm > 0 ? customMm : 0)
    : (REFERENCES.find(r => r.id === refId)?.mm || 0)
  // A zero reference silently produces a useless scale, so say why nothing
  // happens rather than ignoring the taps.
  const scaleReady = refMm > 0
  const mmPerPx = ref?.mmPerPx || 0

  const measureOf = (a, b) => {
    const img = imgRef.current
    if (!img || img.naturalWidth === 0) return 0
    const dx = (b.x - a.x) * img.naturalWidth
    const dy = (b.y - a.y) * img.naturalHeight
    return Math.hypot(dx, dy)
  }

  const tap = (e) => {
    const img = imgRef.current
    if (!img) return
    const r = img.getBoundingClientRect()
    if (!r.width || !r.height) return
    const p = {
      x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    }
    if (pending.length === 0) { setPending([p]); return }

    const a = pending[0]
    setPending([])
    const px = measureOf(a, p)
    if (px < 4) return // a slip of the finger, not a measurement

    if (step === 'calibrate') {
      if (!(refMm > 0)) return
      const next = { mmPerPx: refMm / px, refMm }
      setRef(next)
      onCalib(next)
      setStep('length')
      return
    }
    const mm = Math.round(px * mmPerPx)
    if (step === 'length') {
      setLength(mm)
      setLengthLine({ a, b: p })
      setStep(mode === 'length' ? 'done' : 'width')
      return
    }
    if (step === 'width') {
      setWidth(mm)
      setWidthLine({ a, b: p })
      setStep('done')
    }
  }

  const undo = () => {
    if (pending.length) { setPending([]); return }
    if (step === 'width') { setWidth(null); setWidthLine(null); setStep('length'); return }
    if (step === 'done') {
      if (width) { setWidth(null); setWidthLine(null); setStep('width'); return }
      setLength(null); setLengthLine(null); setStep('length'); return
    }
    if (step === 'length' && ref) { setStep('calibrate'); return }
  }

  const recalibrate = () => {
    setRef(null)
    onCalib(null)
    setStep('calibrate')
    setPending([])
  }

  const ready = length > 0 && (mode === 'length' || width > 0)

  const instruction = useMemo(() => {
    if (step === 'calibrate') {
      return scaleReady
        ? 'Tap the two ends of the known object.'
        : 'Type the real length of the reference object first.'
    }
    if (step === 'length') return `Tap the two ends of the ${material.toLowerCase()}.`
    if (step === 'width') return 'Now tap across the width.'
    return 'Size measured. Use it, or tap Undo to redo a line.'
  }, [step, material, scaleReady])

  const line = (l, color) => l && (
    <line x1={l.a.x} y1={l.a.y} x2={l.b.x} y2={l.b.y} stroke={color} strokeWidth="1.6"
      vectorEffect="non-scaling-stroke" strokeLinecap="round" />
  )

  const label = (l, text, color) => l && (
    <span className="measure-label" style={{
      left: `${((l.a.x + l.b.x) / 2) * 100}%`,
      top: `${((l.a.y + l.b.y) / 2) * 100}%`,
      borderColor: color,
    }}>{text}</span>
  )

  return (
    <div className="crop-modal measure-modal" role="dialog" aria-modal="true"
      aria-label={`Measure ${material}`} onClick={onClose}>
      <div className="crop-view measure-view" onClick={e => e.stopPropagation()}>
        <div className="measure-stage">
          <div className="measure-img-wrap">
            <img ref={imgRef} src={src} alt={`${material} photo with the measuring points`}
              onClick={tap} onDragStart={e => e.preventDefault()} draggable="false" />
            <svg className="measure-svg" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
              {line(lengthLine, '#ffd400')}
              {line(widthLine, '#ffd400')}
              {pending.length === 1 && (
                <circle cx={pending[0].x} cy={pending[0].y} r="0.012" fill="#ffd400" />
              )}
            </svg>
            {lengthLine && label(lengthLine, `${fmtMetres(length)} · ${fmtFeet(length)}`, '#ffd400')}
            {widthLine && label(widthLine, `${fmtMetres(width)} · ${fmtFeet(width)}`, '#ffd400')}
          </div>
        </div>

        <div className="measure-steps" aria-live="polite">
          <span className={step === 'calibrate' ? 'mstep on' : 'mstep'}>1 · Scale</span>
          <span className={step === 'length' ? 'mstep on' : 'mstep'}>2 · Length</span>
          <span className={step === 'width' ? 'mstep on' : 'mstep'}>3 · Width</span>
        </div>

        {step === 'calibrate' ? (
          <div className="measure-ref">
            <label>Known length
              <select value={refId} onChange={e => setRefId(e.target.value)}>
                {REFERENCES.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
                <option value="custom">Custom length…</option>
              </select>
            </label>
            {refId === 'custom' && (
              <div className="measure-custom">
                <label>Reference length
                  <input type="number" min="0" step="0.1" inputMode="decimal" value={customLength}
                    placeholder="e.g. 400" onChange={e => setCustomLength(e.target.value)} />
                </label>
                <label>Unit
                  <select value={customUnit} onChange={e => setCustomUnit(e.target.value)}>
                    <option value="mm">mm</option>
                    <option value="cm">cm</option>
                    <option value="in">inch</option>
                  </select>
                </label>
                {!scaleReady && customLength !== '' && (
                  <span className="err" role="alert">Type a length above zero.</span>
                )}
              </div>
            )}
            <span className="mono small muted">A brick, tile or sheet in the photo works best.</span>
          </div>
        ) : (
          <div className="measure-ref">
            <span className="mono small muted">
              Scale: {(ref?.mmPerPx ? ref.mmPerPx : 0).toFixed(2)} mm per pixel · reference {ref?.refMm} mm
            </span>
            <button type="button" className="crop-toggle" onClick={recalibrate}>Recalibrate</button>
          </div>
        )}

        <div className="crop-view-bar measure-bar">
          <span>{instruction}</span>
          <span className="crop-actions">
            <button type="button" className="crop-toggle" onClick={undo}>Undo</button>
            <button type="button" className="crop-toggle" onClick={onClose}>Cancel</button>
            <button type="button" className="crop-close" disabled={!ready} onClick={() => onApply({
              length_mm: Math.round(length || 0),
              ...(mode === 'length' ? {} : { width_mm: Math.round(width || 0) }),
            })}>Use size</button>
            {mode === 'volume' && (
              <span className="mono small muted measure-note">Apply the size, then type the height on the card.</span>
            )}
          </span>
        </div>
      </div>
    </div>
  )
}
