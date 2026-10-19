// UrbanMine Frontend — simple, one file.
// React + Vite. Five tabs, each does one thing.
// No GSAP, no complex hooks, easy to read top to bottom.

import { useEffect, useRef, useState } from 'react'
import exifr from 'exifr'
import LocationPicker from './LocationPicker.jsx'
import { createViewer, flyTo, setPins } from './cesium.js'

// API is the backend URL. Empty string means dev mode, Vite proxy sends /api to :8000
const API = ''
// BLR is Bengaluru center coordinates, used as default location
const BLR = { lat: 12.9716, lng: 77.5946 }

// MATERIAL_PAINT gives each material a color for dots and map pins
const MATERIAL_PAINT = {
  Wood: '#fbb833', Bricks: '#fa4d43', Metal: '#027b49', Doors: '#f19ec8', Windows: '#1f1f1f',
  Concrete: '#000000', Plywood: '#fbb833', Rebar: '#3d3d3d', Copper: '#b87333',
  Aluminium: '#a8a9ad', 'PVC Pipes': '#fafafa', Tiles: '#c96f2f', Marble: '#8e8e93',
  Glass: '#7dd3e0', Gypsum: '#e8e2d0', Sand: '#d4a017',
}

// TABS defines the 5 tabs: Upload, Marketplace, Smart Match, Requests, Impact
const TABS = [
  { id: 'upload', label: 'Upload + AI', short: 'Upload', title: 'Upload + AI', sub: 'Drop demolition photos. AI reads location and materials.' },
  { id: 'market', label: 'Marketplace', short: 'Market', title: 'Marketplace', sub: 'Search reclaimed materials nearby.' },
  { id: 'match', label: 'Smart Match', short: 'Match', title: 'Smart matching', sub: 'Ranked by material 40 · quantity 25 · distance 20 · condition 15.' },
  { id: 'requests', label: 'Requests', short: 'Requests', title: 'Buyer requests', sub: 'Accept or decline incoming material requests.' },
  { id: 'impact', label: 'Impact', short: 'Impact', title: 'Impact dashboard', sub: 'Tonnes diverted, value recovered, matches.' },
]

