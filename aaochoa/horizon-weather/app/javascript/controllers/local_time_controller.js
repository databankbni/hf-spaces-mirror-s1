import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static values = {
    utc: String
  }

  connect() {
    const date = new Date(this.utcValue)
    if (!isNaN(date.getTime())) {
      let hours = date.getHours()
      const minutes = String(date.getMinutes()).padStart(2, '0')
      const seconds = String(date.getSeconds()).padStart(2, '0')
      const ampm = hours >= 12 ? 'PM' : 'AM'
      hours = hours % 12
      hours = hours ? hours : 12 // the hour '0' should be '12'
      const hoursStr = String(hours).padStart(2, '0')
      this.element.textContent = `${hoursStr}:${minutes}:${seconds} ${ampm}`
    }
  }
}
