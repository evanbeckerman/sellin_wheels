Rails.application.routes.draw do
  root 'wheels#new'
  resources :wheels

  resources :coupons do
    collection do 
      post 'check_code'
    end
  end

  resources :charges


  get '/pages/about_us' => 'pages#about_us', as: 'about_us'
  get '/pages/blog' => 'pages#blog', as: 'blog'
  get '/pages/faq' => 'pages#faq', as: 'faq'

end