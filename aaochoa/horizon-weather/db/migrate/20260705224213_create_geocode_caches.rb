class CreateGeocodeCaches < ActiveRecord::Migration[8.1]
  def change
    create_table :geocode_caches do |t|
      t.string :query_type, null: false
      t.string :query_key, null: false
      t.json :response_data, null: false

      t.timestamps
    end

    add_index :geocode_caches, [ :query_type, :query_key ], unique: true
  end
end
