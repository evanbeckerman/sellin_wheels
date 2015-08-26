class AddAdsPurchasedToWheel < ActiveRecord::Migration
  def change
    add_column :wheels, :ads_purchased, :integer
  end
end
