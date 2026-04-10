"""
Adynex – Background Tasks
==========================
Auto-Pause Logik für Kampagnen:
  - Conversion-Limit erreicht → Kampagne pausieren
  - Budget 80% verbraucht → Admin benachrichtigen
  - Budget 100% verbraucht → Kampagne pausieren

Wird aufgerufen:
  1. Beim Dashboard-Aufruf (leichtgewichtig, max. 1x pro 10 Min)
  2. Über /api/cron/check-campaigns (Render Cron Job)
"""

from datetime import datetime, timedelta
from models import db, Campaign, NotificationLog, User


# Verhindert zu häufige Checks (in-memory Timestamp)
_last_check: datetime | None = None
CHECK_INTERVAL_MINUTES = 10


def should_run_check() -> bool:
    """Gibt True zurück wenn der letzte Check mehr als 10 Minuten her ist."""
    global _last_check
    if _last_check is None:
        return True
    return datetime.utcnow() - _last_check > timedelta(minutes=CHECK_INTERVAL_MINUTES)


def run_campaign_checks(force: bool = False) -> dict:
    """
    Führt alle Kampagnen-Checks durch.

    Returns:
        dict mit Statistiken: paused_count, alerted_count, checked_count
    """
    global _last_check

    if not force and not should_run_check():
        return {"skipped": True}

    _last_check = datetime.utcnow()

    active_campaigns = Campaign.query.filter_by(
        status=Campaign.STATUS_ACTIVE
    ).all()

    paused_count  = 0
    alerted_count = 0

    for campaign in active_campaigns:
        # ── 1. Conversion-Limit Check ──────────────────────────────────
        if campaign.conversion_limit and campaign.conversions >= campaign.conversion_limit:
            _pause_campaign(
                campaign=campaign,
                reason="conversion_limit",
                message=f"Conversion-Limit von {campaign.conversion_limit} erreicht ({campaign.conversions} Conversions)."
            )
            paused_count += 1
            continue  # Nicht weiter prüfen wenn bereits pausiert

        # ── 2. Budget 100% Check ───────────────────────────────────────
        if campaign.total_budget > 0 and campaign.total_cost >= campaign.total_budget:
            _pause_campaign(
                campaign=campaign,
                reason="budget",
                message=f"Budget vollständig verbraucht ({campaign.total_cost:.0f} € von {campaign.total_budget:.0f} €)."
            )
            paused_count += 1
            continue

        # ── 3. Budget 80% Alert ────────────────────────────────────────
        if campaign.needs_budget_alert:
            already_alerted = NotificationLog.query.filter_by(
                campaign_id=campaign.id,
                notif_type="budget_alert",
            ).filter(
                NotificationLog.created_at >= datetime.utcnow() - timedelta(days=1)
            ).first()

            if not already_alerted:
                _send_budget_alert(campaign)
                alerted_count += 1

    db.session.commit()

    return {
        "checked": len(active_campaigns),
        "paused":  paused_count,
        "alerted": alerted_count,
        "timestamp": datetime.utcnow().isoformat(),
    }


def _pause_campaign(campaign: Campaign, reason: str, message: str):
    """Pausiert eine Kampagne und benachrichtigt Admins."""
    campaign.status       = Campaign.STATUS_PAUSED
    campaign.paused_at    = datetime.utcnow()
    campaign.pause_reason = reason

    print(f"[Adynex] Kampagne pausiert: {campaign.name} | Grund: {reason}")

    # Admin benachrichtigen
    admins = User.query.filter_by(
        mandant_id=campaign.mandant_id,
        role="admin",
        is_active=True,
    ).all()

    icon = "🔕" if reason == "conversion_limit" else "💰"
    subject = f"[Adynex] Kampagne automatisch pausiert: {campaign.name}"
    body = f"""
Hallo,

die folgende Kampagne wurde automatisch pausiert:

Kampagne:   {campaign.name}
Grund:      {message}
Niederlassung: {campaign.niederlassung.name} (KST-{campaign.kostenstelle})
Plattform:  {campaign.platform}

Die Kampagne kann im Adynex-Dashboard manuell wieder aktiviert werden.

Mit freundlichen Grüßen
Adynex – Automatisierte Search-Kampagnen
    """.strip()

    for admin in admins:
        _log_notification(
            mandant_id=campaign.mandant_id,
            campaign_id=campaign.id,
            notif_type=reason,
            subject=subject,
            sent_to=admin.email,
        )
        _try_send_email(to=admin.email, subject=subject, body=body)


def _send_budget_alert(campaign: Campaign):
    """Sendet Budget-Warnung bei 80% Verbrauch."""
    pct = campaign.budget_spent_pct
    subject = f"[Adynex] Budget-Warnung {pct:.0f}%: {campaign.name}"
    body = f"""
Hallo,

eine Kampagne hat {pct:.0f}% des Budgets verbraucht:

Kampagne:    {campaign.name}
Ausgaben:    {campaign.total_cost:.0f} € von {campaign.total_budget:.0f} € ({pct:.0f}%)
Niederlassung: {campaign.niederlassung.name} (KST-{campaign.kostenstelle})

Bitte prüfen Sie ob das Budget erhöht oder die Kampagne pausiert werden soll.

Mit freundlichen Grüßen
Adynex
    """.strip()

    admins = User.query.filter_by(
        mandant_id=campaign.mandant_id,
        role="admin",
        is_active=True,
        notify_budget_alert=True,
    ).all()

    for admin in admins:
        _log_notification(
            mandant_id=campaign.mandant_id,
            campaign_id=campaign.id,
            notif_type="budget_alert",
            subject=subject,
            sent_to=admin.email,
        )
        _try_send_email(to=admin.email, subject=subject, body=body)


def _log_notification(mandant_id, campaign_id, notif_type, subject, sent_to):
    log = NotificationLog(
        mandant_id=mandant_id,
        campaign_id=campaign_id,
        notif_type=notif_type,
        subject=subject,
        sent_to=sent_to,
        success=True,
    )
    db.session.add(log)


def _try_send_email(to: str, subject: str, body: str):
    """Versucht E-Mail zu senden – Fehler werden nur geloggt."""
    import os, smtplib
    from email.mime.text import MIMEText

    server   = os.getenv("MAIL_SERVER", "")
    username = os.getenv("MAIL_USERNAME", "")
    password = os.getenv("MAIL_PASSWORD", "")

    if not all([server, username, password]):
        print(f"[E-Mail simuliert] An: {to} | {subject}")
        return

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"]    = os.getenv("MAIL_FROM", username)
        msg["To"]      = to
        port = int(os.getenv("MAIL_PORT", "587"))
        with smtplib.SMTP(server, port) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(username, to, msg.as_string())
    except Exception as e:
        print(f"[E-Mail Fehler] {e}")
