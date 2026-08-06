class AddUnitSystemToUsers < ActiveRecord::Migration[8.1]
  def change
    add_column :users, :unit_system, :string, default: "imperial", null: false
  end
end
