"""
Alert utilities for notifying on scraper failures and anomalous price swings,
and for delivering API keys to new subscribers after purchase.

Supports Slack webhooks and email (via SMTP) notifications.
"""

import logging

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


async def send_slack_alert(message: str) -> None:
    """
    Send an alert message to a Slack channel via webhook.

    Args:
        message: The alert text to send.
    """
    webhook_url = settings.alert_slack_webhook_url
    if not webhook_url:
        logger.warning("Slack webhook URL not configured — alert not sent: %s", message)
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                webhook_url,
                json={"text": f"🚨 *BAJUS Price API Alert*\n{message}"},
            )
            response.raise_for_status()
            logger.info("Slack alert sent successfully.")
    except httpx.HTTPError as exc:
        logger.error("Failed to send Slack alert: %s", exc)


async def send_email_alert(subject: str, body: str) -> None:
    """
    Send an alert email via SMTP.

    Args:
        subject: Email subject line.
        body: Email body text.
    """
    if not settings.smtp_host or not settings.alert_email_to:
        logger.warning("Email not configured — alert not sent: %s", subject)
        return

    try:
        from email.mime.text import MIMEText

        import aiosmtplib

        msg = MIMEText(body)
        msg["Subject"] = f"[BAJUS Price API] {subject}"
        msg["From"] = settings.smtp_user
        msg["To"] = settings.alert_email_to

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            use_tls=True,
        )
        logger.info("Email alert sent to %s.", settings.alert_email_to)
    except Exception as exc:
        logger.error("Failed to send email alert: %s", exc)


async def send_alert(subject: str, message: str) -> None:
    """
    Send an alert via all configured channels (Slack + email).

    Args:
        subject: Short alert title (used as email subject).
        message: Detailed alert body.
    """
    await send_slack_alert(f"*{subject}*\n{message}")
    await send_email_alert(subject, message)


async def send_api_key_email(to_email: str, raw_key: str, plan: str) -> None:
    """
    Send a welcome/delivery email with the new subscriber's API key.

    This is called immediately after a successful Stripe checkout.
    The raw key is included in the email body — it is NEVER stored anywhere
    after this point. The user must save it from this email.

    Args:
        to_email: The subscriber's email address.
        raw_key:  The plain-text API key (shown once).
        plan:     The subscribed plan name (e.g. 'starter').
    """
    if not settings.smtp_host or not settings.smtp_user:
        logger.warning(
            "SMTP not configured — cannot email API key to %s. Key prefix: %s...",
            to_email,
            raw_key[:16],
        )
        return

    plan_labels = {
        "free": "Free Trial",
        "starter": "Starter ($6/month or $60/year)",
        "pro": "Pro",
        "enterprise": "Enterprise",
    }
    plan_label = plan_labels.get(plan, plan.title())

    quota_map = {
        "free": "200",
        "starter": "10,000",
        "pro": "100,000",
        "enterprise": "1,000,000",
    }
    quota = quota_map.get(plan, "—")

    body = f"""Welcome to the BAJUS Gold & Silver Price API! 🪙

Your API key is ready. Save it now — for security reasons, we cannot show it again.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  YOUR API KEY:  {raw_key}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Plan:           {plan_label}
Monthly quota:  {quota} requests/month

─── QUICK START ─────────────────────────────────────

Get the latest gold price (per gram, all karats):

  curl -H "Authorization: Bearer {raw_key}" \\
       https://api.bajusprices.com/v1/prices/gold/latest

Get both gold + silver in one call:

  curl -H "Authorization: Bearer {raw_key}" \\
       https://api.bajusprices.com/v1/prices/latest

JavaScript (for your jewellery website):

  const res = await fetch(
    'https://api.bajusprices.com/v1/prices/gold/latest',
    {{ headers: {{ Authorization: 'Bearer {raw_key}' }} }}
  );
  const data = await res.json();
  // data.prices => {{ "22k": 19970, "21k": 19075, "18k": 16380, "sanaton": 13380 }}

─── ALL ENDPOINTS ───────────────────────────────────

  GET /v1/prices/gold/latest     Latest gold buy price (all karats)
  GET /v1/prices/silver/latest   Latest silver price
  GET /v1/prices/latest          Gold + silver in one response
  GET /v1/prices/convert         Convert price to vori, ounce, kg, etc.
  GET /v1/prices/history         Historical price series (Starter+)
  GET /v1/meta/usage             Your current usage vs. monthly quota

Full interactive docs: https://api.bajusprices.com/docs

─── NOTES ───────────────────────────────────────────

• Prices are sourced from BAJUS (Bangladesh Jewellers' Association)
  and refresh every 10 minutes automatically.
• The response includes a "stale": true flag if data is >60 min old.
• Source attribution: BAJUS, via bajushub.com

─── SUPPORT ─────────────────────────────────────────

Reply to this email for any help.
To rotate your key, contact us and we will issue a replacement.

— The BAJUS Price API Team
"""

    try:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        import aiosmtplib

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Your BAJUS Price API Key — Save This Now"
        msg["From"] = settings.smtp_user
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain"))

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            use_tls=True,
        )
        logger.info("API key delivery email sent to %s (plan=%s).", to_email, plan)
    except Exception as exc:
        logger.error(
            "Failed to send API key email to %s: %s. Key prefix %s... — MANUAL ACTION REQUIRED.",
            to_email,
            exc,
            raw_key[:16],
        )
        # Escalate to Slack so no key is silently lost
        await send_slack_alert(
            f"⚠️ *API Key Email Delivery Failed*\n"
            f"Customer: `{to_email}` (plan: {plan})\n"
            f"Key prefix: `{raw_key[:16]}...`\n"
            f"Error: `{exc}`\n"
            f"*Manual action required — send the key to the customer directly.*"
        )
