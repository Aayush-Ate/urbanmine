import { useEffect, useRef, useState } from 'react'
import { createViewer, flyTo } from './cesium.js'

export const AREAS = [
  { name: 'Koramangala', lat: 12.9352, lng: 77.6245 },
  { name: 'HSR Layout', lat: 12.9116, lng: 77.6474 },
  { name: 'Indiranagar', lat: 12.9784, lng: 77.6408 },
  { name: 'Jayanagar', lat: 12.925, lng: 77.5938 },
  { name: 'BTM Layout', lat: 12.9166, lng: 77.61 },
  { name: 'Whitefield', lat: 12.9698, lng: 77.75 },
  { name: 'Hebbal', lat: 13.0358, lng: 77.597 },
  { name: 'Yelahanka', lat: 13.1007, lng: 77.5963 },
  { name: 'Peenya', lat: 13.0284, lng: 77.5182 },
  { name: 'Electronic City', lat: 12.8452, lng: 77.6602 },
  { name: 'MG Road', lat: 12.9757, lng: 77.6013 },
  { name: 'Bellandur', lat: 12.926, lng: 77.6762 },
]

const short = (name) => (name || '').split(',').slice(0, 3).join(',')

// HERE Geocoding & Search (free tier at developer.here.com) when
// VITE_HERE_API_KEY is set; Nominatim (OSM, keyless) otherwise.
const HERE_KEY =
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_HERE_API_KEY) || ''
const HERE_AT = '12.9716,77.5946' // Bengaluru bias

async function geoSearch(q) {
  if (HERE_KEY) {
    try {
      const r = await fetch(
        `https://geocode.search.hereapi.com/v1/geocode?q=${encodeURIComponent(q)}&in=countryCode:IND&at=${HERE_AT}&limit=5&lang=en&apiKey=${HERE_KEY}`
      )
      const j = await r.json()
      if (Array.isArray(j.items) && j.items.length) {
        return j.items.map((it, i) => ({
          id: it.id || `h${i}`,
          label: short(it.address?.label || it.title),
          lat: it.position.lat,
          lng: it.position.lng,
        }))
      }
    } catch { /* fall through to Nominatim */ }
  }
  const r = await fetch(
    `https://nominatim.openstreetmap.org/search?format=jsonv2&q=${encodeURIComponent(q)}&limit=5&viewbox=77.4,13.2,77.8,12.8&accept-language=en`
  )
  const j = await r.json()
  return (Array.isArray(j) ? j : []).map((x, i) => ({
    id: x.place_id || `n${i}`,
    label: short(x.display_name),
    lat: +x.lat,
    lng: +x.lon,
  }))
}

async function geoReverse(lat, lng) {
  if (HERE_KEY) {
    try {
      const r = await fetch(
        `https://revgeocode.search.hereapi.com/v1/revgeocode?at=${lat},${lng}&limit=1&lang=en&apiKey=${HERE_KEY}`
      )
      const j = await r.json()
      const label = j.items?.[0]?.address?.label
      if (label) return short(label)
    } catch { /* fall through to Nominatim */ }
  }
  const r = await fetch(
    `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}&accept-language=en`
  )
  const j = await r.json()
  return j.display_name ? short(j.display_name) : ''
}

/**
 * LocationPicker. Nobody types lat/lng.
 * Ways to set a point: address search (Nominatim), area preset,
 * device GPS, or tap/drag on the mini map. Reverse-geocodes to a
 * human address automatically. `compact` hides the mini map.
 */
