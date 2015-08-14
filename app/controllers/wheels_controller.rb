class WheelsController < ApplicationController

  def new
    @wheel = Wheel.new
    @charged = false
    if params[:c_id].present?
      if Charge.where(charge_password: params[:c_id]).present?
        @charged = true
        @charge = Charge.find_by_c_id(params[:c_id])
      end
    end
  end

  def create
    @wheel = Wheel.new(wheel_params)
    if @wheel.save
      charge = charge_em
      if charge == true
        NotificationMailer.notification(@wheel).deliver if Rails.env == "production"
        redirect_to wheel_path(@wheel), notice: "Thank you for your submission!"
      else
        render action: 'new'
      end
    else
      render action: 'new'
    end
  end

  def show
    @wheel = Wheel.find(params[:id])
  end

  def index
    @wheels = Wheel.all.sort_by(&:created_at).reverse
  end

  private

  def charge_em
    result = true
    # @amount = 500
    # customer = Stripe::Customer.create(
    #   :email => 'example@stripe.com',
    #   :card  => params[:stripeToken]
    # )
    # charge = Stripe::Charge.create(
    #   :customer    => customer.id,
    #   :amount      => @amount,
    #   :description => 'Rails Stripe customer',
    #   :currency    => 'usd'
    # )
    # rescue Stripe::CardError => e
    #   flash[:error] = e.message
    #   result = false
    # end
    # return result
  end

  def wheel_params
    params.require(:wheel).permit(:instagram_username, :make, :model, :diameter, :front_width, :rear_width, :front_offset, :rear_offset, :pcd_lug_pattern, :price, :notes, :image)
  end

end