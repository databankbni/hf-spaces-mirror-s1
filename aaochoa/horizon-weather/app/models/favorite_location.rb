class FavoriteLocation < ApplicationRecord
  belongs_to :user

  validates :name, presence: true
  validates :latitude, presence: true, numericality: { greater_than_or_equal_to: -90, less_than_or_equal_to: 90 }
  validates :longitude, presence: true, numericality: { greater_than_or_equal_to: -180, less_than_or_equal_to: 180 }
  validates :latitude, uniqueness: { scope: [ :user_id, :longitude ], message: "has already been favorited" }
end
