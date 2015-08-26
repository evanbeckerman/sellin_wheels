class AddAdsPurchasedToWheel < ActiveRecord::Migration
  def change
    add_column :wheels, :ads_purchased, :integer
    add_column :wheels, :integer, :string
  end
end
