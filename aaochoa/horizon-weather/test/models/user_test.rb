require "test_helper"

class UserTest < ActiveSupport::TestCase
  test "downcases and strips email_address" do
    user = User.new(email_address: " DOWNCASED@EXAMPLE.COM ")
    assert_equal "downcased@example.com", user.email_address
  end

  test "requires email_address to be present" do
    user = User.new(email_address: "")
    assert_not user.valid?
    assert_includes user.errors[:email_address], "can't be blank"
  end

  test "requires email_address to be unique (case-insensitive)" do
    existing = users(:one)
    duplicate = User.new(email_address: existing.email_address.upcase, password: "password")
    assert_not duplicate.valid?
    assert_includes duplicate.errors[:email_address], "has already been taken"
  end

  test "validates email_address format" do
    invalid_emails = %w[invalid-email user@ @domain.com]
    invalid_emails.each do |email|
      user = User.new(email_address: email, password: "password")
      assert_not user.valid?, "#{email} should be invalid"
      assert_includes user.errors[:email_address], "is invalid"
    end
  end

  test "validates password minimum length" do
    user = User.new(email_address: "user@example.com", password: "123")
    assert_not user.valid?
    assert_includes user.errors[:password], "is too short (minimum is 6 characters)"
  end

  test "destroys sessions and favorite locations when user is destroyed" do
    user = users(:one)
    user.sessions.create!(user_agent: "test", ip_address: "127.0.0.1")
    user.favorite_locations.create!(name: "Paris", latitude: 48.8566, longitude: 2.3522)

    assert_difference -> { Session.count } => -1, -> { FavoriteLocation.count } => -1 do
      user.destroy
    end
  end
end
