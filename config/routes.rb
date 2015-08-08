Rails.application.routes.draw do
  root 'wheels#new'
  resources :wheels

  get '/pages/about_us' => 'pages#about_us', as: 'about_us'
  get '/pages/blog' => 'pages#blog', as: 'blog'
  get '/pages/faq' => 'pages#faq', as: 'faq'

end