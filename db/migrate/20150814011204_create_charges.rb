class CreateCharges < ActiveRecord::Migration
  def change
    create_table :charges do |t|
      t.string :email
      t.float :amount
      t.string :charge_password
      t.string :string
      t.string :stripe_customer_id

      t.timestamps
    end
  end
end
