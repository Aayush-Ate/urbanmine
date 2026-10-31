import { useEffect, useMemo, useRef, useState } from 'react'
import { REFERENCES, fmtFeet, fmtMetres } from '../lib/measureMath.js'

// MeasureModal is a photo ruler: a known object sets the scale, then two taps
// give a length. It is the closest a web page gets to the iPhone Measure app --
// a browser cannot reach LiDAR or ARKit, so a reference object replaces them.
//
// The ends stay draggable. After a line is placed you can drag either end and
// the number follows your finger, which is what makes it feel live instead of
// like typing numbers into a form.
//
// Points are stored as fractions of the image, so a resize never moves them.
const HIT = 0.035 // how near (as a fraction of the image) counts as grabbing an end

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
  // drag names the end under the finger: 'length-a', 'length-b', 'width-a' or 'pending'
  const [drag, setDrag] = useState(null)
  // cursor follows the pointer so a half-drawn line shows a running measurement
  const [cursor, setCursor] = useState(null)

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

  // Pixel distance in the original photo, not on screen, so the scale holds at
  // any zoom or window size.
  const measureOf = (a, b) => {
    const img = imgRef.current
    if (!img || img.naturalWidth === 0 || !a || !b) return 0
    const dx = (b.x - a.x) * img.naturalWidth
    const dy = (b.y - a.y) * img.naturalHeight
    return Math.hypot(dx, dy)
  }
  const mmOf = (line) => (line && mmPerPx > 0 ? Math.round(measureOf(line.a, line.b) * mmPerPx) : 0)

  const pointAt = (e) => {
    const img = imgRef.current
    if (!img) return null
    const r = img.getBoundingClientRect()
    if (!r.width || !r.height) return null
    return {
      x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    }
  }

  // Ends already on the photo, so a touch near one grabs it instead of starting
  // a new line. This is the whole "drag the dot" interaction.
  const nearestEnd = (p) => {
    const ends = []
    if (lengthLine) ends.push({ id: 'length-a', p: lengthLine.a }, { id: 'length-b', p: lengthLine.b })
    if (widthLine) ends.push({ id: 'width-a', p: widthLine.a }, { id: 'width-b', p: widthLine.b })
    if (pending.length === 1) ends.push({ id: 'pending', p: pending[0] })
    let hit = null
    let best = HIT
    for (const end of ends) {
      const d = Math.hypot(end.p.x - p.x, end.p.y - p.y)
      if (d <= best) { hit = end.id; best = d }
    }
    return hit
  }

  const moveTo = (id, p) => {
    if (id === 'pending') { setPending([p]); return }
    if (id === 'length-a' || id === 'length-b') {
      const next = { ...lengthLine, [id === 'length-a' ? 'a' : 'b']: p }
      setLengthLine(next)
      setLength(mmOf(next))
      return
    }
    const next = { ...widthLine, [id === 'width-a' ? 'a' : 'b']: p }
    setWidthLine(next)
    setWidth(mmOf(next))
  }

  // Second tap: the scale is set, or the line is committed.
  const tapAt = (p) => {
    if (pending.length === 0) { setPending([p]); return }
    const a = pending[0]
    setPending([])
    const px = measureOf(a, p)
    if (px < 4) return // a slip of the finger, not a measurement

    if (step === 'calibrate') {
      if (!scaleReady) return
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

  const onDown = (e) => {
    const p = pointAt(e)
    if (!p) return
    const hit = nearestEnd(p)
    if (hit) {
      setDrag(hit)
      setCursor(p)
      e.currentTarget.setPointerCapture?.(e.pointerId)
      return
    }
    tapAt(p)
    setCursor(p)
  }

  const onMove = (e) => {
    const p = pointAt(e)
    if (!p) return
    setCursor(p)
    if (drag) moveTo(drag, p)
  }

  const onUp = (e) => {
    setDrag(null)
    e.currentTarget.releasePointerCapture?.(e.pointerId)
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
    if (step === 'length') return `Tap the two ends of the ${material.toLowerCase()}, then drag an end to fine-tune.`
    if (step === 'width') return 'Now tap across the width.'
    return 'Size measured. Drag an end to adjust, or tap Undo to redo a line.'
  }, [step, material, scaleReady])

  const line = (l, dashed) => l && (
    <line x1={l.a.x} y1={l.a.y} x2={l.b.x} y2={l.b.y} stroke="#ffd400" strokeWidth="1.6"
      vectorEffect="non-scaling-stroke" strokeLinecap="round"
      {...(dashed ? { strokeDasharray: '6 5' } : {})} />
  )

  const end = (p) => p && (
    <circle cx={p.x} cy={p.y} r="0.013" fill="#ffd400" stroke="#1f1f1f" strokeWidth="0.004"
      vectorEffect="non-scaling-stroke" />
  )

  const label = (l, text) => l && (
    <span className="measure-label" style={{
      left: `${((l.a.x + l.b.x) / 2) * 100}%`,
      top: `${((l.a.y + l.b.y) / 2) * 100}%`,
    }}>{text}</span>
  )

  // A line being dragged, or one half-drawn, reads out live.
  const preview = pending.length === 1 && cursor ? { a: pending[0], b: cursor } : null
  const previewMm = mmOf(preview)

  return (
    <div className="crop-modal measure-modal" role="dialog" aria-modal="true"
      aria-label={`Measure ${material}`} onClick={onClose}>
      <div className="crop-view measure-view" onClick={e => e.stopPropagation()}>
        <div className="measure-stage">
          <div className="measure-img-wrap"
            onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
            onPointerLeave={() => { if (!drag) setCursor(null) }}>
            <img ref={imgRef} src={src} alt={`${material} photo with the measuring points`}
              onDragStart={e => e.preventDefault()} draggable="false" />
            <svg className="measure-svg" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
              {line(lengthLine)}
              {line(widthLine)}
              {preview && line(preview, true)}
              {end(lengthLine?.a)}{end(lengthLine?.b)}
              {end(widthLine?.a)}{end(widthLine?.b)}
              {pending.length === 1 && end(pending[0])}
            </svg>
            {lengthLine && label(lengthLine, `${fmtMetres(length)} · ${fmtFeet(length)}`)}
            {widthLine && label(widthLine, `${fmtMetres(width)} · ${fmtFeet(width)}`)}
            {preview && previewMm > 0 && label(preview, `${fmtMetres(previewMm)} · ${fmtFeet(previewMm)}`)}
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
