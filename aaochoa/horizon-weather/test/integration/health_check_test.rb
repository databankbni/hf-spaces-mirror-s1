require "test_helper"

class HealthCheckTest < ActionDispatch::IntegrationTest
  test "should get health check endpoint" do
    get rails_health_check_path
    assert_response :success
    assert_equal "text/html", response.media_type
  end
end
