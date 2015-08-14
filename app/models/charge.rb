class Charge < ActiveRecord::Base


  def self.find_by_c_id(c_id)
    if Charge.where(charge_password: c_id).present?
      Charge.where(charge_password: c_id).first
    else
      nil
    end
  end

end
