class ChargesController < ApplicationController
  respond_to :js

  def new
  end

  def create
    begin
    # Amount in cents
      @purchase = params[:number_of_ads]
      if @purchase == "3 for $5"
        @amount = 500
      elsif @purchase == "5 $10"
        @amount = 1000
      elsif @purchase == "10 ($10)"
        @amount = 1000
      else
        @amount = 3000
      end

      customer = Stripe::Customer.create(
        :email => params[:stripeEmail],
        :card  => params[:stripeToken]
      )

      charge = Stripe::Charge.create(
        :customer    => customer.id,
        :amount      => @amount,
        :description => 'Rails Stripe customer',
        :currency    => 'usd'
      )

    rescue Stripe::CardError => e
      flash[:error] = e.message
      @error = e.message
    end
    
    if @error.present?
      redirect_to new_wheel_path, alert: "Credit Card Error, try again. #{e.message}"
    else
      @password = SecureRandom.base64
      Charge.create(email: params[:stripeEmail], amount: @amount, charge_password: @password, stripe_customer_id: customer.id, string: @purchase)
      redirect_to new_wheel_path(c_id: @password), notice: "Thank you for your purchase of #{@purchase}"
    end
  end

end
