// UrbanMine Frontend — simple, one file.
// React + Vite. Five tabs, each does one thing.
// GSAP motions on sidebar and tab switches, kept minimal.

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import exifr from 'exifr'
import LocationPicker from './LocationPicker.jsx'
import { createViewer, flyTo, setPins } from './cesium.js'
import wipNote from './assets/work-in-progress.png'

// API reads VITE_API_BASE at build time. Empty string means dev mode,
// Vite proxy sends /api to :8000. Share builds bake the tunnel URL here.
const API = (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_BASE) || ''
// BLR is Bengaluru centre: the globe's starting view, never a saved location
const BLR = { lat: 12.9716, lng: 77.5946 }

// MATERIAL_PAINT gives each material a color for dots and map pins
const MATERIAL_PAINT = {
  Wood: '#fbb833', Bricks: '#fa4d43', Metal: '#027b49', Doors: '#f19ec8', Windows: '#1f1f1f',
  Concrete: '#000000', Plywood: '#fbb833', Rebar: '#3d3d3d', Copper: '#b87333',
  Aluminium: '#a8a9ad', 'PVC Pipes': '#fafafa', Tiles: '#c96f2f', Marble: '#8e8e93',
  Glass: '#7dd3e0', Gypsum: '#e8e2d0', Sand: '#d4a017',
}

// TABS defines the 4 tabs: Upload, Marketplace, Smart Match, Requests
const TABS = [
  { id: 'upload', label: 'Upload + AI', short: 'Upload', title: 'Upload + AI', sub: 'Drop demolition photos. AI reads location and materials.' },
  { id: 'market', label: 'Marketplace', short: 'Market', title: 'Marketplace', sub: 'Search reclaimed materials nearby.' },
  { id: 'match', label: 'Smart Match', short: 'Match', title: 'Smart matching', sub: 'Work in progress — check back soon.' },
  { id: 'requests', label: 'Requests', short: 'Requests', title: 'Buyer requests', sub: 'Work in progress — check back soon.' },
]

