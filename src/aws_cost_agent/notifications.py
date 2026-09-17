import logging
from email.message import EmailMessage
from hashlib import sha256
from pathlib import Path

logger = logging.getLogger(__name__)


def deliver(store, config, provider):
    count = 0
    for message in store.messages(pending=True):
        try:
            if config.demo:
                message = {
                    **message,
                    "subject": "[DEMO] " + message["subject"],
                    "body": "SYNTHETIC DEMO DATA — NOT AN AWS ACCOUNT REPORT\n\n" + message["body"],
                }
            if config.delivery == "ses":
                if config.demo:
                    raise ValueError("Demo messages cannot be sent through SES")
                provider.send_email(message, config)
                store.delivered(message["id"], "sent")
            else:
                directory = Path(config.outbox_dir)
                directory.mkdir(parents=True, exist_ok=True)
                mail = EmailMessage()
                mail["Subject"] = message["subject"]
                mail["From"] = config.sender or "agent@example.invalid"
                mail["To"] = ", ".join(config.recipients) or "cto@example.invalid"
                mail.set_content(message["body"])
                filename = sha256(message["id"].encode()).hexdigest()[:24] + ".eml"
                target = directory / filename
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(bytes(mail))
                temporary.replace(target)
                store.delivered(message["id"], "previewed")
            count += 1
        except Exception as error:
            # Persist for retry, but avoid storing provider response bodies or credentials.
            store.failed(message["id"], type(error).__name__)
            logger.warning("Email delivery failed (%s); retained in outbox", type(error).__name__)
    return count
