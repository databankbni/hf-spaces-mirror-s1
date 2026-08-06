require "test_helper"

class WeatherServiceTest < ActiveSupport::TestCase
  test "weather_info returns appropriate details for WMO codes" do
    clear_sky = WeatherService.weather_info(0)
    assert_equal "Clear Sky", clear_sky[:description]
    assert_equal "sun", clear_sky[:icon]
    assert_equal "sunny clear sky weather", clear_sky[:gif_query]

    thunderstorm = WeatherService.weather_info(95)
    assert_equal "Thunderstorm", thunderstorm[:description]
    assert_equal "cloud-lightning", thunderstorm[:icon]
    assert_equal "thunderstorm lightning storm", thunderstorm[:gif_query]

    unknown = WeatherService.weather_info(999)
    assert_equal "Unknown", unknown[:description]
    assert_equal "help-circle", unknown[:icon]
    assert_equal "weather sky", unknown[:gif_query]
  end

  test "get_weather fetches and returns weather data" do
    class << WeatherService
      alias_method :original_fetch_weather, :fetch_weather_from_api
      def fetch_weather_from_api(lat, lon, unit_system = "imperial")
        { "current" => { "temperature_2m" => 22.5 } }
      end
    end

    begin
      result = WeatherService.get_weather(41.8781, -87.6298, force_refresh: true)
      assert_equal 22.5, result["current"]["temperature_2m"]
    ensure
      class << WeatherService
        alias_method :fetch_weather_from_api, :original_fetch_weather
        remove_method :original_fetch_weather
      end
    end
  end

  test "search_cities returns list of matches" do
    class << WeatherService
      alias_method :original_fetch_cities, :fetch_cities_from_api
      def fetch_cities_from_api(query)
        [ { name: "Chicago, IL, USA", latitude: 41.8781, longitude: -87.6298, country: "USA", country_code: "US" } ]
      end
    end

    begin
      results = WeatherService.search_cities("Chicago")
      assert_equal 1, results.size
      assert_equal "Chicago, IL, USA", results.first[:name]
    ensure
      class << WeatherService
        alias_method :fetch_cities_from_api, :original_fetch_cities
        remove_method :original_fetch_cities
      end
    end
  end

  test "moon_phase_details returns correct description, emoji, and illumination" do
    new_moon = WeatherService.moon_phase_details(0)
    assert_equal "New Moon", new_moon[:name]
    assert_equal "🌑", new_moon[:emoji]
    assert_equal 0, new_moon[:illumination]

    first_quarter = WeatherService.moon_phase_details(0.25)
    assert_equal "First Quarter", first_quarter[:name]
    assert_equal "🌓", first_quarter[:emoji]
    assert_equal 50, first_quarter[:illumination]

    full_moon = WeatherService.moon_phase_details(0.5)
    assert_equal "Full Moon", full_moon[:name]
    assert_equal "🌕", full_moon[:emoji]
    assert_equal 100, full_moon[:illumination]

    third_quarter = WeatherService.moon_phase_details(0.75)
    assert_equal "Third Quarter", third_quarter[:name]
    assert_equal "🌗", third_quarter[:emoji]
    assert_equal 50, third_quarter[:illumination]

    gibbous = WeatherService.moon_phase_details(0.4)
    assert_equal "Waxing Gibbous", gibbous[:name]
    assert_equal "🌔", gibbous[:emoji]
    assert_equal 80, gibbous[:illumination]
  end

  test "reverse_geocode returns formatted address on success" do
    stub_weather_service(:fetch_city_from_coords, "Paris, Île-de-France, France") do
      result = WeatherService.reverse_geocode(48.8566, 2.3522)
      assert_equal "Paris, Île-de-France, France", result
    end
  end

  test "reverse_geocode returns coordinate fallback on failure/timeout" do
    # Clear cache first to ensure it hits the stubbed method
    Rails.cache.delete("reverse_geocode_48.8566_2.3522")

    err_proc = ->(lat, lon) { raise Net::OpenTimeout.new("timeout") }
    stub_weather_service(:fetch_city_from_coords, err_proc) do
      result = WeatherService.reverse_geocode(48.8566, 2.3522)
      assert_equal "Coordinates: 48.8566, 2.3522", result
    end
  end

  test "get_weather returns fallback data when API returns nil" do
    stub_weather_service(:fetch_weather_from_api, nil) do
      result = WeatherService.get_weather(41.8781, -87.6298, unit_system: "metric", force_refresh: true)
      assert result["is_fallback"]
      assert_equal 21.5, result["current"]["temperature_2m"]

      result_imp = WeatherService.get_weather(41.8781, -87.6298, unit_system: "imperial", force_refresh: true)
      assert result_imp["is_fallback"]
      assert_equal 70.7, result_imp["current"]["temperature_2m"]
    end
  end

  test "get_weather returns fallback data when API raises network exception" do
    err_proc = ->(lat, lon, *args) { raise Net::OpenTimeout.new("timeout") }
    stub_weather_service(:fetch_weather_from_api, err_proc) do
      result = WeatherService.get_weather(41.8781, -87.6298, unit_system: "metric", force_refresh: true)
      assert result["is_fallback"]
      assert_equal 21.5, result["current"]["temperature_2m"]
    end
  end

  test "search_cities returns fallback cities when API fails" do
    stub_weather_service(:fetch_cities_from_api, ->(q) { [] }) do
      results = WeatherService.search_cities("Chicago")
      assert_equal 1, results.size
      assert_equal "Chicago, Illinois, United States", results.first[:name]
    end
  end

  test "get_weather force_refresh deletes cache key" do
    cache_key = "weather_forecast_41.8781_-87.6298_imperial"
    Rails.cache.write(cache_key, { "current" => { "temperature_2m" => 10.0 } })

    mock_api = ->(lat, lon, *args) { { "current" => { "temperature_2m" => 25.0 } } }
    stub_weather_service(:fetch_weather_from_api, mock_api) do
      result = WeatherService.get_weather(41.8781, -87.6298, force_refresh: true)
      assert_equal 25.0, result["current"]["temperature_2m"]
    end
  end

  test "search_cities reads from database cache on Rails cache miss" do
    memory_store = ActiveSupport::Cache.lookup_store(:memory_store)
    original_cache = Rails.cache
    begin
      Rails.cache = memory_store
      GeocodeCache.delete_all

      GeocodeCache.create!(
        query_type: "search",
        query_key: "chicago",
        response_data: [ { name: "Chicago, IL, Cached in DB" } ]
      )

      # API is mocked to raise error if called
      mock_api = ->(q) { raise "API should not be called!" }
      stub_weather_service(:fetch_cities_from_api, mock_api) do
        results = WeatherService.search_cities("chicago")
        assert_equal "Chicago, IL, Cached in DB", results.first["name"] || results.first[:name]
      end

      # Also verify it wrote it to Rails.cache
      assert Rails.cache.read("city_search_chicago").present?
    ensure
      Rails.cache = original_cache
    end
  end

  test "search_cities writes to database and Rails cache on API success" do
    memory_store = ActiveSupport::Cache.lookup_store(:memory_store)
    original_cache = Rails.cache
    begin
      Rails.cache = memory_store
      GeocodeCache.delete_all

      mock_results = [ { name: "Miami, FL, USA" } ]
      stub_weather_service(:fetch_cities_from_api, mock_results) do
        results = WeatherService.search_cities("miami")
        assert_equal "Miami, FL, USA", results.first[:name]
      end

      # Verify DB entry
      db_cache = GeocodeCache.find_by(query_type: "search", query_key: "miami")
      assert_not_nil db_cache
      assert_equal "Miami, FL, USA", db_cache.response_data.first["name"]

      # Verify Rails.cache
      assert Rails.cache.read("city_search_miami").present?
    ensure
      Rails.cache = original_cache
    end
  end

  test "reverse_geocode reads from database cache on Rails cache miss" do
    memory_store = ActiveSupport::Cache.lookup_store(:memory_store)
    original_cache = Rails.cache
    begin
      Rails.cache = memory_store
      GeocodeCache.delete_all

      coord_key = "48.8566,2.3522"
      GeocodeCache.create!(
        query_type: "reverse",
        query_key: coord_key,
        response_data: "Paris, Cached in DB"
      )

      # API is mocked to raise error if called
      mock_api = ->(lat, lon) { raise "API should not be called!" }
      stub_weather_service(:fetch_city_from_coords, mock_api) do
        result = WeatherService.reverse_geocode(48.8566, 2.3522)
        assert_equal "Paris, Cached in DB", result
      end

      # Also verify it wrote to Rails cache
      assert_equal "Paris, Cached in DB", Rails.cache.read("reverse_geocode_#{coord_key}")
    ensure
      Rails.cache = original_cache
    end
  end

  test "reverse_geocode writes to database and Rails cache on API success" do
    memory_store = ActiveSupport::Cache.lookup_store(:memory_store)
    original_cache = Rails.cache
    begin
      Rails.cache = memory_store
      GeocodeCache.delete_all

      coord_key = "48.8566,2.3522"
      stub_weather_service(:fetch_city_from_coords, "Paris, France") do
        result = WeatherService.reverse_geocode(48.8566, 2.3522)
        assert_equal "Paris, France", result
      end

      # Verify DB entry
      db_cache = GeocodeCache.find_by(query_type: "reverse", query_key: coord_key)
      assert_not_nil db_cache
      assert_equal "Paris, France", db_cache.response_data

      # Verify Rails cache
      assert_equal "Paris, France", Rails.cache.read("reverse_geocode_#{coord_key}")
    ensure
      Rails.cache = original_cache
    end
  end

  test "reverse_geocode does not write fallback coordinates to database cache on API failure" do
    memory_store = ActiveSupport::Cache.lookup_store(:memory_store)
    original_cache = Rails.cache
    begin
      Rails.cache = memory_store
      GeocodeCache.delete_all

      coord_key = "48.8566,2.3522"
      stub_weather_service(:fetch_city_from_coords, "Coordinates: 48.8566, 2.3522") do
        result = WeatherService.reverse_geocode(48.8566, 2.3522)
        assert_equal "Coordinates: 48.8566, 2.3522", result
      end

      # Verify NO DB entry was created
      assert_nil GeocodeCache.find_by(query_type: "reverse", query_key: coord_key)

      # Verify it still cached the fallback in Rails cache (to avoid spamming external endpoints)
      assert_equal "Coordinates: 48.8566, 2.3522", Rails.cache.read("reverse_geocode_#{coord_key}")
    ensure
      Rails.cache = original_cache
    end
  end

  test "map_owm_id_to_wmo maps OpenWeatherMap conditions to WMO correctly" do
    assert_equal 0, WeatherService.send(:map_owm_id_to_wmo, 800)
    assert_equal 2, WeatherService.send(:map_owm_id_to_wmo, 802)
    assert_equal 3, WeatherService.send(:map_owm_id_to_wmo, 804)
    assert_equal 45, WeatherService.send(:map_owm_id_to_wmo, 741)
    assert_equal 61, WeatherService.send(:map_owm_id_to_wmo, 500)
    assert_equal 95, WeatherService.send(:map_owm_id_to_wmo, 211)
  end

  test "translate_owm_to_open_meteo correctly maps One Call 3.0 response format" do
    now = Time.current.beginning_of_hour
    owm_payload = {
      "lat" => 41.8781,
      "lon" => -87.6298,
      "timezone" => "America/Chicago",
      "current" => {
        "temp" => 20.5,
        "feels_like" => 19.8,
        "humidity" => 60,
        "wind_speed" => 5.0, # m/s -> should be converted to 18.0 km/h
        "dt" => now.to_i,
        "sunrise" => (now - 6.hours).to_i,
        "sunset" => (now + 6.hours).to_i,
        "weather" => [ { "id" => 800, "description" => "clear sky" } ]
      },
      "hourly" => [
        {
          "dt" => now.to_i,
          "temp" => 20.5,
          "pop" => 0.1,
          "weather" => [ { "id" => 800 } ]
        }
      ],
      "daily" => [
        {
          "dt" => now.to_i,
          "temp" => { "max" => 25.0, "min" => 15.0 },
          "rain" => 2.5,
          "sunrise" => (now - 6.hours).to_i,
          "sunset" => (now + 6.hours).to_i,
          "moonrise" => (now + 8.hours).to_i,
          "moonset" => (now - 4.hours).to_i,
          "moon_phase" => 0.25,
          "weather" => [ { "id" => 800 } ]
        }
      ]
    }

    result = WeatherService.send(:translate_owm_to_open_meteo, owm_payload, "metric")

    assert_equal 41.8781, result["latitude"]
    assert_equal -87.6298, result["longitude"]
    assert_equal "America/Chicago", result["timezone"]

    # Current
    assert_equal 20.5, result["current"]["temperature_2m"]
    assert_equal 19.8, result["current"]["apparent_temperature"]
    assert_equal 60, result["current"]["relative_humidity_2m"]
    assert_equal 18.0, result["current"]["wind_speed_10m"]
    assert_equal 0, result["current"]["weather_code"]
    assert_equal 1, result["current"]["is_day"]

    # Hourly
    assert_equal 1, result["hourly"]["time"].size
    assert_equal 20.5, result["hourly"]["temperature_2m"].first
    assert_equal 10, result["hourly"]["precipitation_probability"].first # 0.1 * 100
    assert_equal 0, result["hourly"]["weather_code"].first

    # Daily
    assert_equal 1, result["daily"]["time"].size
    assert_equal 25.0, result["daily"]["temperature_2m_max"].first
    assert_equal 15.0, result["daily"]["temperature_2m_min"].first
    assert_equal 2.5, result["daily"]["precipitation_sum"].first
    assert_equal 0.25, result["daily"]["moon_phase"].first
  end

  test "translate_owm_to_open_meteo correctly maps One Call 3.0 response format in imperial" do
    now = Time.current.beginning_of_hour
    owm_payload = {
      "lat" => 41.8781,
      "lon" => -87.6298,
      "timezone" => "America/Chicago",
      "current" => {
        "temp" => 68.9,
        "feels_like" => 67.2,
        "humidity" => 60,
        "wind_speed" => 11.2, # mph
        "dt" => now.to_i,
        "sunrise" => (now - 6.hours).to_i,
        "sunset" => (now + 6.hours).to_i,
        "rain" => { "1h" => 25.4 }, # 25.4 mm -> 1.0 inch
        "weather" => [ { "id" => 800, "description" => "clear sky" } ]
      },
      "hourly" => [
        {
          "dt" => now.to_i,
          "temp" => 68.9,
          "pop" => 0.1,
          "weather" => [ { "id" => 800 } ]
        }
      ],
      "daily" => [
        {
          "dt" => now.to_i,
          "temp" => { "max" => 77.0, "min" => 59.0 },
          "rain" => 25.4, # 25.4 mm -> 1.0 inch
          "sunrise" => (now - 6.hours).to_i,
          "sunset" => (now + 6.hours).to_i,
          "moonrise" => (now + 8.hours).to_i,
          "moonset" => (now - 4.hours).to_i,
          "moon_phase" => 0.25,
          "weather" => [ { "id" => 800 } ]
        }
      ]
    }

    result = WeatherService.send(:translate_owm_to_open_meteo, owm_payload, "imperial")

    assert_equal 41.8781, result["latitude"]
    assert_equal -87.6298, result["longitude"]
    assert_equal "America/Chicago", result["timezone"]

    # Current
    assert_equal 68.9, result["current"]["temperature_2m"]
    assert_equal 67.2, result["current"]["apparent_temperature"]
    assert_equal 60, result["current"]["relative_humidity_2m"]
    assert_equal 11.2, result["current"]["wind_speed_10m"] # remains 11.2 mph
    assert_equal 1.0, result["current"]["precipitation"] # 25.4 mm -> 1.0 inch
    assert_equal 0, result["current"]["weather_code"]
    assert_equal 1, result["current"]["is_day"]

    # Daily
    assert_equal 1, result["daily"]["time"].size
    assert_equal 77.0, result["daily"]["temperature_2m_max"].first
    assert_equal 59.0, result["daily"]["temperature_2m_min"].first
    assert_equal 1.0, result["daily"]["precipitation_sum"].first # 25.4 mm -> 1.0 inch
  end

  test "get_weather replaces GMT with UTC in timezone abbreviation" do
    payload = {
      "timezone" => "America/Bogota",
      "timezone_abbreviation" => "GMT-5",
      "current" => { "temperature_2m" => 20 }
    }
    
    stub_weather_service(:fetch_weather_from_api, payload) do
      result = WeatherService.get_weather(4.82, -75.7, force_refresh: true)
      assert_equal "UTC-5", result["timezone_abbreviation"]
    end
  end

  private

  def stub_weather_service(method_name, mock_val_or_proc)
    mock_implementation = mock_val_or_proc.respond_to?(:call) ? mock_val_or_proc : ->(*args) { mock_val_or_proc }

    metaclass = class << WeatherService; self; end
    metaclass.alias_method :"original_#{method_name}", method_name
    metaclass.define_method(method_name, &mock_implementation)

    yield
  ensure
    metaclass = class << WeatherService; self; end
    metaclass.alias_method method_name, :"original_#{method_name}"
    metaclass.remove_method :"original_#{method_name}"
  end
end
