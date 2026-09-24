from email.message import EmailMessage

from app.core.config import get_settings
from app.models import EmailOutbox


def enqueue_email(*, recipient: str, event_type: str, subject: str, text_body: str) -> EmailOutbox:
    return EmailOutbox(
        recipient_email=recipient,
        event_type=event_type,
        subject=subject,
        text_body=text_body,
    )


def build_email(item: EmailOutbox) -> EmailMessage:
    message = EmailMessage()
    message["From"] = get_settings().smtp_from_email
    message["To"] = item.recipient_email
    message["Subject"] = item.subject
    message.set_content(item.text_body)
    return message
