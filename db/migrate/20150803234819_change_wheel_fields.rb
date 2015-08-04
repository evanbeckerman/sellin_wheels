class ChangeWheelFields < ActiveRecord::Migration
  def change
    rename_column :wheels, :front_width_offset, :front_width
    rename_column :wheels, :rear_width_offset, :rear_width
    add_column :wheels, :front_offset, :string
    add_column :wheels, :rear_offset, :string
  end
end
