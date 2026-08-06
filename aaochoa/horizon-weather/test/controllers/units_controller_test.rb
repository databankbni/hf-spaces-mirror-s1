require "test_helper"

class UnitsControllerTest < ActionDispatch::IntegrationTest
  setup do
    @user = User.take
  end

  test "guest user should toggle unit system via session" do
    patch unit_path, params: { unit_system: "metric" }
    assert_redirected_to root_path
    assert_equal "metric", session[:unit_system]

    patch unit_path, params: { unit_system: "imperial" }
    assert_redirected_to root_path
    assert_equal "imperial", session[:unit_system]
  end

  test "guest user does not set invalid unit system" do
    patch unit_path, params: { unit_system: "invalid_unit" }
    assert_redirected_to root_path
    assert_nil session[:unit_system]
  end

  test "authenticated user toggles unit system in database" do
    sign_in_as(@user)
    assert_equal "imperial", @user.reload.unit_system

    patch unit_path, params: { unit_system: "metric" }
    assert_redirected_to root_path
    assert_equal "metric", @user.reload.unit_system

    patch unit_path, params: { unit_system: "imperial" }
    assert_redirected_to root_path
    assert_equal "imperial", @user.reload.unit_system
  end

  test "authenticated user cannot set invalid unit system" do
    sign_in_as(@user)
    
    patch unit_path, params: { unit_system: "invalid_unit" }
    assert_redirected_to root_path
    assert_equal "imperial", @user.reload.unit_system
  end
end
