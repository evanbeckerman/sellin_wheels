class WheelsController < ApplicationController

  def new
    @wheel = Wheel.new
  end

  def create
    @wheel = Wheel.new(wheel_params)
    if @wheel.save
      charge = charge_em
      if charge == true
        NotificationMailer.notification(@wheel).deliver if Rails.env == "production"
        redirect_to new_wheel_path, notice: "Thank you for your submission!"
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