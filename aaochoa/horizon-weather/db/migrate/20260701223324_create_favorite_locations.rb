class CreateFavoriteLocations < ActiveRecord::Migration[8.1]
  def change
    create_table :favorite_locations do |t|
      t.references :user, null: false, foreign_key: true
      t.string :name
      t.decimal :latitude, precision: 10, scale: 6
      t.decimal :longitude, precision: 10, scale: 6

      t.timestamps
    end
  end
end
