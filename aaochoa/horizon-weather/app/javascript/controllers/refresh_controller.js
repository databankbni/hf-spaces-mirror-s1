import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["scrollContainer"]
  
  static values = {
    interval: { type: Number, default: 60000 }, // 60 seconds default
    temp: String,
    desc: String,
    time: String,
    icon: String,
    precip: String,
    precipUnit: String,
    metricPrecip: String
  }

  connect() {
    this.startTimer()
    this.boundRestoreScroll = this.restoreScroll.bind(this)
    this.boundSaveScroll = this.saveScroll.bind(this)
    this.element.addEventListener("turbo:frame-load", this.boundRestoreScroll)
    this.element.addEventListener("turbo:submit-start", this.boundSaveScroll)
  }

  disconnect() {
    this.stopTimer()
    this.element.removeEventListener("turbo:frame-load", this.boundRestoreScroll)
    this.element.removeEventListener("turbo:submit-start", this.boundSaveScroll)
  }

  startTimer() {
    this.stopTimer()
    this.timer = setInterval(() => {
      this.refresh()
    }, this.intervalValue)
  }

  stopTimer() {
    if (this.timer) {
      clearInterval(this.timer)
    }
  }

  saveScroll() {
    if (this.hasScrollContainerTarget) {
      this.savedScrollTop = this.scrollContainerTarget.scrollTop
    }
  }

  restoreScroll() {
    if (this.hasScrollContainerTarget && this.savedScrollTop !== undefined) {
      this.scrollContainerTarget.scrollTop = this.savedScrollTop
      this.savedScrollTop = undefined
    }
  }

  refresh() {
    // If the element itself is a turbo-frame, reload it. Otherwise, look for one inside.
    const frame = this.element.tagName === "TURBO-FRAME" ? this.element : this.element.querySelector("turbo-frame")
    if (frame) {
      this.saveScroll()

      // We append a custom query param to bypass cache
      const src = new URL(frame.src || window.location.href)
      src.searchParams.set("refresh", "true")
      
      const newSrc = src.toString()
      if (frame.src !== newSrc) {
        frame.src = newSrc
      } else {
        frame.reload()
      }
    }
  }

  tempValueChanged() {
    this.updateMap()
  }

  descValueChanged() {
    this.updateMap()
  }

  timeValueChanged() {
    this.updateMap()
  }

  iconValueChanged() {
    this.updateMap()
  }

  precipValueChanged() {
    this.updateMap()
  }

  precipUnitValueChanged() {
    this.updateMap()
  }

  metricPrecipValueChanged() {
    this.updateMap()
  }

  updateMap() {
    const mapElement = document.getElementById("weather_map_container")
    if (mapElement) {
      if (this.hasTempValue) mapElement.setAttribute("data-weather-map-temp-value", this.tempValue)
      if (this.hasDescValue) mapElement.setAttribute("data-weather-map-desc-value", this.descValue)
      if (this.hasTimeValue) mapElement.setAttribute("data-weather-map-time-value", this.timeValue)
      if (this.hasIconValue) mapElement.setAttribute("data-weather-map-icon-value", this.iconValue)
      if (this.hasPrecipValue) mapElement.setAttribute("data-weather-map-precip-value", this.precipValue)
      if (this.hasPrecipUnitValue) mapElement.setAttribute("data-weather-map-precip-unit-value", this.precipUnitValue)
      if (this.hasMetricPrecipValue) mapElement.setAttribute("data-metric-precip-value", this.metricPrecipValue)
    }
  }
}