// fmtINR converts a number to Indian rupees format like ₹1.5 lakh or ₹2 Cr
function fmtINR(n) {
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)} lakh`
  return '₹' + Number(n).toLocaleString('en-IN')
}

// useIsMobile follows the 900px breakpoint.
// CSS cannot swap the sidebar shell for the bottom-tab shell, so React
// picks one tree. The listener keeps it correct when the window resizes.
function useIsMobile() {
  const [mobile, setMobile] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)')
    const onChange = (e) => setMobile(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return mobile
}

// cropCanvas cuts a normalized box out of a loaded photo.
// bbox is 0..1, so the same numbers work on the preview and the original.
// The canvas keeps the box's own shape, so there are no gray bars and no
// extra scenery around the object.
function cropCanvas(img, bbox, maxSize, allowUpscale) {
  const w = img.naturalWidth
  const h = img.naturalHeight
  const [nx1, ny1, nx2, ny2] = bbox || [0, 0, 1, 1]
  // a hair of padding keeps the object from touching the frame edge
  const padX = (nx2 - nx1) * 0.03
  const padY = (ny2 - ny1) * 0.03
  const x1 = Math.max(0, (nx1 - padX) * w)
  const y1 = Math.max(0, (ny1 - padY) * h)
  const x2 = Math.min(w, (nx2 + padX) * w)
  const y2 = Math.min(h, (ny2 + padY) * h)
  const sw = Math.max(1, x2 - x1)
  const sh = Math.max(1, y2 - y1)
  // shrink big boxes; small boxes get a little upscale so they stay visible
  let scale = Math.min(1, maxSize / Math.max(sw, sh))
  if (allowUpscale) scale = Math.max(scale, Math.min(3, 600 / Math.max(sw, sh)))
  const cw = Math.max(1, Math.round(sw * scale))
  const ch = Math.max(1, Math.round(sh * scale))
  const c = document.createElement('canvas')
  c.width = cw
  c.height = ch
  c.getContext('2d').drawImage(img, x1, y1, sw, sh, 0, 0, cw, ch)
  return c
}

// CropThumb shows only the detected object, cut from the uploaded photo.
// No bbox means a color-only hit, so the whole frame is the only evidence.
function CropThumb({ src, bbox, alt, onOpen }) {
  const [url, setUrl] = useState('')

  useEffect(() => {
    if (!src) { setUrl(''); return }
    let alive = true
    const img = new Image()
    img.onload = () => {
      if (!alive) return
      try {
        const c = cropCanvas(img, bbox, 480, true)
        setUrl(c.toDataURL('image/jpeg', 0.86))
      } catch { setUrl('') }
    }
    img.onerror = () => { if (alive) setUrl('') }
    // canvas needs this when the photo is served from another origin
    img.crossOrigin = 'anonymous'
    img.src = src
    return () => { alive = false }
  }, [src, bbox])

  if (!url) return (
    <button type="button" className="det-crop-btn" onClick={onOpen} aria-label={`${alt}. Open object crop`}>
      <div className="det-crop det-crop-empty" aria-hidden="true" />
    </button>
  )
  return (
    <button type="button" className="det-crop-btn" onClick={onOpen} aria-label={`${alt}. Open object crop`}>
      <img className="det-crop" src={url} alt={alt} title={alt} />
    </button>
  )
}

// CropViewer opens on the object itself, cut from the photo.
// "Show in photo" switches to the whole frame with the box drawn, for context.
function CropViewer({ src, bbox, material, pct, onClose }) {
  // view is 'object' (tight crop) or 'photo' (full frame + box)
  const [view, setView] = useState('object')
  // objectUrl is the enlarged cutout of the detected box
  const [objectUrl, setObjectUrl] = useState('')

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    if (!src) { setObjectUrl(''); return }
    let alive = true
    const img = new Image()
    img.onload = () => {
      if (!alive) return
      try {
        const c = cropCanvas(img, bbox, 1400, true)
        setObjectUrl(c.toDataURL('image/jpeg', 0.9))
      } catch { setObjectUrl('') }
    }
    img.onerror = () => { if (alive) setObjectUrl('') }
    // canvas needs this when the photo is served from another origin
    img.crossOrigin = 'anonymous'
    img.src = src
    return () => { alive = false }
  }, [src, bbox])

  const [x1, y1, x2, y2] = bbox || [0, 0, 1, 1]
  return (
    <div className="crop-modal" role="dialog" aria-modal="true" aria-label={`Detected ${material} object`} onClick={onClose}>
      <div className="crop-view" onClick={e => e.stopPropagation()}>
        {view === 'object' ? (
          <div className="crop-stage">
            {objectUrl
              ? <img className="crop-object" src={objectUrl} alt={`Cropped ${material} detected in the photo`} />
              : <span className="crop-loading">Cutting the object…</span>}
          </div>
        ) : (
          <div className="crop-frame">
            <img src={src} alt={`Full photo with the ${material} detection highlighted`} />
            {bbox && <span className="crop-box" style={{
              left: `${x1 * 100}%`, top: `${y1 * 100}%`,
              width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%`,
            }} />}
          </div>
        )}
        <div className="crop-view-bar">
          <span>
            {view === 'object'
              ? <>Detected object · <b>{material}</b>{pct != null ? ` · ${pct}% match` : ''}</>
              : <>AI saw this area for <b>{material}</b></>}
          </span>
          <span className="crop-actions">
            {bbox && (
              <button type="button" className="crop-toggle" onClick={() => setView(v => v === 'object' ? 'photo' : 'object')}>
                {view === 'object' ? 'Show in photo' : 'Show object'}
              </button>
            )}
            <button type="button" className="crop-close" onClick={onClose}>Close</button>
          </span>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  // tab is which tab is currently open
  const [tab, setTab] = useState('upload')
  // health is the backend status from /api/health
  const [health, setHealth] = useState(null)

  // on load, check if backend is alive
  useEffect(() => {
    fetch(`${API}/api/health`).then(r => r.json()).then(j => setHealth(j)).catch(() => {})
  }, [])

  // GSAP: sidebar animation on load, card feedback on tab switch.
  // Skipped entirely under prefers-reduced-motion.
  const pageRef = useRef(null)
  const reduceMotion = () =>
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  useLayoutEffect(() => {
    if (reduceMotion()) return
    const ctx = gsap.context(() => {
      gsap.fromTo('.side-brand, .snav, .side-formula, .m-top, .mtab',
        { x: -14, opacity: 0 },
        { x: 0, opacity: 1, duration: 0.6, stagger: 0.05, ease: 'power3.out', clearProps: 'transform,opacity' })
    }, pageRef)
    return () => ctx.revert()
  }, [])

  useLayoutEffect(() => {
    if (reduceMotion()) return
    const ctx = gsap.context(() => {
      gsap.fromTo('.tab-panel .bezel',
        { y: 16, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.5, stagger: 0.06, ease: 'power3.out', clearProps: 'transform,opacity' })
    }, pageRef)
    return () => ctx.revert()
  }, [tab])

  const active = TABS.find(t => t.id === tab) || TABS[0]
  const isMobile = useIsMobile()

  // Phones get the brand bar and bottom tab bar. Laptops keep the sidebar.
  // Same panels, same API calls, only the shell changes.
  if (isMobile) {
    return (
      <div className="shell m-shell" ref={pageRef}>
        <a className="skip" href="#main">Skip to content</a>

        <header className="m-top">
          <div className="mark">UM</div>
          <div className="m-title">
            <div className="m-brand">UrbanMine · {active.title}</div>
            <div className="m-sub">{active.sub}</div>
          </div>
          <span className={health ? 'dot ok' : 'dot bad'} title="Backend status" />
        </header>

        <main className="page m-page" id="main">
          <div className="tab-panel" key={tab}>
            {tab === 'upload' && <UploadPanel />}
            {tab === 'market' && <MarketPanel />}
            {tab === 'match' && (
              <WipPanel
                title="Smart matching"
                blurb="The ranking works, but the inventory is thin, so most searches come back empty. Check back soon."
              />
            )}
            {tab === 'requests' && (
              <WipPanel
                title="Buyer requests"
                blurb="The form and the save work. The inbox and buyer updates do not. Check back soon."
              />
            )}
          </div>
        </main>

        <footer className="foot mono m-foot">
          UrbanMine · {health ? `${health.listings} listings · YOLOv8` : 'connecting…'}
        </footer>

        <nav className="m-tabs" role="tablist" aria-label="Marketplace sections">
          {TABS.map((t, i) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'mtab active' : 'mtab'} onClick={() => setTab(t.id)}>
              <span className="num">{i + 1}</span>{t.short}
            </button>
          ))}
        </nav>
      </div>
    )
  }

  return (
    <div className="shell" ref={pageRef}>
      <a className="skip" href="#main">Skip to content</a>

      {/* Sidebar on desktop, shows tabs and match formula */}
      <aside className="side">
        <div className="side-brand">
          <div className="mark">UM</div>
          <div>
            <div className="side-brand-name">UrbanMine</div>
            <div className="side-brand-sub">Demolition → reuse · Bengaluru</div>
          </div>
        </div>
        <div className="side-label">Workspace</div>
        <nav className="side-nav" role="tablist" aria-label="Marketplace sections">
          {TABS.map((t, i) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'snav active' : 'snav'} onClick={() => setTab(t.id)}>
              <span className="n">{i + 1}</span>{t.label}
            </button>
          ))}
        </nav>
        <div className="side-formula">
          <div className="side-label">Match formula</div>
          <div className="bars">
            {[['Material', 40], ['Quantity', 25], ['Distance', 20], ['Condition', 15]].map(([k, v]) => (
              <div key={k} className="bar-row"><span>{k}</span>
                <div className="bar"><i style={{ width: v * 2.2 + '%' }} /></div>
                <b>{v}%</b></div>
            ))}
          </div>
          <div className="mono small side-tech">Postgres · YOLOv8 · FastAPI · Cesium</div>
        </div>
        <div className="side-status">
          <span className={health ? 'dot ok' : 'dot bad'} />
          {health ? `${health.listings} listings · YOLOv8` : 'connecting…'}
        </div>
      </aside>

      {/* Main content area */}
      <div className="main">
        <header className="topbar">
          <div>
            <h1>{active.title}</h1>
            <p>Turn demolition waste into revenue. {active.sub}</p>
          </div>
          <div className="spacer" />
          <div className="status-pill">
            <span className={health ? 'dot ok' : 'dot bad'} />
            {health ? `${health.listings} listings · YOLOv8` : 'connecting…'}
          </div>
        </header>

        <main className="page" id="main">
          <div className="tab-panel" key={tab}>
            {tab === 'upload' && <UploadPanel />}
            {tab === 'market' && <MarketPanel />}
            {tab === 'match' && (
              <WipPanel
                title="Smart matching"
                blurb="The ranking works, but the inventory is thin, so most searches come back empty. Check back soon."
              />
            )}
            {tab === 'requests' && (
              <WipPanel
                title="Buyer requests"
                blurb="The form and the save work. The inbox and buyer updates do not. Check back soon."
              />
            )}
          </div>
        </main>

        <footer className="foot mono">
          UrbanMine MVP · React + FastAPI + YOLO + Cesium
        </footer>
      </div>
    </div>
  )
}

