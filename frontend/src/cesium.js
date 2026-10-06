// Central Cesium helper for UrbanMine's 3D globes.
//
// Have a Cesium ion token? Put it in frontend/.env as:
//   VITE_CESIUM_TOKEN=eyJ...
// That unlocks ion imagery, world terrain and 3D tiles.
// Without a token the globe runs keyless on Esri satellite imagery. Fully functional.

export const CESIUM_TOKEN =
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_CESIUM_TOKEN) || ''

export async function createViewer(el) {
  const Cesium = window.Cesium
  if (!Cesium || !el) return null
  try {
    let baseProvider = null
    let terrainProvider = null
    if (CESIUM_TOKEN) {
      try {
        Cesium.Ion.defaultAccessToken = CESIUM_TOKEN
        baseProvider = await Cesium.createWorldImageryAsync()
        terrainProvider = await Cesium.createWorldTerrainAsync()
      } catch {
        baseProvider = null
        terrainProvider = null
      }
    }
    // NOTE: on 1.119 the constructor imageryProvider option is ignored AND
    // removeAll() strands tile references (render crash). So: construct with
    // baseLayer:false (no default layer to destroy), then add ours on top.
    const viewer = new Cesium.Viewer(el, {
      baseLayer: false,
      animation: false,
      timeline: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      fullscreenButton: false,
      vrButton: false,
      infoBox: true,
      selectionIndicator: true,
    })
    if (!baseProvider) {
      // Keyless satellite: Esri World Imagery via the 1.119-native async
      // factory. NOTE: `new ArcGisMapServerImageryProvider({url})` alone is an
      // UNBUILT shell (no metadata, never ready, crashes tile rendering).
      // fromBasemapType/fromUrl is mandatory on this Cesium version.
      try {
        baseProvider = await Cesium.ArcGisMapServerImageryProvider.fromBasemapType(
          Cesium.ArcGisBaseMapType.SATELLITE
        )
      } catch {
        baseProvider = new Cesium.UrlTemplateImageryProvider({
          url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          credit: 'Imagery © Esri, Maxar, Earthstar Geographics',
          maximumLevel: 19,
        })
      }
    }
    viewer.imageryLayers.addImageryProvider(baseProvider)
    if (terrainProvider) viewer.terrainProvider = terrainProvider
  // Google-Earth atmosphere tuning: sun-driven light + ground atmosphere.
  // Free, works keyless. It adds realistic building shadows to the satellite view.
  try {
    if (viewer.scene && viewer.scene.globe) {
      viewer.scene.globe.showGroundAtmosphere = true
      viewer.scene.globe.enableLighting = true
    }
  } catch { /* older Cesium builds: skip tuning */ }

  // Google-style layout: Photorealistic 3D Tiles replace the globe entirely.
  // Setup: ion dashboard → Asset Depot → add Google Maps Platform
  // Photorealistic 3D Tiles → set VITE_GOOGLE_TILES_ASSET_ID to its asset ID
  // (plus VITE_CESIUM_TOKEN). Without it, the satellite globe stays.
  const tilesAssetId =
    (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_GOOGLE_TILES_ASSET_ID) || ''
  if (CESIUM_TOKEN && tilesAssetId) {
    try {
      const tileset = await Cesium.Cesium3DTileset.fromIonAssetId(Number(tilesAssetId))
      viewer.scene.primitives.add(tileset)
      viewer.scene.globe.show = false
    } catch { /* keep the satellite globe */ }
  }

  // NOTE: no Esri Reference-labels overlay. Its provider deterministically
  // crashes tile rendering (getDerivedResource) in this app. Place names come
  // from our own Nominatim search + pin labels instead.
  return viewer
  } catch {
    return null
  }
}

export function flyTo(viewer, lat, lng, height = 60000) {
  if (!viewer || !window.Cesium || viewer.isDestroyed()) return
  viewer.camera.flyTo({
    destination: window.Cesium.Cartesian3.fromDegrees(lng, lat, height),
    duration: 1.2,
  })
}

export function setPins(viewer, listings) {
  const Cesium = window.Cesium
  if (!viewer || !Cesium || viewer.isDestroyed()) return
  viewer.entities.removeAll()
  listings.forEach((l) => {
    viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(l.lng, l.lat),
      point: {
        pixelSize: 10,
        color: Cesium.Color.fromCssColorString('#fbb833'),
        outlineColor: Cesium.Color.fromCssColorString('#1f1f1f'),
        outlineWidth: 2,
      },
      label: {
        text: String(l.material || ''),
        font: '12px sans-serif',
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -18),
      },
      description:
        `<b>${l.title}</b><br>${l.condition} · ₹${l.price_per_unit}/${l.unit}` +
        `<br>${l.address || ''}`,
    })
  })
}
