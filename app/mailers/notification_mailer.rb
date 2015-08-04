class NotificationMailer < ActionMailer::Base
  default from: "www.SellinWheels.com"
  layout 'mailer'

  def notification(wheel)
    @wheel = wheel
    mail(to: "er0l012@gmail.com", subject: "New Submission")
  end
end
