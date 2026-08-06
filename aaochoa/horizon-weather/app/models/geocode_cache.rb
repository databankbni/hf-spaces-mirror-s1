class GeocodeCache < ApplicationRecord
  validates :query_type, presence: true
  validates :query_key, presence: true, uniqueness: { scope: :query_type }
  validates :response_data, presence: true
end
