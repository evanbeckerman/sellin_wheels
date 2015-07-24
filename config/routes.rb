Rails.application.routes.draw do
  root 'wheels#new'
  resources :wheels

end