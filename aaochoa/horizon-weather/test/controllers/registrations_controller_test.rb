require "test_helper"

class RegistrationsControllerTest < ActionDispatch::IntegrationTest
  test "should get sign up page" do
    get signup_path
    assert_response :success
  end

  test "should register a new user and log in" do
    assert_difference "User.count", 1 do
      post signup_path, params: {
        user: {
          email_address: "newuser@example.com",
          password: "password123",
          password_confirmation: "password123"
        }
      }
    end

    assert_redirected_to root_path
    assert cookies[:session_id]
  end

  test "should not register with invalid details" do
    assert_no_difference "User.count" do
      post signup_path, params: {
        user: {
          email_address: "bademail",
          password: "123",
          password_confirmation: "456"
        }
      }
    end

    assert_response :unprocessable_entity
    assert_nil cookies[:session_id]
  end
end