// fmtINR converts a number to Indian rupees format like ₹1.5 lakh or ₹2 Cr
function fmtINR(n) {
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)} lakh`
  return '₹' + Number(n).toLocaleString('en-IN')
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

  const active = TABS.find(t => t.id === tab) || TABS[0]

  return (
    <div className="shell">
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
        <nav className="side-nav">
          {TABS.map((t, i) => (
            <button key={t.id} className={tab === t.id ? 'snav active' : 'snav'} onClick={() => setTab(t.id)}>
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
          <div className="mono small side-tech">PostGIS · YOLOv8n · FastAPI · Cesium</div>
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
            {tab === 'match' && <MatchPanel />}
            {tab === 'requests' && <RequestsPanel />}
            {tab === 'impact' && <ImpactPanel />}
          </div>
        </main>

        <footer className="foot mono">
          UrbanMine MVP · React + FastAPI + YOLO + Cesium · localhost:5173 ↔ :8000
        </footer>
      </div>
    </div>
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
  // form has lat, lng, address, contractor
  const [form, setForm] = useState({ lat: BLR.lat, lng: BLR.lng, address: 'Koramangala, Bengaluru', contractor: 'Sharma Demolition Co.' })
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

  // update location when LocationPicker changes
  const setLoc = ({ lat, lng, address, source }) => {
    setForm(s => ({
      ...s,
      ...(lat != null ? { lat } : {}),
      ...(lng != null ? { lng } : {}),
      ...(address ? { address } : {}),
    }))
    if (source) setLocSource(source)
  }

  // send photo to backend /api/analyze
  const runAnalyze = async (f, plat, plng, paddr) => {
    const fd = new FormData()
    fd.append('file', f, 'photo.jpg')
    fd.append('lat', plat); fd.append('lng', plng); fd.append('address', paddr)
    try {
      const r = await fetch(`${API}/api/analyze`, { method: 'POST', body: fd })
      const j = await r.json()
      if (j.error) { setError(j.error) }
      else {
        setDets(j.detections || [])
        setModel(j.model || '')
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
    setFile(f); setDets([]); setOthers([]); setIsSite(true); setSaved([]); setError(''); setModel('')
    setLoading(true); setPhase('exif'); setExifNote('')
    let plat = form.lat, plng = form.lng
    try {
      // exifr reads GPS from photo metadata
      // if photo has GPS tag, we use it as location
      const g = await exifr.gps(f)
      if (g && g.latitude && g.longitude) {
        plat = +g.latitude.toFixed(5); plng = +g.longitude.toFixed(5)
        setForm(s => ({ ...s, lat: plat, lng: plng }))
        setLocSource('photo EXIF')
        setExifNote(`GPS found in photo → ${plat.toFixed(4)}, ${plng.toFixed(4)}`)
      } else {
        setExifNote('No GPS tag in this photo. Set the site below.')
      }
    } catch { setExifNote('No GPS tag in this photo. Set the site below.') }
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
      lat: Number(form.lat), lng: Number(form.lng),
      address: form.address, contractor: form.contractor,
      title: `${d.material} — ${d.quantity} ${d.unit}`,
      description: `AI-detected (${Math.round(d.confidence * 100)}% confidence), contractor-verified.`,
      confidence: d.confidence,
    }
    const r = await fetch(`${API}/api/listings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const j = await r.json()
    setSaved(s => [...s, j])
  }

  const step = saved.length ? 2 : file ? 1 : 0

  return (
    <div className="grid2">
      <div className="card bezel">
        <div className="card-in">
          <h2>1 · Site photo</h2>
          <p className="muted">Drop a demolition photo. The AI reads the <b>location from the photo itself</b> (GPS tag) and detects materials. You verify.</p>
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
            <label>Contractor<input value={form.contractor} onChange={e => setForm({ ...form, contractor: e.target.value })} /></label>
          </div>
          <button className="cta" onClick={reanalyse} disabled={loading || !file}>{loading ? 'AI thinking…' : 'Re-analyse photo'}<span className="cta-ic">↗</span></button>
          {error && <div className="err" role="alert">{error}</div>}
          {model && <div className="mono small">model: {model}</div>}
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
              <div className="det-top"><span className="det-ic">{d.icon}</span><span className="mdot" style={{ background: MATERIAL_PAINT[d.material] || '#1f1f1f' }} /><b>{d.material}</b>
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
  const [f, setF] = useState({ q: '', material: '', condition: '', max_distance_km: 100, lat: BLR.lat, lng: BLR.lng, address: 'Koramangala, Bengaluru', source: '' })
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
    const p = new URLSearchParams({ ...f, q: f.q || '', material: f.material || '' })
    if (!f.material) p.delete('material')
    if (!f.q) p.delete('q')
    if (!f.condition) p.delete('condition')
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
  useEffect(() => { if (mapObj.current) flyTo(mapObj.current, f.lat, f.lng, 60000) }, [f.lat, f.lng])

  // reqForm has buyer name, type, message
  const [reqForm, setReqForm] = useState({ buyer_name: 'Architect A', buyer_type: 'Architect', message: '' })
  const [notice, setNotice] = useState('')
  const request = async (l) => {
    await fetch(`${API}/api/requests`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ listing_id: l.id, ...reqForm, quantity: l.quantity }),
    })
    setNotice(`Requested: ${l.title}. The contractor sees it under Requests.`)
  }

  return (
    <div>
      <div className="card bezel"><div className="card-in">
        <h2>Buyer location: distances measured from here</h2>
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
          <label>Buyer name<input value={reqForm.buyer_name} onChange={e => setReqForm({ ...reqForm, buyer_name: e.target.value })} /></label>
          <label>Type<select value={reqForm.buyer_type} onChange={e => setReqForm({ ...reqForm, buyer_type: e.target.value })}>
            {['Architect', 'Builder', 'Interior Designer', 'Artist', 'Contractor'].map(t => <option key={t}>{t}</option>)}
          </select></label>
        </div>
        {notice && <div className="ok-box" role="status">{notice}</div>}
      </div></div>

      <div className="grid2">
        <div className="cards">
          {items.map(l => (
            <div key={l.id} className="card bezel"><div className="card-in">
              <div className="l-top"><span className="mdot" style={{ background: MATERIAL_PAINT[l.material] || '#1f1f1f' }} /><b>{l.title}</b><span className="tag">{l.condition}</span></div>
              <div className="muted">{l.description}</div>
              <div className="l-meta mono">{l.quantity} {l.unit} · ₹{l.price_per_unit}/{l.unit} · total {fmtINR(l.quantity * l.price_per_unit)}{l.distance_km != null ? ` · ${l.distance_km} km` : ''}</div>
              <div className="muted small">{l.address} · {l.contractor} · AI {Math.round((l.confidence || 1) * 100)}%</div>
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
    </div>
  )
}

// ============================================================
// 3 · Smart Match panel
// ============================================================
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

// ============================================================
// 5 · Impact panel
// ============================================================
function ImpactPanel() {
  // d is impact data from backend
  const [d, setD] = useState(null)
  useEffect(() => { fetch(`${API}/api/impact`).then(r => r.json()).then(setD) }, [])
  if (!d) return <div className="empty">Loading impact…</div>
  const cards = [
    ['Material diverted', `${d.tonnes_diverted} tonnes`, 'vs landfill', 'paint-g'],
    ['Value recovered', d.value_recovered_fmt, `${d.active_listings} active listings`, 'paint-y'],
    ['Buyer matches', d.buyer_matches, `${d.total_requests} direct requests`, 'paint-p'],
    ['Active listings', d.active_listings, 'live now', 'paint-r'],
  ]
  return (
    <div>
      <div className="impact-grid">
        {cards.map(([k, v, s, p]) => (
          <div key={k} className="card bezel"><div className={`card-in impact ${p}`}>
            <span className="muted">{k}</span><b>{v}</b><span className="mono small">{s}</span>
          </div></div>
        ))}
      </div>
      <div className="card bezel"><div className="card-in">
        <h2>How it's computed (MVP)</h2>
        <p className="muted">Tonnes ≈ Σ qty × material CO₂ factor / 1000 · Value = Σ qty × price · Matches = seed 43 + live requests.</p>
      </div></div>
    </div>
  )
}
