class AddChargeIdToWheel < ActiveRecord::Migration
  def change
    add_column :wheels, :charge_id, :integer
  end
end
