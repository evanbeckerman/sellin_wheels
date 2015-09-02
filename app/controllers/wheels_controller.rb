class WheelsController < ApplicationController

  def new
    @wheel = Wheel.new
    @charged = false
    @selected = nil
    if params[:amount].present?
      if params[:amount] == "3"
        @selected = "3 for $5"
      elsif params[:amount] == "5"
        @selected = "5 for $10"
      elsif params[:amount] == "unlimited"
        @selected = "Unlimited for $30"
      end
    end
    if params[:c_id].present?
      if Charge.where(charge_password: params[:c_id]).present?
        @charged = true
        @charge = Charge.find_by_c_id(params[:c_id])
      end
    end
  end

  def create
    @wheel = Wheel.new(wheel_params)
    if params[:charge_id].present?
      @wheel.charge_id = params[:charge_id].to_i
    end
    if params[:user_id].present?
      @wheel.user_id = params[:user_id].to_i
    end
    if @wheel.save
      NotificationMailer.notification(@wheel).deliver if Rails.env == "production"
      redirect_to wheel_path(@wheel), notice: "Thank you for your submission!"
    else
      render action: 'new'
    end
  end

  def show
    @wheel = Wheel.find(params[:id])
  end

  def index
    @q = Wheel.ransack(params[:q])
    @wheels = @q.result(distinct: true)
    @admin = false
    if current_user.present?
      if current_user.roles.present?
        @admin = true
      end
    end
  end

  def destroy
    @wheel = Wheel.find(params[:id])
    @wheel.destroy
    redirect_to wheels_path, notice: "you deleted a wheel"
  end

  def edit
    @wheel = Wheel.find(params[:id])
  end

  def update
    @wheel = Wheel.find(params[:id])
    @wheel.update_attributes(wheel_params)
    redirect_to wheel_path(@wheel), notice: "nice update bro"
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