class User < ApplicationRecord
  has_secure_password
  has_many :sessions, dependent: :destroy
  has_many :favorite_locations, dependent: :destroy

  normalizes :email_address, with: ->(e) { e.strip.downcase }

  validates :email_address, presence: true, uniqueness: { case_sensitive: false }, format: { with: URI::MailTo::EMAIL_REGEXP }
  validates :password, length: { minimum: 6 }, allow_nil: true
  validates :unit_system, inclusion: { in: %w[imperial metric] }
end