export default function LocationPicker({ lat, lng, address, source, onChange, compact }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [err, setErr] = useState('')
  const [geoLoading, setGeoLoading] = useState(false)
  const [mapError, setMapError] = useState('')
  const mapRef = useRef(null)
  const mapObj = useRef(null)
  const markerRef = useRef(null)
  const lastRev = useRef('')
  const searchTimer = useRef(null)

  // Pass through only what changed. The parent merges into its own state,
  // so a map tap never clobbers a freshly reverse-geocoded address.
  const set = (patch) => onChange(patch)

  // Reverse-geocode whenever the point moves → human address, no typing.
  // HERE with key, Nominatim fallback. Whichever answers first wins.
  useEffect(() => {
    const key = `${Number(lat).toFixed(4)},${Number(lng).toFixed(4)}`
    if (!lat || !lng || lastRev.current === key) return
    lastRev.current = key
    let live = true
    geoReverse(lat, lng)
      .then((label) => { if (live && label) set({ address: label }) })
      .catch(() => {})
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lat, lng])

  // Address search (debounced, biased to Bengaluru; HERE with key, Nominatim fallback).
  useEffect(() => {
    clearTimeout(searchTimer.current)
    if (q.trim().length < 3) { setResults([]); setSearching(false); return }
    setSearching(true)
    let live = true
    searchTimer.current = setTimeout(async () => {
      try {
        const out = await geoSearch(q.trim())
        if (live) setResults(out)
      } catch { if (live) setResults([]) }
      if (live) setSearching(false)
    }, 500)
    return () => { live = false; clearTimeout(searchTimer.current) }
  }, [q])

  // Mini 3D globe: click to set, drag the SITE pin to fine-tune.
  useEffect(() => {
    if (compact) return
    if (!window.Cesium || !mapRef.current) {
      setMapError('Mini-globe failed to load. Search, presets and GPS above still work.')
      return
    }
    let alive = true
    let handler = null
    ;(async () => {
      const Cesium = window.Cesium
      const viewer = await createViewer(mapRef.current)
      if (!alive) { if (viewer && !viewer.isDestroyed()) viewer.destroy(); return }
      if (!viewer) {
        setMapError('Mini-globe failed to start (WebGL or tiles unreachable). Search, presets and GPS above still work.')
        return
      }
      mapObj.current = viewer
      const pin = viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(lng, lat),
        point: {
          pixelSize: 14,
          color: Cesium.Color.fromCssColorString('#fbb833'),
          outlineColor: Cesium.Color.fromCssColorString('#1f1f1f'),
          outlineWidth: 3,
        },
        label: {
          text: 'SITE', font: '11px sans-serif',
          fillColor: Cesium.Color.WHITE, outlineColor: Cesium.Color.BLACK, outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(0, -20),
        },
      })
      markerRef.current = pin
      flyTo(viewer, lat, lng, 30000)
      const toLL = (pos) => {
        const cart = viewer.camera.pickEllipsoid(pos)
        if (!cart) return null
        const c = Cesium.Cartographic.fromCartesian(cart)
        return {
          lat: +Cesium.Math.toDegrees(c.latitude).toFixed(5),
          lng: +Cesium.Math.toDegrees(c.longitude).toFixed(5),
        }
      }
      let dragging = false
      handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas)
      handler.setInputAction((e) => {
        const picked = viewer.scene.pick(e.position)
        if (picked && picked.id === markerRef.current) {
          dragging = true
          viewer.scene.screenSpaceCameraController.enableRotate = false
        }
      }, Cesium.ScreenSpaceEventType.LEFT_DOWN)
      handler.setInputAction((m) => {
        if (!dragging) return
        const ll = toLL(m.endPosition)
        if (ll) set({ ...ll, source: 'map pin' })
      }, Cesium.ScreenSpaceEventType.MOUSE_MOVE)
      handler.setInputAction(() => {
        dragging = false
        viewer.scene.screenSpaceCameraController.enableRotate = true
      }, Cesium.ScreenSpaceEventType.LEFT_UP)
      handler.setInputAction((c) => {
        if (dragging) return
        const ll = toLL(c.position)
        if (ll) set({ ...ll, source: 'map tap' })
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK)
    })()
    return () => {
      alive = false
      if (handler) { handler.destroy(); handler = null }
      if (mapObj.current && !mapObj.current.isDestroyed()) { mapObj.current.destroy(); mapObj.current = null }
      markerRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compact])

  // Keep the pin in sync when the point changes elsewhere (search / GPS / preset / EXIF).
  useEffect(() => {
    const viewer = mapObj.current
    if (!viewer || !window.Cesium || viewer.isDestroyed()) return
    if (markerRef.current) {
      markerRef.current.position = window.Cesium.Cartesian3.fromDegrees(lng, lat)
    }
  }, [lat, lng])

  const useMyLocation = () => {
    if (!navigator.geolocation) { setErr('Geolocation not supported here.'); return }
    setGeoLoading(true); setErr('')
    navigator.geolocation.getCurrentPosition(
      (p) => { setGeoLoading(false); set({ lat: +p.coords.latitude.toFixed(5), lng: +p.coords.longitude.toFixed(5), source: 'device GPS' }) },
      () => { setGeoLoading(false); setErr('Location blocked. Allow it in the browser bar, or tap the map.') },
      { timeout: 10000 }
    )
  }

  return (
    <div className="loc">
      <div className="loc-row">
        <label className="loc-search">Find area or address
          <input value={q} placeholder="e.g. HSR Layout, Whitefield…" onChange={e => setQ(e.target.value)} autoComplete="off" />
        </label>
        <label>Area preset
          <select value="" onChange={e => {
            const a = AREAS.find(x => x.name === e.target.value)
            if (a) set({ lat: a.lat, lng: a.lng, address: a.name + ', Bengaluru', source: 'preset' })
          }}>
            <option value="">Pick…</option>
            {AREAS.map(a => <option key={a.name} value={a.name}>{a.name}</option>)}
          </select>
        </label>
        <button type="button" className="cta sm loc-gps" onClick={useMyLocation} disabled={geoLoading}>
          {geoLoading ? 'Locating…' : '◎ Current location'}
        </button>
      </div>
      {searching && <div className="mono small muted">searching…</div>}
      {results.length > 0 && (
        <ul className="loc-results">
          {results.map(r => (
            <li key={r.id}>
              <button type="button" onClick={() => {
                set({ lat: +(+r.lat).toFixed(5), lng: +(+r.lng).toFixed(5), address: r.label, source: HERE_KEY ? 'HERE search' : 'search' })
                setResults([]); setQ('')
              }}>{r.label}</button>
            </li>
          ))}
        </ul>
      )}
      {err && <div className="err" role="alert">{err}</div>}
      {!compact && <div ref={mapRef} className="map loc-mini" role="application" aria-label="Tap to set the site location" />}
      {!compact && mapError && <div className="err" role="alert">{mapError}</div>}
      {!compact && <div className="mono small muted">tap map or drag pin, no coordinates to type</div>}
      <div className="loc-readout">
        <span>📍 {address || 'resolving address…'}</span>
        <span className="mono small">{Number(lat).toFixed(4)}, {Number(lng).toFixed(4)}</span>
        {source && <span className="tag">{source}</span>}
      </div>
    </div>
  )
}
