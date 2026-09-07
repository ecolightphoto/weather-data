import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_forecast_email(forecast_text: str, subject: str):
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("EMAIL_TO", sender)

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(forecast_text, "plain"))  # or "html" if you build an HTML body

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)

if __name__ == "__main__":
    # replace with your actual forecast-generation logic
    forecast = "Today's Flagstaff forecast: sunny, high 78°F, low 45°F."
    send_forecast_email(forecast, "Flagstaff Forecast — Today")
