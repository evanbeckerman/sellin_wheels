class NotificationMailer < ActionMailer::Base
  default from: "SellinWheels"
  layout 'mailer'

  def notification(wheel)
    @wheel = wheel
    mail(to: "sellinwheels@gmail.com", subject: "New Submission")
  end
end
