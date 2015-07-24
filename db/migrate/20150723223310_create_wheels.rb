class CreateWheels < ActiveRecord::Migration
  def change
    create_table :wheels do |t|
      t.string :instagram_username
      t.string :make
      t.string :model
      t.string :diameter
      t.string :front_width_offset
      t.string :rear_width_offset
      t.string :pcd_lug_pattern
      t.string :price
      t.text :notes

      t.timestamps
    end
  end
end
