class CreateCoupons < ActiveRecord::Migration
  def change
    create_table :coupons do |t|
      t.string :code
      t.integer :amount
      t.integer :wheel_id

      t.timestamps
    end
  end
end
