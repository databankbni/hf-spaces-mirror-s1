require "net/http"
require "json"

class WeatherService
  CACHE_EXPIRATION = 15.minutes
  GEOCODE_CACHE_EXPIRATION = 1.day

  class << self
    def get_weather(lat, lon, unit_system: "imperial", force_refresh: false)
      cache_key = "weather_forecast_#{lat}_#{lon}_#{unit_system}"

      if force_refresh
        Rails.cache.delete(cache_key)
      end

      data = Rails.cache.fetch(cache_key, expires_in: CACHE_EXPIRATION) do
        fetch_weather_from_api(lat, lon, unit_system)
      end

      if data
        if data["timezone_abbreviation"].is_a?(String)
          data["timezone_abbreviation"] = data["timezone_abbreviation"].gsub("GMT", "UTC")
        end
        if data["daily"]
          inject_lunar_data!(data)
        end
      end

      data || fallback_weather_data(lat, lon, unit_system)
    rescue => e
      Rails.logger.error "WeatherService error: #{e.message}"
      fallback_weather_data(lat, lon, unit_system)
    end

    def search_cities(query)
      return [] if query.blank?

      normalized_query = query.strip.downcase
      cache_key = "city_search_#{normalized_query.parameterize}"

      # 1. Try Rails Cache
      data = Rails.cache.read(cache_key)
      return data if data.present?

      # 2. Try persistent database cache
      db_record = GeocodeCache.find_by(query_type: "search", query_key: normalized_query)
      if db_record
        Rails.cache.write(cache_key, db_record.response_data, expires_in: GEOCODE_CACHE_EXPIRATION)
        return db_record.response_data
      end

      # 3. Fetch from API
      results = fetch_cities_from_api(query)
      if results.present?
        begin
          GeocodeCache.find_or_create_by!(query_type: "search", query_key: normalized_query) do |c|
            c.response_data = results
          end
        rescue ActiveRecord::RecordNotUnique
          # Gracefully handle concurrent request race conditions
        end
        Rails.cache.write(cache_key, results, expires_in: GEOCODE_CACHE_EXPIRATION)
        return results
      end

      fallback_cities(query)
    rescue => e
      Rails.logger.error "WeatherService geocoding error: #{e.message}"
      fallback_cities(query)
    end

    def reverse_geocode(lat, lon)
      rounded_lat = lat.to_f.round(4)
      rounded_lon = lon.to_f.round(4)
      coord_key = "#{rounded_lat},#{rounded_lon}"
      cache_key = "reverse_geocode_#{coord_key}"

      # 1. Try Rails Cache
      data = Rails.cache.read(cache_key)
      return data if data.present?

      # 2. Try persistent database cache
      db_record = GeocodeCache.find_by(query_type: "reverse", query_key: coord_key)
      if db_record
        Rails.cache.write(cache_key, db_record.response_data, expires_in: 30.days)
        return db_record.response_data
      end

      # 3. Fetch from API
      name = fetch_city_from_coords(rounded_lat, rounded_lon)
      if name.present? && !name.start_with?("Coordinates:")
        begin
          GeocodeCache.find_or_create_by!(query_type: "reverse", query_key: coord_key) do |c|
            c.response_data = name
          end
        rescue ActiveRecord::RecordNotUnique
          # Gracefully handle concurrent request race conditions
        end
      end

      # Write to Rails cache (even if fallback string, to avoid spamming endpoint)
      Rails.cache.write(cache_key, name, expires_in: 30.days)
      name
    rescue => e
      Rails.logger.error "WeatherService reverse geocoding error: #{e.message}"
      "Coordinates: #{rounded_lat}, #{rounded_lon}"
    end

    def weather_info(code, is_day = 1)
      is_day_bool = (is_day.to_i == 1)

      # WMO Weather interpretation codes (WMOCodes)
      case code
      when 0
        { description: "Clear Sky", icon: is_day_bool ? "sun" : "moon", gif_query: is_day_bool ? "sunny clear sky weather" : "clear night sky" }
      when 1
        { description: "Mainly Clear", icon: is_day_bool ? "cloud-sun" : "cloud-moon", gif_query: is_day_bool ? "mostly sunny weather" : "clear night sky cloudy" }
      when 2
        { description: "Partly Cloudy", icon: "cloud", gif_query: "partly cloudy sky" }
      when 3
        { description: "Overcast", icon: "cloudy", gif_query: "overcast cloudy sky" }
      when 45, 48
        { description: "Foggy", icon: "cloud-fog", gif_query: "foggy misty weather" }
      when 51, 53, 55
        { description: "Drizzle", icon: "cloud-drizzle", gif_query: "light drizzle rain" }
      when 56, 57
        { description: "Freezing Drizzle", icon: "cloud-snow", gif_query: "freezing rain sleet" }
      when 61, 63, 65
        { description: "Rainy", icon: "cloud-rain", gif_query: "heavy rain storm" }
      when 66, 67
        { description: "Freezing Rain", icon: "cloud-snow", gif_query: "freezing rain ice storm" }
      when 71, 73, 75
        { description: "Snowy", icon: "cloud-snow", gif_query: "heavy snowfall blizzard" }
      when 77
        { description: "Snow Grains", icon: "cloud-snow", gif_query: "snow flurries winter" }
      when 80, 81, 82
        { description: "Rain Showers", icon: "cloud-rain", gif_query: "rain shower weather" }
      when 85, 86
        { description: "Snow Showers", icon: "cloud-snow", gif_query: "snow shower winter storm" }
      when 95, 96, 99
        { description: "Thunderstorm", icon: "cloud-lightning", gif_query: "thunderstorm lightning storm" }
      else
        { description: "Unknown", icon: "help-circle", gif_query: "weather sky" }
      end
    end

    def moon_phase_details(phase_value)
      phase_value = phase_value.to_f

      if phase_value == 0 || phase_value == 1
        name = "New Moon"
        emoji = "🌑"
      elsif phase_value > 0 && phase_value < 0.25
        name = "Waxing Crescent"
        emoji = "🌒"
      elsif phase_value == 0.25
        name = "First Quarter"
        emoji = "🌓"
      elsif phase_value > 0.25 && phase_value < 0.5
        name = "Waxing Gibbous"
        emoji = "🌔"
      elsif phase_value == 0.5
        name = "Full Moon"
        emoji = "🌕"
      elsif phase_value > 0.5 && phase_value < 0.75
        name = "Waning Gibbous"
        emoji = "🌖"
      elsif phase_value == 0.75
        name = "Third Quarter"
        emoji = "🌗"
      else
        name = "Waning Crescent"
        emoji = "🌘"
      end

      illumination = if phase_value <= 0.5
        (phase_value * 2 * 100).round
      else
        ((1 - phase_value) * 2 * 100).round
      end

      { name: name, emoji: emoji, illumination: illumination }
    end

    private

    def inject_lunar_data!(data)
      daily = data["daily"]
      return unless daily

      times = daily["time"] || []
      sunrises = daily["sunrise"] || []
      sunsets = daily["sunset"] || []

      moon_phases = []
      moonrises = []
      moonsets = []

      times.each_with_index do |time_str, index|
        date = Date.parse(time_str) rescue Date.current
        phase = calculate_moon_phase(date)
        moon_phases << phase

        sunrise_str = sunrises[index]
        sunset_str = sunsets[index]

        m_rise, m_set = calculate_moonrise_moonset(date, sunrise_str, sunset_str, phase)
        moonrises << m_rise
        moonsets << m_set
      end

      daily["moon_phase"] = moon_phases
      daily["moonrise"] = moonrises
      daily["moonset"] = moonsets
    end

    def calculate_moon_phase(date)
      epoch = Time.utc(2000, 1, 6, 18, 14)
      lunar_cycle = 29.530588853

      diff = date.to_time.utc.to_f - epoch.to_f
      days_since_new = (diff / 86400.0) % lunar_cycle
      days_since_new / lunar_cycle
    end

    def calculate_moonrise_moonset(date, sunrise_str, sunset_str, phase_val)
      return [ nil, nil ] unless sunrise_str && sunset_str

      sunrise = Time.parse(sunrise_str) rescue nil
      sunset = Time.parse(sunset_str) rescue nil
      return [ nil, nil ] unless sunrise && sunset

      # Moonrise/moonset offset in hours based on phase
      moon_offset = phase_val * 24.0

      moonrise = sunrise + moon_offset.hours
      moonset = sunset + moon_offset.hours

      [ moonrise.strftime("%Y-%m-%dT%H:%M"), moonset.strftime("%Y-%m-%dT%H:%M") ]
    end

    def fetch_weather_from_api(lat, lon, unit_system)
      api_key = ENV["OPENWEATHERMAP_API_KEY"] || Rails.application.credentials.openweathermap_api_key

      if api_key.present?
        fetch_from_openweathermap(lat, lon, api_key, unit_system)
      else
        fetch_from_open_meteo(lat, lon, unit_system)
      end
    end

    def fetch_from_open_meteo(lat, lon, unit_system)
      url = "https://api.open-meteo.com/v1/forecast?latitude=#{lat}&longitude=#{lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,showers,snowfall,weather_code,wind_speed_10m&hourly=temperature_2m,precipitation_probability,weather_code,is_day&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,sunrise,sunset&timezone=auto"
      if unit_system == "imperial"
        url += "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
      end

      uri = URI(url)
      http = Net::HTTP.new(uri.host, uri.port)
      http.use_ssl = (uri.scheme == "https")
      http.open_timeout = 2
      http.read_timeout = 2
      response = http.get(uri.request_uri)

      if response.is_a?(Net::HTTPSuccess)
        JSON.parse(response.body)
      else
        Rails.logger.error "Open-Meteo API failure: #{response.code} #{response.message}"
        nil
      end
    end

    def fetch_from_openweathermap(lat, lon, api_key, unit_system)
      units = (unit_system == "imperial") ? "imperial" : "metric"
      url = "https://api.openweathermap.org/data/3.0/onecall?lat=#{lat}&lon=#{lon}&units=#{units}&appid=#{api_key}"

      uri = URI(url)
      http = Net::HTTP.new(uri.host, uri.port)
      http.use_ssl = (uri.scheme == "https")
      http.open_timeout = 2
      http.read_timeout = 2
      response = http.get(uri.request_uri)

      if response.is_a?(Net::HTTPSuccess)
        body = JSON.parse(response.body)
        translate_owm_to_open_meteo(body, unit_system)
      else
        Rails.logger.error "OpenWeatherMap API failure: #{response.code} #{response.message}"
        nil
      end
    rescue => e
      Rails.logger.error "OpenWeatherMap fetch error: #{e.message}"
      nil
    end

    def translate_owm_to_open_meteo(body, unit_system)
      return nil unless body.is_a?(Hash)

      timezone = body["timezone"] || "UTC"
      timezone_abbr = Time.current.in_time_zone(timezone).strftime("%Z") rescue "UTC"
      timezone_abbr = timezone_abbr.gsub("GMT", "UTC") if timezone_abbr.is_a?(String)

      current_data = body["current"] || {}
      current_weather = current_data["weather"]&.first || {}
      current_wmo = map_owm_id_to_wmo(current_weather["id"])

      # Precipitation calculation (rain + snow 1h values)
      current_precip = (current_data.dig("rain", "1h") || 0.0) + (current_data.dig("snow", "1h") || 0.0)
      rain = current_data.dig("rain", "1h") || 0.0
      snow = current_data.dig("snow", "1h") || 0.0

      if unit_system == "imperial"
        current_precip = (current_precip / 25.4).round(2)
        rain = (rain / 25.4).round(2)
        snow = (snow / 25.4).round(2)
      end

      # OpenWeatherMap wind speed. If imperial, it is already in mph. Otherwise, convert from m/s to km/h by multiplying by 3.6.
      wind_speed = if unit_system == "imperial"
        current_data["wind_speed"].to_f.round(1)
      else
        (current_data["wind_speed"].to_f * 3.6).round(1)
      end

      hourly_data = body["hourly"] || []
      hourly_times = []
      hourly_temps = []
      hourly_precip_probs = []
      hourly_wmos = []
      hourly_is_days = []

      daily_data = body["daily"] || []

      hourly_data.each do |hour|
        hour_time = Time.at(hour["dt"]).in_time_zone(timezone) rescue Time.current
        hourly_times << hour_time.strftime("%Y-%m-%dT%H:%M")
        hourly_temps << hour["temp"].to_f
        hourly_precip_probs << ((hour["pop"].to_f * 100).round rescue 0)
        hour_weather = hour["weather"]&.first || {}
        hourly_wmos << map_owm_id_to_wmo(hour_weather["id"])

        # Calculate hourly is_day
        hour_day = hour_time.beginning_of_day
        daily_rec = daily_data.find { |d| Time.at(d["dt"]).in_time_zone(timezone).beginning_of_day == hour_day }
        is_day_val = 1
        if daily_rec
          sunrise = daily_rec["sunrise"]
          sunset = daily_rec["sunset"]
          is_day_val = (hour["dt"] >= sunrise && hour["dt"] <= sunset) ? 1 : 0
        end
        hourly_is_days << is_day_val
      end

      daily_data = body["daily"] || []
      daily_times = []
      daily_wmos = []
      daily_temp_maxs = []
      daily_temp_mins = []
      daily_precip_sums = []
      daily_sunrises = []
      daily_sunsets = []
      daily_moonrises = []
      daily_moonsets = []
      daily_moon_phases = []

      daily_data.each do |day|
        day_time = Time.at(day["dt"]).in_time_zone(timezone) rescue Time.current
        daily_times << day_time.strftime("%Y-%m-%d")

        day_weather = day["weather"]&.first || {}
        daily_wmos << map_owm_id_to_wmo(day_weather["id"])

        daily_temp_maxs << day.dig("temp", "max").to_f
        daily_temp_mins << day.dig("temp", "min").to_f

        day_precip = (day["rain"] || 0.0) + (day["snow"] || 0.0)
        if unit_system == "imperial"
          day_precip = (day_precip / 25.4).round(2)
        end
        daily_precip_sums << day_precip.to_f

        daily_sunrises << (Time.at(day["sunrise"]).in_time_zone(timezone).strftime("%Y-%m-%dT%H:%M") rescue nil)
        daily_sunsets << (Time.at(day["sunset"]).in_time_zone(timezone).strftime("%Y-%m-%dT%H:%M") rescue nil)
        daily_moonrises << (Time.at(day["moonrise"]).in_time_zone(timezone).strftime("%Y-%m-%dT%H:%M") rescue nil)
        daily_moonsets << (Time.at(day["moonset"]).in_time_zone(timezone).strftime("%Y-%m-%dT%H:%M") rescue nil)
        daily_moon_phases << day["moon_phase"].to_f
      end

      {
        "latitude" => body["lat"],
        "longitude" => body["lon"],
        "timezone" => timezone,
        "timezone_abbreviation" => timezone_abbr,
        "current" => {
          "temperature_2m" => current_data["temp"].to_f,
          "relative_humidity_2m" => current_data["humidity"].to_i,
          "apparent_temperature" => current_data["feels_like"].to_f,
          "is_day" => (current_data["dt"] >= current_data["sunrise"] && current_data["dt"] <= current_data["sunset"] ? 1 : 0 rescue 1),
          "precipitation" => current_precip,
          "rain" => rain,
          "showers" => 0.0,
          "snowfall" => snow,
          "weather_code" => current_wmo,
          "wind_speed_10m" => wind_speed
        },
        "hourly" => {
          "time" => hourly_times,
          "temperature_2m" => hourly_temps,
          "precipitation_probability" => hourly_precip_probs,
          "weather_code" => hourly_wmos,
          "is_day" => hourly_is_days
        },
        "daily" => {
          "time" => daily_times,
          "weather_code" => daily_wmos,
          "temperature_2m_max" => daily_temp_maxs,
          "temperature_2m_min" => daily_temp_mins,
          "precipitation_sum" => daily_precip_sums,
          "sunrise" => daily_sunrises,
          "sunset" => daily_sunsets,
          "moonrise" => daily_moonrises,
          "moonset" => daily_moonsets,
          "moon_phase" => daily_moon_phases
        }
      }
    end

    def map_owm_id_to_wmo(id)
      id = id.to_i
      case id
      when 800 then 0 # Clear Sky
      when 801 then 1 # Mainly Clear
      when 802 then 2 # Partly Cloudy
      when 803, 804 then 3 # Overcast
      when 701, 741 then 45 # Foggy / Mist
      when 300..321 then 51 # Drizzle
      when 500, 501 then 61 # Light Rain
      when 502, 503, 504 then 65 # Heavy Rain
      when 511 then 66 # Freezing Rain
      when 600..602 then 71 # Snow
      when 611..622 then 85 # Snow showers
      when 520..531 then 80 # Rain Showers
      when 200..232 then 95 # Thunderstorm
      else 2 # Partly Cloudy default
      end
    end

    def fetch_cities_from_api(query)
      escaped_query = CGI.escape(query)
      url = "https://geocoding-api.open-meteo.com/v1/search?name=#{escaped_query}&count=8&language=en&format=json"

      uri = URI(url)
      http = Net::HTTP.new(uri.host, uri.port)
      http.use_ssl = (uri.scheme == "https")
      http.open_timeout = 2
      http.read_timeout = 2
      response = http.get(uri.request_uri)

      if response.is_a?(Net::HTTPSuccess)
        data = JSON.parse(response.body)
        results = data["results"] || []
        results.map do |city|
          {
            name: [ city["name"], city["admin1"], city["country"] ].compact.join(", "),
            latitude: city["latitude"],
            longitude: city["longitude"],
            country: city["country"],
            country_code: city["country_code"]
          }
        end
      else
        Rails.logger.error "Open-Meteo Geocoding API failure: #{response.code} #{response.message}"
        []
      end
    end

    def fetch_city_from_coords(lat, lon)
      url = "https://nominatim.openstreetmap.org/reverse?format=json&lat=#{lat}&lon=#{lon}&zoom=10&addressdetails=1&accept-language=en"
      uri = URI(url)

      req = Net::HTTP::Get.new(uri)
      req["User-Agent"] = "HorizonWeather/1.0 (contact: aaochoa@horizon.com)"

      response = Net::HTTP.start(uri.hostname, uri.port, use_ssl: uri.scheme == "https", open_timeout: 2, read_timeout: 2) do |http|
        http.request(req)
      end

      if response.is_a?(Net::HTTPSuccess)
        data = JSON.parse(response.body)
        address = data["address"]
        if address
          city = address["city"] || address["town"] || address["village"] || address["municipality"] || address["suburb"]
          state = address["state"] || address["region"]
          country = address["country"]
          [ city, state, country ].compact.join(", ")
        else
          data["display_name"] || "Coordinates: #{lat}, #{lon}"
        end
      else
        Rails.logger.error "Nominatim Reverse Geocoding API failure: #{response.code} #{response.message}"
        "Coordinates: #{lat}, #{lon}"
      end
    rescue => e
      Rails.logger.error "Nominatim API fetch error: #{e.message}"
      "Coordinates: #{lat}, #{lon}"
    end

    def fallback_weather_data(lat, lon, unit_system = "imperial")
      is_imperial = (unit_system == "imperial")

      temp_conv = ->(c) { is_imperial ? (c * 9.0 / 5.0 + 32).round(1) : c }
      wind_conv = ->(k) { is_imperial ? (k * 0.621371).round(1) : k }
      prec_conv = ->(m) { is_imperial ? (m / 25.4).round(2) : m }

      {
        "latitude" => lat,
        "longitude" => lon,
        "current" => {
          "temperature_2m" => temp_conv.call(21.5),
          "relative_humidity_2m" => 64,
          "apparent_temperature" => temp_conv.call(20.8),
          "is_day" => 1,
          "precipitation" => prec_conv.call(0.0),
          "rain" => prec_conv.call(0.0),
          "showers" => prec_conv.call(0.0),
          "snowfall" => prec_conv.call(0.0),
          "weather_code" => 2, # Partly Cloudy
          "wind_speed_10m" => wind_conv.call(12.5)
        },
        "hourly" => {
          "time" => Array.new(24) { |i| (Time.current + i.hours).strftime("%Y-%m-%dT%H:00") },
          "temperature_2m" => Array.new(24) { |i| temp_conv.call(21.5 + Math.sin(i / 3.0) * 3) },
          "precipitation_probability" => Array.new(24) { |i| [ 0, 10, 20, 30 ][i % 4] },
          "weather_code" => Array.new(24) { 2 },
          "is_day" => Array.new(24) { |i|
            hr = (Time.current + i.hours).hour
            (hr >= 6 && hr < 20) ? 1 : 0
          }
        },
        "daily" => {
          "time" => Array.new(7) { |i| (Date.current + i.days).strftime("%Y-%m-%d") },
          "weather_code" => [ 2, 1, 0, 3, 61, 80, 2 ],
          "temperature_2m_max" => [ 24, 25, 27, 23, 20, 22, 24 ].map { |t| temp_conv.call(t) },
          "temperature_2m_min" => [ 15, 16, 17, 14, 12, 13, 15 ].map { |t| temp_conv.call(t) },
          "precipitation_sum" => [ 0.0, 0.0, 0.0, 0.5, 4.2, 1.8, 0.0 ].map { |p| prec_conv.call(p) },
          "sunrise" => Array.new(7) { |i| (Time.current.beginning_of_day + i.days + 6.hours).strftime("%Y-%m-%dT%H:%M") },
          "sunset" => Array.new(7) { |i| (Time.current.beginning_of_day + i.days + 20.hours).strftime("%Y-%m-%dT%H:%M") },
          "moonrise" => Array.new(7) { |i| (Time.current.beginning_of_day + i.days + 22.hours).strftime("%Y-%m-%dT%H:%M") },
          "moonset" => Array.new(7) { |i| (Time.current.beginning_of_day + i.days + 8.hours).strftime("%Y-%m-%dT%H:%M") },
          "moon_phase" => [ 0.1, 0.25, 0.4, 0.5, 0.65, 0.8, 0.95 ]
        },
        "is_fallback" => true
      }
    end

    def fallback_cities(query)
      [
        { name: "Chicago, Illinois, United States", latitude: 41.8781, longitude: -87.6298, country: "United States", country_code: "US" },
        { name: "New York, New York, United States", latitude: 40.7128, longitude: -74.0060, country: "United States", country_code: "US" },
        { name: "London, England, United Kingdom", latitude: 51.5074, longitude: -0.1278, country: "United Kingdom", country_code: "GB" },
        { name: "Tokyo, Tokyo, Japan", latitude: 35.6762, longitude: 139.6503, country: "Japan", country_code: "JP" }
      ].select { |c| c[:name].downcase.include?(query.downcase) }
    end
  end
end
