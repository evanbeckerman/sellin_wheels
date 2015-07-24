class NotificationMailer < ActionMailer::Base
  default from: "from@example.com"
  layout 'mailer'

  def notification(wheel)
    @wheel = wheel
    mail(to: "er0l012@gmail.com", subject: "dink")
  end
end
