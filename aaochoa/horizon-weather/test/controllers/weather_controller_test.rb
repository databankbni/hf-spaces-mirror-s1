require "test_helper"

class WeatherControllerTest < ActionDispatch::IntegrationTest
  setup do
    @user = users(:one)
    @@weather_mock = {
      "timezone" => "UTC",
      "timezone_abbreviation" => "UTC",
      "current" => {
        "temperature_2m" => 20,
        "relative_humidity_2m" => 50,
        "apparent_temperature" => 20,
        "is_day" => 1,
        "precipitation" => 0,
        "weather_code" => 0,
        "wind_speed_10m" => 10
      },
      "hourly" => {
        "time" => Array.new(12) { Time.current.to_s },
        "temperature_2m" => Array.new(12) { 20 },
        "precipitation_probability" => Array.new(12) { 0 },
        "weather_code" => Array.new(12) { 0 }
      },
      "daily" => {
        "time" => Array.new(7) { Date.current.to_s },
        "weather_code" => Array.new(7) { 0 },
        "temperature_2m_max" => Array.new(7) { 25 },
        "temperature_2m_min" => Array.new(7) { 15 }
      }
    }
    @@cities_mock = [ { "name" => "Boston, MA, USA", "latitude" => 42.3601, "longitude" => -71.0589 } ]

    class << WeatherService
      alias_method :real_get_weather, :get_weather
      alias_method :real_search_cities, :search_cities
      alias_method :real_reverse_geocode, :reverse_geocode

      def get_weather(lat, lon, unit_system: "imperial", force_refresh: false)
        @@weather_mock
      end

      def search_cities(query)
        @@cities_mock
      end

      def reverse_geocode(lat, lon)
        "Mock City, USA"
      end
    end
  end

  teardown do
    class << WeatherService
      alias_method :get_weather, :real_get_weather
      alias_method :search_cities, :real_search_cities
      alias_method :reverse_geocode, :real_reverse_geocode
      remove_method :real_get_weather
      remove_method :real_search_cities
      remove_method :real_reverse_geocode
    end
  end

  test "guest user should view the dashboard" do
    get root_path
    assert_response :success
    assert_select "h1", "Chicago, IL"
    assert_select "a", text: "Log In"
  end

  test "authenticated user should view the dashboard with favorites" do
    sign_in_as(@user)
    @user.favorite_locations.create!(name: "San Francisco", latitude: 37.7749, longitude: -122.4194)

    get root_path
    assert_response :success
    assert_select "strong", @user.email_address
    assert_select "a", text: "San Francisco"
  end

  test "search endpoint returns matching cities" do
    get search_cities_path, params: { q: "Boston" }
    assert_response :success
    assert_equal "application/json; charset=utf-8", response.content_type

    json = JSON.parse(response.body)
    assert_equal 1, json.size
    assert_equal "Boston, MA, USA", json.first["name"]
  end

  test "guest user cannot create a favorite" do
    assert_no_difference "FavoriteLocation.count" do
      post favorite_locations_path, params: {
        favorite_location: { name: "Boston", latitude: 42.3601, longitude: -71.0589 }
      }
    end
    assert_redirected_to new_session_path
  end

  test "authenticated user can create and destroy a favorite" do
    sign_in_as(@user)

    assert_difference "@user.favorite_locations.count", 1 do
      post favorite_locations_path, params: {
        favorite_location: { name: "Miami", latitude: 25.7617, longitude: -80.1918 }
      }
    end

    favorite = @user.favorite_locations.last
    assert_redirected_to root_path(lat: 25.7617, lon: -80.1918, name: "Miami")

    assert_difference "@user.favorite_locations.count", -1 do
      delete favorite_location_path(favorite), params: { lat: 25.7617, lon: -80.1918, name: "Miami" }
    end
    assert_redirected_to root_path(lat: 25.7617, lon: -80.1918, name: "Miami")
  end

  test "dashboard should reverse-geocode location name and display local time if name is not provided" do
    get root_path, params: { lat: "42.3601", lon: "-71.0589" }
    assert_response :success
    assert_select "h1", "Mock City, USA"
    assert_select "div", text: /Local Time:/
  end
end
