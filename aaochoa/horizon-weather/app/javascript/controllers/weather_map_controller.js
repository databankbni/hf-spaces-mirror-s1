import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["canvas"]
  static values = {
    lat: Number,
    lon: Number,
    name: String,
    temp: String,
    desc: String,
    time: String,
    icon: String,
    unitSymbol: { type: String, default: "°C" },
    precip: String,
    precipUnit: String
  }

  connect() {
    this.initMap()
    this.themeChangedListener = this.onThemeChanged.bind(this)
    document.addEventListener("theme-changed", this.themeChangedListener)

    this.unitsChangedListener = this.onUnitsChanged.bind(this)
    document.addEventListener("units-changed", this.unitsChangedListener)
  }

  disconnect() {
    this.destroyMap()
    if (this.updateTimeout) clearTimeout(this.updateTimeout)
    document.removeEventListener("theme-changed", this.themeChangedListener)
    document.removeEventListener("units-changed", this.unitsChangedListener)
  }

  onThemeChanged(event) {
    if (this.map && this.tileLayer) {
      this.map.removeLayer(this.tileLayer)
      const isDark = event.detail.theme === "dark"
      const tileUrl = isDark 
        ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
      
      this.tileLayer = L.tileLayer(tileUrl, {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: "abcd",
        maxZoom: 20,
        className: "map-tiles"
      }).addTo(this.map)
    }
  }

  onUnitsChanged(event) {
    const { unitSymbol, temp, precip, precipUnit } = event.detail
    this.unitSymbolValue = unitSymbol
    this.tempValue = temp
    if (precip !== undefined) this.precipValue = precip
    if (precipUnit !== undefined) this.precipUnitValue = precipUnit

    if (this.marker) {
      const markerElement = this.marker.getElement()
      if (markerElement) {
        const tempSpan = markerElement.querySelector('span.relative')
        if (tempSpan) {
          tempSpan.textContent = `${Math.round(parseFloat(temp))}°`
        }
      }

      const popupContent = this.getPopupContent(this.latValue, this.lonValue)
      this.marker.setPopupContent(popupContent)
      if (typeof lucide !== 'undefined') lucide.createIcons()
    }
  }

  initMap() {
    this.destroyMap()

    const lat = this.latValue
    const lon = this.lonValue

    // Initialize Leaflet Map on the canvas target
    this.map = L.map(this.canvasTarget, {
      zoomControl: false,
      scrollWheelZoom: true
    }).setView([lat, lon], 10)

    // Move Zoom controls to bottom-right to avoid overlapping the left sidebar
    L.control.zoom({
      position: 'bottomright'
    }).addTo(this.map)

    const isDark = document.documentElement.classList.contains("dark")
    const tileUrl = isDark 
      ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
      : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"

    // Theme-themed Map Tiles (CartoDB Dark Matter / Positron)
    this.tileLayer = L.tileLayer(tileUrl, {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20,
      className: "map-tiles"
    }).addTo(this.map)

    // Custom CSS-styled marker for Leaflet
    const markerHtml = `
      <div class="relative flex items-center justify-center">
        <span class="absolute inline-flex h-8 w-8 rounded-full bg-cyan-400/40 animate-ping"></span>
        <span class="relative inline-flex rounded-full h-5 w-5 bg-cyan-500 border-2 border-slate-900 shadow-md flex items-center justify-center text-slate-950 font-bold text-[9px] select-none">
          ${Math.round(parseFloat(this.tempValue))}°
        </span>
      </div>
    `

    const customIcon = L.divIcon({
      html: markerHtml,
      className: 'custom-map-marker',
      iconSize: [32, 32],
      iconAnchor: [16, 16],
      popupAnchor: [0, -10]
    })

    // Call lucide.createIcons on popup open
    this.map.on("popupopen", () => {
      if (typeof lucide !== 'undefined') lucide.createIcons()
    })

    // Place Marker
    this.marker = L.marker([lat, lon], { icon: customIcon }).addTo(this.map)

    // Bind Popup with weather status
    const popupContent = this.getPopupContent(lat, lon)
    this.marker.bindPopup(popupContent).openPopup()

    // Bind click listener to select places on click
    this.map.on("click", (e) => {
      const { lat, lng } = e.latlng
      this.selectCoordinates(lat, lng)
    })

    // Ensure Leaflet updates size if the layout is dynamically rendered/resized
    setTimeout(() => {
      if (this.map) {
        this.map.invalidateSize()
      }
    }, 100)
  }

  selectCoordinates(lat, lon) {
    const url = new URL(window.location.origin)
    url.searchParams.set("lat", lat.toFixed(4))
    url.searchParams.set("lon", lon.toFixed(4))

    if (window.Turbo) {
      window.Turbo.visit(url.toString())
    } else {
      window.location.href = url.toString()
    }
  }


  destroyMap() {
    if (this.map) {
      this.map.off()
      this.map.remove()
      this.map = null
    }
  }

  latValueChanged() { this.updateMapPosition() }
  lonValueChanged() { this.updateMapPosition() }
  tempValueChanged() { this.updateMapPosition() }
  nameValueChanged() { this.updateMapPosition() }
  descValueChanged() { this.updateMapPosition() }
  timeValueChanged() { this.updateMapPosition() }
  iconValueChanged() { this.updateMapPosition() }
  precipValueChanged() { this.updateMapPosition() }
  precipUnitValueChanged() { this.updateMapPosition() }

  getPopupContent(lat, lon) {
    const precipHtml = this.hasPrecipValue ? `
      <div class="flex items-center gap-1.5 mt-2 text-xs text-slate-500 dark:text-slate-400">
        <i data-lucide="cloud-rain" class="w-3.5 h-3.5 text-cyan-500 dark:text-cyan-400 shrink-0"></i>
        <span>Precipitation: <strong class="text-slate-700 dark:text-slate-300">${this.precipValue} ${this.precipUnitValue}</strong></span>
      </div>
    ` : '';

    return `
      <div class="flex items-center justify-between gap-4 p-1 text-slate-900 dark:text-slate-100 font-sans min-w-[260px] max-w-[320px]">
        <div class="flex-grow text-left">
          <h4 class="font-bold text-sm leading-tight text-slate-900 dark:text-slate-100">${this.nameValue}</h4>
          ${this.hasTimeValue ? `<p class="text-xs font-semibold text-slate-500 dark:text-slate-400 mt-1">${this.timeValue}</p>` : ''}
          <div class="flex items-center gap-2 mt-2">
            <span class="text-2xl font-black text-slate-800 dark:text-slate-200">${this.tempValue}${this.unitSymbolValue}</span>
            <span class="text-xs font-semibold px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20">${this.descValue}</span>
          </div>
          ${precipHtml}
          <p class="text-[10px] text-slate-400 dark:text-slate-500 mt-2.5">Coordinates: ${lat.toFixed(4)}, ${lon.toFixed(4)}</p>
        </div>
        ${this.hasIconValue ? `
          <i data-lucide="${this.iconValue}" class="w-16 h-16 text-cyan-500 dark:text-cyan-400 shrink-0 stroke-[1.2]"></i>
        ` : ''}
      </div>
    `
  }

  updateMapPosition() {
    if (this.map && this.marker) {
      if (this.updateTimeout) clearTimeout(this.updateTimeout)
      this.updateTimeout = setTimeout(() => {
        const lat = this.latValue
        const lon = this.lonValue

        // Smooth pan map to new coordinates
        this.map.panTo([lat, lon])
        this.marker.setLatLng([lat, lon])

        const popupContent = this.getPopupContent(lat, lon)
        this.marker.setPopupContent(popupContent)
        if (typeof lucide !== 'undefined') lucide.createIcons()

        const markerElement = this.marker.getElement()
        if (markerElement) {
          const tempSpan = markerElement.querySelector('span.relative')
          if (tempSpan) {
            tempSpan.textContent = `${Math.round(parseFloat(this.tempValue))}°`
          }
        }
      }, 50)
    }
  }
}