// ============================================================
// 0 · Work-in-progress placeholder
// ============================================================
// A tab that is not finished shows only this. No form, no buttons:
// if a tab says work in progress it should not also hand you a form.
function WipPanel({ title, blurb }) {
  return (
    <div className="card bezel"><div className="card-in wip-panel">
      <h2>{title}</h2>
      <img className="wip-note" src={wipNote} alt="This website is a work in progress. Check back soon." />
      <p className="muted">{blurb}</p>
    </div></div>
  )
}

// ============================================================
// 1 · Upload + AI panel
// ============================================================
function UploadPanel() {
  // file is the photo user dropped
  const [file, setFile] = useState(null)
  // preview is the image shown on screen before upload
  const [preview, setPreview] = useState(null)
  // zoom holds the detection whose full photo is open
  const [zoom, setZoom] = useState(null)
  // dets is the list of materials AI found
  const [dets, setDets] = useState([])
  // others is things that are NOT construction (bedsheet, person, clothes)
  const [others, setOthers] = useState([])
  // isSite tells if photo looks like construction site
  const [isSite, setIsSite] = useState(true)
  // loading is true while AI is thinking
  const [loading, setLoading] = useState(false)
  // model is which AI model was used
  const [model, setModel] = useState('')
  // verification is the checked / rejected / kept counter from the backend
  const [verification, setVerification] = useState(null)
  // imageUrl is the saved photo URL the backend returns for this upload
  const [imageUrl, setImageUrl] = useState('')
  // thumbUrl is the small copy the feed shows
  const [thumbUrl, setThumbUrl] = useState('')
  // form has lat, lng, address, contractor.
  // no default point: "no location" is a real answer until the user sets one.
  const [form, setForm] = useState({ lat: null, lng: null, address: '', contractor: '' })
  // locSource says where location came from (photo EXIF, map, GPS, preset)
  const [locSource, setLocSource] = useState('')
  // saved is listings already published
  const [saved, setSaved] = useState([])
  // error shows error message
  const [error, setError] = useState('')
  // phase is idle | exif | detect | done
  const [phase, setPhase] = useState('idle')
  // exifNote is message about GPS found or not found
  const [exifNote, setExifNote] = useState('')
  // preppedRef holds the shrunk photo blob
  const preppedRef = useRef(null)

  // when component unmounts, revoke preview URL to free memory
  useEffect(() => () => { setPreview(p => { if (p) URL.revokeObjectURL(p); return null }) }, [])

  // shrink photo to max 1600px before upload
  // phone photos are 5-15MB, we make them smaller so upload is fast
  const prepImage = (f) => new Promise((resolve) => {
    const url = URL.createObjectURL(f)
    const img = new Image()
    img.onload = () => {
      try {
        const max = 1600
        const scale = Math.min(1, max / Math.max(img.width, img.height))
        const c = document.createElement('canvas')
        c.width = Math.max(1, Math.round(img.width * scale))
        c.height = Math.max(1, Math.round(img.height * scale))
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height)
        URL.revokeObjectURL(url)
        c.toBlob((b) => resolve(b || f), 'image/jpeg', 0.85)
      } catch { URL.revokeObjectURL(url); resolve(f) }
    }
    img.onerror = () => { URL.revokeObjectURL(url); resolve(null) }
    img.src = url
  })

  // update location when LocationPicker changes.
  // null lat/lng means the user picked "no location", so it must be kept as null.
  const setLoc = (patch) => {
    setForm(s => ({
      ...s,
      ...('lat' in patch ? { lat: patch.lat } : {}),
      ...('lng' in patch ? { lng: patch.lng } : {}),
      ...('address' in patch ? { address: patch.address } : {}),
    }))
    if ('source' in patch) setLocSource(patch.source || '')
  }

  // send photo to backend /api/analyze
  const runAnalyze = async (f, plat, plng, paddr) => {
    const fd = new FormData()
    fd.append('file', f, 'photo.jpg')
    // only send a point when one exists; the backend keeps its own default otherwise
    if (plat != null && plng != null) { fd.append('lat', plat); fd.append('lng', plng) }
    fd.append('address', paddr || '')
    try {
      const r = await fetch(`${API}/api/analyze`, { method: 'POST', body: fd })
      const j = await r.json()
      if (j.error) { setError(j.error) }
      else {
        setDets(j.detections || [])
        setModel(j.model || '')
        setVerification(j.verification || null)
        setImageUrl(j.image_url || '')
        setThumbUrl(j.thumb_url || '')
        setOthers(j.non_construction || [])
        setIsSite(j.is_construction_site !== false)
      }
    } catch { setError('Analysis failed. Check the connection, then tap Re-analyse. The photo is kept.') }
    setLoading(false); setPhase('done')
  }

  // called when user drops or selects a photo
  const onFile = async (f) => {
    if (!f) return
    setPreview(prev => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(f) })
    setFile(f); setDets([]); setOthers([]); setIsSite(true); setSaved([]); setError(''); setModel(''); setVerification(null); setImageUrl(''); setThumbUrl('')
    setLoading(true); setPhase('exif'); setExifNote('')
    let plat = form.lat, plng = form.lng
    let hasGps = false
    try {
      // exifr reads GPS from photo metadata
      // if photo has GPS tag, we use it as location
      const g = await exifr.gps(f)
      if (g && g.latitude && g.longitude) {
        hasGps = true
        plat = +g.latitude.toFixed(5); plng = +g.longitude.toFixed(5)
        setForm(s => ({ ...s, lat: plat, lng: plng }))
        setLocSource('photo EXIF')
        setExifNote(`GPS found in photo → ${plat.toFixed(4)}, ${plng.toFixed(4)}`)
      }
    } catch { /* no readable metadata: handled below */ }

    // Camera capture and chat apps strip the GPS tag, so a photo with no tag
    // still gets a point from the device. A location the user already picked wins.
    if (!hasGps && form.lat == null && form.lng == null) {
      if (navigator.geolocation) {
        setExifNote('No GPS tag in this photo. Asking this device for its location…')
        navigator.geolocation.getCurrentPosition(
          (p) => {
            const lat = +p.coords.latitude.toFixed(5), lng = +p.coords.longitude.toFixed(5)
            // ignore the answer if the photo was published from elsewhere meanwhile
            setForm(s => (s.lat == null && s.lng == null ? { ...s, lat, lng } : s))
            setLocSource('device GPS')
            setExifNote(`No GPS tag in photo. Used this device → ${lat.toFixed(4)}, ${lng.toFixed(4)}`)
          },
          () => setExifNote('No GPS tag in this photo and device location is blocked. Set the site below.'),
          { timeout: 10000, maximumAge: 300000 }
        )
      } else {
        setExifNote('No GPS tag in this photo. Set the site below.')
      }
    }
    setPhase('detect')
    const blob = await prepImage(f)
    if (!blob) { setError("Couldn't read that photo. Please use JPG or PNG."); setLoading(false); setPhase('idle'); return }
    preppedRef.current = blob
    await runAnalyze(blob, plat, plng, form.address)
  }

  // re-run AI on same photo
  const reanalyse = () => {
    if (!file) { setError('Drop a demolition photo first.'); return }
    setError(''); setLoading(true); setPhase('detect')
    runAnalyze(preppedRef.current || file, form.lat, form.lng, form.address)
  }

  // change one field of one detection (qty, unit, condition, price)
  const updateDet = (i, k, v) => setDets(d => d.map((x, j) => j === i ? { ...x, [k]: v } : x))

  // send confirmed detection to backend to create listing
  const confirm = async (d) => {
    const body = {
      material: d.material, quantity: Number(d.quantity), unit: d.unit,
      condition: d.condition, price_per_unit: Number(d.suggested_price_per_unit),
      lat: form.lat == null ? null : Number(form.lat),
      lng: form.lng == null ? null : Number(form.lng),
      address: form.address, contractor: form.contractor,
      title: `${d.material} — ${d.quantity} ${d.unit}`,
      description: `Detected by AI from a site photo (${Math.round(d.confidence * 100)}% match). Condition is the seller's estimate.`,
      confidence: d.confidence,
      image_url: imageUrl || null,
      thumb_url: thumbUrl || null,
      bbox: d.bbox || null,
    }
    const r = await fetch(`${API}/api/listings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    if (!r.ok) { setError('Could not save that listing. Please try again.'); return }
    const j = await r.json()
    setSaved(s => [...s, j])
  }

  const step = saved.length ? 2 : file ? 1 : 0

  return (
    <div className="grid2">
      <div className="card bezel">
        <div className="card-in">
          <h2>1 · Site photo</h2>
          <p className="muted">Drop a demolition photo. The AI reads the <b>location from the photo itself</b> (GPS tag), falls back to this device when the photo has none, and detects materials. You verify.</p>
          <div className="steps" aria-label="Progress">
            {['Photo', 'AI review', 'Published'].map((s, i) => (
              <div key={s} className={i < step ? 'step done' : i === step ? 'step on' : 'step'}>{i < step ? '✓ ' : ''}{s}</div>
            ))}
          </div>
          <label className="drop" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); onFile(e.dataTransfer.files[0]) }}>
            <input type="file" accept="image/*" className="visually-hidden" onChange={e => onFile(e.target.files[0])} aria-label="Upload demolition site photo" />
            {preview ? <img src={preview} alt="Demolition site preview" /> : <div className="drop-empty"><b>Drop photo / click to browse</b><span>JPG, PNG — site, pile, interior</span></div>}
          </label>
          <div className="snap-row">
            <label className="cta sm">📷 Snap with camera<input type="file" accept="image/*" capture="environment" className="visually-hidden" onChange={e => e.target.files[0] && onFile(e.target.files[0])} aria-label="Take a site photo" /></label>
            <span className="mono small muted">mobile: rear camera · GPS tag auto-read</span>
          </div>
          {loading && (
            <div className="think" role="status" aria-label="AI thinking">
              <div>{phase === 'exif' ? <span className="spin" /> : '✓ '}Photo location{exifNote && phase !== 'exif' ? ` — ${exifNote}` : '…'}</div>
              <div>{phase === 'detect' ? <span className="spin" /> : phase === 'done' ? '✓ ' : '· '}Material detection (Wood · Bricks · Metal · Doors · Windows · Concrete)</div>
            </div>
          )}
          {!loading && exifNote && <div className="mono small muted">{exifNote}</div>}
          <h2>2 · Site location</h2>
          <LocationPicker lat={form.lat} lng={form.lng} address={form.address} source={locSource} onChange={setLoc} />
          <div className="frow">
            <label>Address (auto-filled, editable)<input value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} /></label>
            <label>Contractor<input value={form.contractor} placeholder="Your company" onChange={e => setForm({ ...form, contractor: e.target.value })} /></label>
          </div>
          <button className="cta" onClick={reanalyse} disabled={loading || !file}>{loading ? 'AI thinking…' : 'Re-analyse photo'}<span className="cta-ic">↗</span></button>
          {error && <div className="err" role="alert">{error}</div>}
          {model && <div className="mono small">model: {model}</div>}
          {verification && (
            <div className="mono small">
              {verification.checked > 0
                ? `AI checked ${verification.checked} object${verification.checked === 1 ? '' : 's'} · ${verification.rejected} rejected · ${verification.kept} listed`
                : 'AI found no objects to check.'}
            </div>
          )}
          {saved.length > 0 && <div className="ok-box">✓ {saved.length} listing(s) published. See Marketplace.</div>}
        </div>
      </div>

      <div className="card bezel">
        <div className="card-in">
          <h2>3 · Verify & publish {dets.length ? `· ${dets.length}` : ''}</h2>
          {loading && <div className="skel"><i /><i /><i /></div>}
          {!loading && dets.length === 0 && <div className="empty">Drop a photo on the left. Analysis starts automatically.<br />Site photos yield materials; anything else gets flagged as non-construction.</div>}
          {!loading && phase === 'done' && !isSite && (
            <div className="err" role="alert">Doesn't look like a construction site. No reusable materials found.</div>
          )}
          {!loading && others.length > 0 && (
            <div className="noncon">
              <div className="noncon-head">Not construction-related: excluded from listings</div>
              {others.map((o, i) => (
                <div key={i} className="noncon-row"><span>{o.label}{o.count > 1 ? ` ×${o.count}` : ''}</span><span className="mono small">{Math.round(o.confidence * 100)}%</span></div>
              ))}
            </div>
          )}
          {dets.map((d, i) => (
            <div key={i} className="det">
              <div className="det-top"><CropThumb src={preview} bbox={d.bbox} alt={`Detected ${d.material} crop`} onOpen={() => setZoom({ src: preview, bbox: d.bbox, material: d.material, pct: d.share != null ? d.share : Math.round(d.confidence * 100) })} /><span className="mdot" style={{ background: MATERIAL_PAINT[d.material] || '#1f1f1f' }} /><b>{d.material}</b>
                <span className="conf" title={d.source || ''}>{d.share != null ? d.share : Math.round(d.confidence * 100)}%</span></div>
              <div className="frow">
                <label>Qty<input type="number" value={d.quantity} onChange={e => updateDet(i, 'quantity', e.target.value)} /></label>
                <label>Unit<input value={d.unit} onChange={e => updateDet(i, 'unit', e.target.value)} /></label>
              </div>
              <div className="frow">
                <label>Condition<select value={d.condition} onChange={e => updateDet(i, 'condition', e.target.value)}>
                  {['Excellent', 'Good', 'Fair', 'Poor'].map(c => <option key={c}>{c}</option>)}
                </select></label>
                <label>₹ / {d.unit}<input type="number" value={d.suggested_price_per_unit} onChange={e => updateDet(i, 'suggested_price_per_unit', e.target.value)} /></label>
              </div>
              <div className="list-preview" aria-label="Listing preview">
                <span className="mono small">WILL BE LISTED AS</span>
                <b>Reclaimed {d.material} — {d.quantity} {d.unit}</b>
                <span className="muted small">{d.condition} condition · ₹{d.suggested_price_per_unit}/{d.unit} · Total {fmtINR((Number(d.quantity) || 0) * (Number(d.suggested_price_per_unit) || 0))}</span>
                {d.source && <span className="mono small muted">spotted by: {d.source}</span>}
              </div>
              <button className="cta ghost" onClick={() => confirm(d)}>Confirm → Create listing<span className="cta-ic">+</span></button>
            </div>
          ))}
        </div>
      </div>
      {zoom && <CropViewer {...zoom} onClose={() => setZoom(null)} />}
    </div>
  )
}

// ============================================================
// 2 · Marketplace + Map panel
// ============================================================
function MarketPanel() {
  // items is the list of listings from backend
  const [items, setItems] = useState([])
  // f has filters: search, material, condition, distance, location
  const [f, setF] = useState({ q: '', material: '', condition: '', max_distance_km: 100, lat: null, lng: null, address: '', source: '' })
  // mats is list of material names for dropdown
  const [mats, setMats] = useState([])
  // mapRef is the Cesium map div
  const mapRef = useRef(null)
  // mapObj is the Cesium viewer object
  const mapObj = useRef(null)
  // mapError shows if globe failed to load
  const [mapError, setMapError] = useState('')

  // load listings from backend with current filters
  const load = async () => {
    // build params by hand: URLSearchParams turns a null lat into "null"
    const p = new URLSearchParams()
    if (f.q) p.set('q', f.q)
    if (f.material) p.set('material', f.material)
    if (f.condition) p.set('condition', f.condition)
    if (f.max_distance_km) p.set('max_distance_km', f.max_distance_km)
    // no buyer point means no distance filter, not a fake one at Bengaluru centre
    if (f.lat != null && f.lng != null) { p.set('lat', f.lat); p.set('lng', f.lng) }
    const r = await fetch(`${API}/api/listings?` + p.toString())
    setItems(await r.json())
  }
  useEffect(() => { load() }, [f.lat, f.lng])
  useEffect(() => { fetch(`${API}/api/materials`).then(r => r.json()).then(j => setMats(j.map(m => m.name))).catch(() => {}) }, [])

  // init Cesium globe once, show pins, follow buyer location
  useEffect(() => {
    let alive = true
    ;(async () => {
      if (!window.Cesium) { setMapError('3D library failed to load. Filters still work.'); return }
      if (!mapRef.current) return
      const viewer = await createViewer(mapRef.current)
      if (!alive) { if (viewer && !viewer.isDestroyed()) viewer.destroy(); return }
      if (!viewer) { setMapError('Globe failed to start. Search and GPS still work.'); return }
      mapObj.current = viewer
      flyTo(viewer, BLR.lat, BLR.lng, 150000)
    })()
    return () => { alive = false; if (mapObj.current && !mapObj.current.isDestroyed()) { mapObj.current.destroy(); mapObj.current = null } }
  }, [])
  useEffect(() => { if (mapObj.current) setPins(mapObj.current, items) }, [items])
  useEffect(() => {
    if (mapObj.current && f.lat != null && f.lng != null) flyTo(mapObj.current, f.lat, f.lng, 60000)
  }, [f.lat, f.lng])

  // reqForm has buyer name, type, message
  const [reqForm, setReqForm] = useState({ buyer_name: '', buyer_type: 'Architect', message: '' })
  const [notice, setNotice] = useState('')
  const [reqError, setReqError] = useState('')
  // zoom holds the listing photo that is open
  const [zoom, setZoom] = useState(null)
  const request = async (l) => {
    if (!reqForm.buyer_name.trim()) {
      setReqError('Add your name before requesting this material.')
      return
    }
    setReqError('')
    const r = await fetch(`${API}/api/requests`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ listing_id: l.id, ...reqForm, quantity: l.quantity }),
    })
    if (!r.ok) { setReqError('Could not save that request. Please try again.'); return }
    setNotice(`Requested: ${l.title}. Saved for the contractor.`)
  }

  return (
    <div>
      <div className="card bezel"><div className="card-in">
        <h2>Buyer location: set one to see distances, or leave it empty</h2>
        <LocationPicker compact lat={f.lat} lng={f.lng} address={f.address} source={f.source} onChange={(p) => setF(s => ({ ...s, ...p }))} />
        <div className="filters">
          <label>Search<input placeholder="teak, steel, doors…" value={f.q} onChange={e => setF({ ...f, q: e.target.value })} /></label>
          <label>Material<select value={f.material} onChange={e => setF({ ...f, material: e.target.value })}>
            <option value="">All</option>{(mats.length ? mats : ['Wood', 'Bricks', 'Metal', 'Doors', 'Windows', 'Concrete']).map(m => <option key={m}>{m}</option>)}
          </select></label>
          <label>Condition<select value={f.condition} onChange={e => setF({ ...f, condition: e.target.value })}>
            <option value="">Any</option>{['Excellent', 'Good', 'Fair', 'Poor'].map(c => <option key={c}>{c}</option>)}
          </select></label>
          <label>Within km<input type="number" value={f.max_distance_km} onChange={e => setF({ ...f, max_distance_km: e.target.value })} /></label>
          <button className="cta sm" onClick={load}>Search<span className="cta-ic">⌕</span></button>
        </div>
        <div className="frow">
          <label>Buyer name<input value={reqForm.buyer_name} placeholder="Your name" onChange={e => setReqForm({ ...reqForm, buyer_name: e.target.value })} /></label>
          <label>Type<select value={reqForm.buyer_type} onChange={e => setReqForm({ ...reqForm, buyer_type: e.target.value })}>
            {['Architect', 'Builder', 'Interior Designer', 'Artist', 'Contractor'].map(t => <option key={t}>{t}</option>)}
          </select></label>
        </div>
        {reqError && <div className="err" role="alert">{reqError}</div>}
        {notice && <div className="ok-box" role="status">{notice}</div>}
      </div></div>

      <div className="grid2">
        <div className="cards">
          {items.map(l => (
            <div key={l.id} className="card bezel"><div className="card-in">
              {(l.image_url || l.thumb_url) && (
                <div className="l-photo">
                  {/* feed loads the small copy; the viewer loads the full photo */}
                  <CropThumb
                    src={`${API}${l.thumb_url || l.image_url}`}
                    bbox={l.bbox}
                    alt={`${l.material} listing photo`}
                    onOpen={() => setZoom({
                      src: `${API}${l.image_url || l.thumb_url}`, bbox: l.bbox, material: l.material,
                      pct: l.confidence != null ? Math.round(l.confidence * 100) : null,
                    })}
                  />
                </div>
              )}
              <div className="l-top"><span className="mdot" style={{ background: MATERIAL_PAINT[l.material] || '#1f1f1f' }} /><b>{l.title}</b><span className="tag">{l.condition}</span></div>
              <div className="muted">{l.description}</div>
              <div className="l-meta mono">{l.quantity} {l.unit} · ₹{l.price_per_unit}/{l.unit} · total {fmtINR(l.quantity * l.price_per_unit)}{l.distance_km != null ? ` · ${l.distance_km} km` : ''}</div>
              <div className="muted small">
                {l.address || 'No location'}
                {l.contractor ? ` · ${l.contractor}` : ''}
                {l.confidence != null ? ` · AI ${Math.round(l.confidence * 100)}%` : ''}
              </div>
              <button className="cta ghost sm" onClick={() => request(l)}>Request material<span className="cta-ic">→</span></button>
            </div></div>
          ))}
          {items.length === 0 && <div className="empty">No listings match. Loosen filters or publish from Upload tab.</div>}
        </div>
        <div className="card bezel map-card"><div className="card-in">
          <h2>Nearby · 3D globe</h2>
          <div ref={mapRef} className="map" role="application" aria-label="3D globe of nearby listings" />
          {mapError && <div className="err" role="alert">{mapError}</div>}
          <div className="mono small">Cesium globe · satellite view keyless · click a pin for details.</div>
        </div></div>
      </div>
      {zoom && <CropViewer {...zoom} onClose={() => setZoom(null)} />}
    </div>
  )
}

// ============================================================
// 3 · Smart Match panel
// ============================================================
// Not rendered while the tab is work in progress: WipPanel stands in.
// Swap the render back in the tab tree when the ranking UI is finished.
function MatchPanel() {
  // q has what buyer is looking for: material, qty, location, condition, distance
  const [q, setQ] = useState({ material: 'Wood', quantity: 500, lat: BLR.lat, lng: BLR.lng, condition: 'Good', max_distance_km: 50, address: 'Koramangala, Bengaluru', source: '' })
  // res is the ranked match results
  const [res, setRes] = useState([])
  // mats is material names for dropdown
  const [mats, setMats] = useState([])

  const run = async () => {
    const r = await fetch(`${API}/api/match`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...q, quantity: Number(q.quantity), lat: Number(q.lat), lng: Number(q.lng), max_distance_km: Number(q.max_distance_km) }),
    })
    const j = await r.json()
    setRes(j.results || [])
  }
  useEffect(() => { run() }, [])
  useEffect(() => { fetch(`${API}/api/materials`).then(r => r.json()).then(j => setMats(j.map(m => m.name))).catch(() => {}) }, [])

  return (
    <div className="card bezel"><div className="card-in">
      <h2>Smart matching</h2>
      <p className="muted">Score = material 40% + quantity 25% + distance 20% + condition 15%.</p>
      <LocationPicker compact lat={q.lat} lng={q.lng} address={q.address} source={q.source} onChange={(p) => setQ(s => ({ ...s, ...p }))} />
      <div className="filters">
        <label>Material<select value={q.material} onChange={e => setQ({ ...q, material: e.target.value })}>
          {(mats.length ? mats : ['Wood', 'Bricks', 'Metal', 'Doors', 'Windows', 'Concrete']).map(m => <option key={m}>{m}</option>)}
        </select></label>
        <label>Qty needed<input type="number" value={q.quantity} onChange={e => setQ({ ...q, quantity: e.target.value })} /></label>
        <label>Condition<select value={q.condition} onChange={e => setQ({ ...q, condition: e.target.value })}>
          {['Excellent', 'Good', 'Fair', 'Poor'].map(c => <option key={c}>{c}</option>)}
        </select></label>
        <label>Within km<input type="number" value={q.max_distance_km} onChange={e => setQ({ ...q, max_distance_km: e.target.value })} /></label>
        <button className="cta sm" onClick={run}>Find matches<span className="cta-ic">✦</span></button>
      </div>
      <div className="match-list">
        {res.map(r => (
          <div key={r.id} className="match-row">
            <div className="score" style={{ '--s': r.match_score + '%' }}>{r.match_score}%</div>
            <div><span className="mdot" style={{ background: MATERIAL_PAINT[r.material] || '#1f1f1f' }} /><b>{r.title}</b><div className="muted small">{r.distance_km} km away · {r.condition} · {r.quantity} {r.unit} · {r.address}</div></div>
            <span className="tag">{r.material}</span>
          </div>
        ))}
        {res.length === 0 && <div className="empty">No matches in range.</div>}
      </div>
    </div></div>
  )
}

// ============================================================
// 4 · Requests panel
// ============================================================
// Not rendered while the tab is work in progress: WipPanel stands in.
function RequestsPanel() {
  // rows is all buyer requests
  const [rows, setRows] = useState([])
  useEffect(() => { fetch(`${API}/api/requests`).then(r => r.json()).then(setRows) }, [])
  const setStatus = async (id, status) => {
    const r = await fetch(`${API}/api/requests/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
    const j = await r.json()
    setRows(rows => rows.map(x => x.id === id ? j : x))
  }
  return (
    <div className="card bezel"><div className="card-in">
      <h2>Buyer requests</h2>
      <p className="muted">Buyer clicks "Request Material" → contractor accepts or declines here.</p>
      {rows.length === 0 && <div className="empty">No requests yet. Request something from the Marketplace.</div>}
      {rows.map(r => (
        <div key={r.id} className="match-row">
          <span className="tag">{r.status}</span>
          <div><b>{r.listing_title}</b><div className="muted small">{r.buyer_name} ({r.buyer_type}) · {r.quantity} units · "{r.message || '—'}" · contractor: {r.contractor}</div></div>
          {r.status === 'pending' ? (
            <span>
              <button type="button" className="cta sm" onClick={() => setStatus(r.id, 'accepted')}>Accept</button>
              {' '}
              <button type="button" className="cta sm ghost" onClick={() => setStatus(r.id, 'declined')}>Decline</button>
            </span>
          ) : <span className="mono small">{r.id}</span>}
        </div>
      ))}
    </div></div>
  )
}


