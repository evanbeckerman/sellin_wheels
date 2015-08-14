class CouponsController < ApplicationController
  respond_to :js

  def check_code
    @coupon_code = params[:coupon_code]
    if Coupon.where(code: @coupon_code).present?
      @password = SecureRandom.base64
      Charge.create(charge_password: @password, string: "coupon", amount: 00)
      redirect_to new_wheel_path(c_id: @password), notice: "Enjoy your free submission"
    else
      redirect_to new_wheel_path, alert: "Not a Valid Code"
    end
  end

end