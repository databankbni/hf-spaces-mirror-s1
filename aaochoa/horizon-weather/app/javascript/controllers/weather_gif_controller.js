import { Controller } from "@hotwired/stimulus"

// Fetches a weather-themed GIF from Tenor and swaps it into the icon slot.
// Falls back gracefully to the Lucide icon if no API key is configured
// or if the network request fails.
export default class extends Controller {
  static targets = ["icon", "gif"]
  static values = {
    query: String,
    apiKey: String
  }

  connect() {
    if (this.hasApiKeyValue && this.apiKeyValue.length > 0) {
      this.fetchGif()
    }
    // Without an API key the Lucide icon is displayed as-is
  }

  async fetchGif() {
    try {
      const url = `https://tenor.googleapis.com/v2/search?q=${encodeURIComponent(this.queryValue)}&key=${this.apiKeyValue}&client_key=horizon_weather&limit=8&contentfilter=medium&media_filter=gif`
      const response = await fetch(url)
      if (!response.ok) throw new Error(`Tenor API error: ${response.status}`)

      const data = await response.json()
      const results = data.results

      if (!results || results.length === 0) return

      // Pick a random result from the first 8 for variety
      const pick = results[Math.floor(Math.random() * results.length)]
      const gifUrl = pick.media_formats?.gif?.url || pick.media_formats?.tinygif?.url

      if (!gifUrl) return

      // Swap icon → GIF
      if (this.hasIconTarget) {
        this.iconTarget.classList.add("hidden")
      }

      if (this.hasGifTarget) {
        this.gifTarget.src = gifUrl
        this.gifTarget.alt = this.queryValue
        this.gifTarget.classList.remove("hidden")
        this.gifTarget.classList.add("opacity-0")

        this.gifTarget.onload = () => {
          this.gifTarget.classList.remove("opacity-0")
          this.gifTarget.classList.add("opacity-100")
        }
      }
    } catch (error) {
      // Silently fall back to icon — already visible by default
      console.warn("WeatherGif: could not load GIF", error)
    }
  }
}
