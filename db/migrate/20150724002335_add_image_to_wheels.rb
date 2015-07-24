class AddImageToWheels < ActiveRecord::Migration
  def self.up
    add_attachment :wheels, :image
  end

  def self.down
    remove_attachment :wheels, :image
  end
end
