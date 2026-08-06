require "test_helper"

class FavoriteLocationTest < ActiveSupport::TestCase
  setup do
    @user = users(:one)
  end

  test "should be valid with correct attributes" do
    fav = @user.favorite_locations.new(name: "Paris", latitude: 48.8566, longitude: 2.3522)
    assert fav.valid?
  end

  test "should require a name, latitude, and longitude" do
    fav = @user.favorite_locations.new
    assert_not fav.valid?
    assert_includes fav.errors[:name], "can't be blank"
    assert_includes fav.errors[:latitude], "can't be blank"
    assert_includes fav.errors[:longitude], "can't be blank"
  end

  test "should validate latitude range" do
    fav_low = @user.favorite_locations.new(name: "Low", latitude: -91, longitude: 0)
    assert_not fav_low.valid?

    fav_high = @user.favorite_locations.new(name: "High", latitude: 91, longitude: 0)
    assert_not fav_high.valid?
  end

  test "should validate longitude range" do
    fav_low = @user.favorite_locations.new(name: "Low", latitude: 0, longitude: -181)
    assert_not fav_low.valid?

    fav_high = @user.favorite_locations.new(name: "High", latitude: 0, longitude: 181)
    assert_not fav_high.valid?
  end

  test "should validate uniqueness scoped to user_id" do
    @user.favorite_locations.create!(name: "Chicago", latitude: 41.8781, longitude: -87.6298)

    duplicate = @user.favorite_locations.new(name: "Chicago Duplicate", latitude: 41.8781, longitude: -87.6298)
    assert_not duplicate.valid?
    assert_includes duplicate.errors[:latitude], "has already been favorited"
  end
end
