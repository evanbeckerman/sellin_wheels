class Wheel < ActiveRecord::Base
  validates :instagram_username, :image, :presence => true
  has_attached_file :image, styles: {
    thumb: '100x100>',
    square: '200x200#',
    medium: '640x640>'
  }

  # Validate the attached image is image/jpg, image/png, etc
  validates_attachment_content_type :image, :content_type => /\Aimage\/.*\Z/

end
