require "test_helper"

class FavoriteLocationsControllerTest < ActionDispatch::IntegrationTest
  setup do
    @user = users(:one)
    sign_in_as(@user)
  end

  test "should create favorite location via HTML redirect" do
    assert_difference("FavoriteLocation.count", 1) do
      post favorite_locations_path, params: {
        favorite_location: { name: "Seattle", latitude: 47.6062, longitude: -122.3321 }
      }
    end
    assert_redirected_to root_path(lat: 47.6062, lon: -122.3321, name: "Seattle")
  end

  test "should create favorite location via Turbo Stream" do
    assert_difference("FavoriteLocation.count", 1) do
      post favorite_locations_path, as: :turbo_stream, params: {
        favorite_location: { name: "Seattle", latitude: 47.6062, longitude: -122.3321 }
      }
    end
    assert_response :success
    assert_match /turbo-stream/i, response.media_type
    assert_match /favorite_header_button/i, response.body
    assert_match /favorites/i, response.body
  end

  test "should destroy favorite location via HTML redirect" do
    favorite = @user.favorite_locations.create!(name: "Boston", latitude: 42.3601, longitude: -71.0589)

    assert_difference("FavoriteLocation.count", -1) do
      delete favorite_location_path(favorite, lat: 42.3601, lon: -71.0589, name: "Boston")
    end
    assert_redirected_to root_path(lat: 42.3601, lon: -71.0589, name: "Boston")
  end

  test "should destroy favorite location via Turbo Stream" do
    favorite = @user.favorite_locations.create!(name: "Boston", latitude: 42.3601, longitude: -71.0589)

    assert_difference("FavoriteLocation.count", -1) do
      delete favorite_location_path(favorite, lat: 42.3601, lon: -71.0589, name: "Boston"), as: :turbo_stream
    end
    assert_response :success
    assert_match /turbo-stream/i, response.media_type
    assert_match /favorite_header_button/i, response.body
    assert_match /favorites/i, response.body
  end

  test "should set flash alert on validation failure" do
    @user.favorite_locations.create!(name: "Boston", latitude: 42.3601, longitude: -71.0589)

    assert_no_difference("FavoriteLocation.count") do
      post favorite_locations_path, params: {
        favorite_location: { name: "Boston Duplicate", latitude: 42.3601, longitude: -71.0589 }
      }
    end
    assert_redirected_to root_path(lat: 42.3601, lon: -71.0589, name: "Boston Duplicate")
    assert_equal "Latitude has already been favorited", flash[:alert]
  end

  test "guest user should be redirected to login on create" do
    # Disconnect the signed in user
    delete session_path

    assert_no_difference("FavoriteLocation.count") do
      post favorite_locations_path, params: {
        favorite_location: { name: "Seattle", latitude: 47.6062, longitude: -122.3321 }
      }
    end
    assert_redirected_to new_session_path
  end

  test "guest user should be redirected to login on destroy" do
    favorite = @user.favorite_locations.create!(name: "Boston", latitude: 42.3601, longitude: -71.0589)
    # Disconnect the signed in user
    delete session_path

    assert_no_difference("FavoriteLocation.count") do
      delete favorite_location_path(favorite, lat: 42.3601, lon: -71.0589, name: "Boston")
    end
    assert_redirected_to new_session_path
  end
end
