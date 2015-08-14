class ChargesController < ApplicationController
  respond_to :js

  def new
  end

  def create
    begin
    # Amount in cents
      @amount = 500
      @purchase = params[:number_of_ads]

      customer = Stripe::Customer.create(
        :email => 'example@stripe.com',
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
      p "derp"
      redirect_to charges_path 
    end
    @password = SecureRandom.base64
    Charge.create(email: params[:stripeEmail], amount: @amount, charge_password: @password, stripe_customer_id: customer.id, string: @purchase)
    redirect_to new_wheel_path(c_id: @password)
  end

end
