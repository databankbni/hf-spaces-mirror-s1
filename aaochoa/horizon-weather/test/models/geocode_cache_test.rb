require "test_helper"

class GeocodeCacheTest < ActiveSupport::TestCase
  test "validates presence of query_type, query_key, and response_data" do
    cache = GeocodeCache.new
    assert_not cache.valid?
    assert_includes cache.errors[:query_type], "can't be blank"
    assert_includes cache.errors[:query_key], "can't be blank"
    assert_includes cache.errors[:response_data], "can't be blank"
  end

  test "validates uniqueness of query_key scoped to query_type" do
    GeocodeCache.create!(
      query_type: "search",
      query_key: "chicago",
      response_data: { some: "data" }
    )

    duplicate = GeocodeCache.new(
      query_type: "search",
      query_key: "chicago",
      response_data: { other: "data" }
    )

    assert_not duplicate.valid?
    assert_includes duplicate.errors[:query_key], "has already been taken"

    # Different query_type is fine
    different_type = GeocodeCache.new(
      query_type: "reverse",
      query_key: "chicago",
      response_data: { other: "data" }
    )
    assert different_type.valid?
  end
end
