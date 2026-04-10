"""Kampagnen-Routes – Erstellen, Freigeben, Anzeigen."""

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import db, Campaign, CampaignCluster, Niederlassung, NotificationLog
from auth import admin_required
from modules.email_parser import parse_email
from modules.job_scraper import scrape_job
from modules.ad_generator import generate_keywords, generate_ad_copy
from modules.google_ads import GoogleAdsManager
from modules.microsoft_ads import MicrosoftAdsManager
from datetime import datetime
import os

campaigns_bp = Blueprint("campaigns", __name__, url_prefix="/campaigns")

# Cluster-Definitionen (Label, Icon, Keywords-Preview)
CLUSTERS = CampaignCluster.TYPES


@campaigns_bp.route("/")
@login_required
def list_campaigns():
    mandant = current_user.mandant
    if current_user.is_admin:
        campaigns = Campaign.query.filter_by(mandant_id=mandant.id)\
                        .order_by(Campaign.created_at.desc()).all()
    else:
        campaigns = Campaign.query.filter_by(
            niederlassung_id=current_user.niederlassung_id
        ).order_by(Campaign.created_at.desc()).all()

    return render_template("campaigns/list.html", campaigns=campaigns)


@campaigns_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_campaign():
    """Formular zum Erstellen einer neuen Kampagne."""
    mandant = current_user.mandant

    # Welche Niederlassungen kann dieser User wählen?
    if current_user.is_admin:
        niederlassungen = mandant.niederlassungen
    else:
        niederlassungen = [current_user.niederlassung] if current_user.niederlassung else []

    if request.method == "POST":
        return _handle_new_campaign(niederlassungen)

    return render_template("campaigns/new.html",
        niederlassungen = niederlassungen,
        clusters        = CLUSTERS,
        campaign_types  = [
            (Campaign.TYPE_SINGLE_JOB, "Einzelstellen-Kampagne", "Für eine konkrete offene Stelle"),
            (Campaign.TYPE_STANDORT,   "Standort-Dauerkampagne", "Dauerhafte Kampagne für die Standortseite"),
        ]
    )


def _handle_new_campaign(niederlassungen):
    """Verarbeitet das Kampagnen-Formular und erstellt Kampagne in Ads-Plattformen."""
    form = request.form

    niederlassung_id = int(form.get("niederlassung_id", 0))
    niederlassung = Niederlassung.query.get_or_404(niederlassung_id)

    # Sicherheitsprüfung: User darf diese Niederlassung?
    if not current_user.can_see_niederlassung(niederlassung_id):
        flash("Kein Zugriff auf diese Niederlassung.", "error")
        return redirect(url_for("campaigns.new_campaign"))

    campaign_type = form.get("campaign_type", Campaign.TYPE_SINGLE_JOB)
    platform      = form.get("platform", Campaign.PLATFORM_BOTH)
    budget_google    = float(form.get("budget_google", 0) or 0)
    budget_microsoft = float(form.get("budget_microsoft", 0) or 0)
    conversion_limit = form.get("conversion_limit")
    conversion_limit = int(conversion_limit) if conversion_limit else None

    # ── Job-Daten ermitteln ────────────────────────────────────────────
    if campaign_type == Campaign.TYPE_SINGLE_JOB:
        job_url   = form.get("job_url", "").strip()
        job_title = form.get("job_title", "").strip()
        job_id    = form.get("job_id", "").strip()

        if not job_url:
            flash("Bitte eine Stellenanzeigen-URL eingeben.", "error")
            return redirect(url_for("campaigns.new_campaign"))

        # Stellenanzeige scrapen
        try:
            job_data = scrape_job(job_url)
            if not job_title:
                job_title = job_data.get("job_title", "")
        except Exception:
            job_data = {}

        job_data.update({
            "job_title":    job_title,
            "job_url":      job_url,
            "job_id":       job_id,
            "location":     niederlassung.city,
            "city":         niederlassung.city,
            "kostenstelle": niederlassung.kostenstelle,
        })

    else:
        # Standort-Kampagne
        job_url   = niederlassung.standort_url or ""
        job_title = f"Standort {niederlassung.city}"
        job_id    = ""
        job_data  = {
            "job_title":    job_title,
            "job_url":      job_url,
            "location":     niederlassung.city,
            "city":         niederlassung.city,
            "kostenstelle": niederlassung.kostenstelle,
        }

    # ── Kampagnenname generieren ───────────────────────────────────────
    city = niederlassung.city or ""
    campaign_name = f"[KST-{niederlassung.kostenstelle}] {job_title} | {city}"
    if job_id:
        campaign_name += f" | ID-{job_id}"
    if campaign_type == Campaign.TYPE_STANDORT:
        campaign_name += " | Dauerlaeufer"

    # ── Kampagne in DB speichern ───────────────────────────────────────
    campaign = Campaign(
        niederlassung_id = niederlassung_id,
        mandant_id       = current_user.mandant_id,
        created_by       = current_user.id,
        name             = campaign_name,
        campaign_type    = campaign_type,
        platform         = platform,
        status           = Campaign.STATUS_PENDING_APPROVAL,
        job_title        = job_title,
        job_url          = job_url,
        job_id           = job_id,
        location         = niederlassung.city,
        kostenstelle     = niederlassung.kostenstelle,
        budget_google    = budget_google if platform != Campaign.PLATFORM_MICROSOFT else 0,
        budget_microsoft = budget_microsoft if platform != Campaign.PLATFORM_GOOGLE else 0,
        is_monthly       = (campaign_type == Campaign.TYPE_STANDORT),
        conversion_limit = conversion_limit,
    )
    db.session.add(campaign)
    db.session.flush()

    # ── Cluster für Standort-Kampagnen ─────────────────────────────────
    if campaign_type == Campaign.TYPE_STANDORT:
        cluster_dict = dict(CLUSTERS)
        for cluster_type, cluster_label in CLUSTERS:
            if form.get(f"cluster_{cluster_type}"):
                budget = float(form.get(f"cluster_budget_{cluster_type}", 0) or 0)
                cluster_limit = form.get(f"cluster_limit_{cluster_type}")
                cluster = CampaignCluster(
                    campaign_id      = campaign.id,
                    cluster_type     = cluster_type,
                    cluster_label    = cluster_label,
                    budget_monthly   = budget,
                    is_active        = True,
                    conversion_limit = int(cluster_limit) if cluster_limit else None,
                )
                db.session.add(cluster)

    db.session.commit()

    # ── Benachrichtigung an Admin ──────────────────────────────────────
    _notify_admin_new_campaign(campaign)

    flash(f'Kampagne "{campaign_name}" wurde erstellt und wartet auf Freigabe.', "success")
    return redirect(url_for("campaigns.detail", campaign_id=campaign.id))


@campaigns_bp.route("/<int:campaign_id>")
@login_required
def detail(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    if not current_user.can_see_niederlassung(campaign.niederlassung_id):
        from flask import abort
        abort(403)
    return render_template("campaigns/detail.html", campaign=campaign)


@campaigns_bp.route("/<int:campaign_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve(campaign_id):
    """Admin gibt Kampagne frei → wird in Google/Microsoft Ads aktiviert."""
    campaign = Campaign.query.get_or_404(campaign_id)

    if campaign.status != Campaign.STATUS_PENDING_APPROVAL:
        flash("Diese Kampagne wartet nicht auf Freigabe.", "warning")
        return redirect(url_for("campaigns.detail", campaign_id=campaign_id))

    errors = []
    mandant = current_user.mandant

    # Keywords & Ad Copy generieren
    job_data = {
        "job_title": campaign.job_title,
        "job_url":   campaign.job_url,
        "location":  campaign.location,
        "city":      campaign.niederlassung.city,
        "kostenstelle": campaign.kostenstelle,
    }
    keywords = generate_keywords(job_data)
    ad_copy  = generate_ad_copy(job_data)

    config = {
        "name":           campaign.name,
        "budget_eur":     campaign.budget_google or campaign.budget_microsoft,
        "keywords":       keywords,
        "ad_copy":        ad_copy,
        "final_url":      campaign.job_url,
        "kostenstelle":   campaign.kostenstelle,
        "group_id":       campaign.niederlassung.group_id or "",
        "job_id":         campaign.job_id or "",
        "location":       campaign.location,
        "job_title":      campaign.job_title,
        "city":           campaign.niederlassung.city,
    }

    # Google Ads
    if campaign.platform in (Campaign.PLATFORM_GOOGLE, Campaign.PLATFORM_BOTH):
        if mandant.google_customer_id:
            try:
                config["budget_eur"] = campaign.budget_google
                g = GoogleAdsManager()
                result = g.create_search_campaign(config)
                campaign.google_campaign_id = result.get("campaign_id")
            except Exception as e:
                errors.append(f"Google Ads: {e}")
        else:
            errors.append("Google Ads: Kein Account konfiguriert.")

    # Microsoft Ads
    if campaign.platform in (Campaign.PLATFORM_MICROSOFT, Campaign.PLATFORM_BOTH):
        if mandant.microsoft_account_id:
            try:
                config["budget_eur"] = campaign.budget_microsoft
                ms = MicrosoftAdsManager()
                result = ms.create_search_campaign(config)
                campaign.microsoft_campaign_id = result.get("campaign_id")
            except Exception as e:
                errors.append(f"Microsoft Ads: {e}")
        else:
            errors.append("Microsoft Ads: Kein Account konfiguriert.")

    campaign.status      = Campaign.STATUS_ACTIVE
    campaign.approved_at = datetime.utcnow()
    campaign.approved_by = current_user.id
    db.session.commit()

    if errors:
        flash(f"Kampagne freigegeben – mit Hinweisen: {'; '.join(errors)}", "warning")
    else:
        flash(f'Kampagne "{campaign.name}" wurde freigegeben und ist jetzt live.', "success")

    return redirect(url_for("campaigns.detail", campaign_id=campaign_id))


@campaigns_bp.route("/<int:campaign_id>/pause", methods=["POST"])
@login_required
@admin_required
def pause(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    campaign.status       = Campaign.STATUS_PAUSED
    campaign.paused_at    = datetime.utcnow()
    campaign.pause_reason = "manual"
    db.session.commit()
    flash(f'Kampagne "{campaign.name}" wurde pausiert.', "info")
    return redirect(url_for("campaigns.detail", campaign_id=campaign_id))


@campaigns_bp.route("/<int:campaign_id>/resume", methods=["POST"])
@login_required
@admin_required
def resume(campaign_id):
    """Pausierte Kampagne wieder aktivieren."""
    campaign = Campaign.query.get_or_404(campaign_id)
    if campaign.status != Campaign.STATUS_PAUSED:
        flash("Nur pausierte Kampagnen können fortgesetzt werden.", "warning")
        return redirect(url_for("campaigns.detail", campaign_id=campaign_id))
    campaign.status       = Campaign.STATUS_ACTIVE
    campaign.pause_reason = None
    db.session.commit()
    flash(f'Kampagne "{campaign.name}" läuft wieder.', "success")
    return redirect(url_for("campaigns.detail", campaign_id=campaign_id))


@campaigns_bp.route("/<int:campaign_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject(campaign_id):
    """Admin lehnt Kampagne ab."""
    campaign = Campaign.query.get_or_404(campaign_id)
    reason   = request.form.get("reason", "Kein Grund angegeben")
    campaign.status       = Campaign.STATUS_REJECTED
    campaign.pause_reason = reason
    db.session.commit()
    flash(f'Kampagne "{campaign.name}" wurde abgelehnt.', "warning")
    return redirect(url_for("campaigns.detail", campaign_id=campaign_id))


@campaigns_bp.route("/<int:campaign_id>/complete", methods=["POST"])
@login_required
@admin_required
def complete(campaign_id):
    """Kampagne manuell als abgeschlossen markieren."""
    campaign = Campaign.query.get_or_404(campaign_id)
    campaign.status = Campaign.STATUS_COMPLETED
    db.session.commit()
    flash(f'Kampagne "{campaign.name}" wurde als abgeschlossen markiert.', "info")
    return redirect(url_for("campaigns.detail", campaign_id=campaign_id))


# ── Hilfsfunktionen ───────────────────────────────────────────────────────

def _notify_admin_new_campaign(campaign: Campaign):
    """Sendet E-Mail-Benachrichtigung an alle Admins des Mandanten."""
    from models import User
    admins = User.query.filter_by(
        mandant_id=campaign.mandant_id,
        role="admin",
        is_active=True,
        notify_campaign_start=True,
    ).all()

    for admin in admins:
        try:
            _send_email(
                to=admin.email,
                subject=f"[Adynex] Neue Kampagne wartet auf Freigabe: {campaign.name}",
                body=f"""
Hallo {admin.full_name},

eine neue Kampagne wurde erstellt und wartet auf Ihre Freigabe:

Kampagne:     {campaign.name}
Plattform:    {campaign.platform}
Budget:       {campaign.total_budget:.0f} €
Erstellt von: {campaign.creator.full_name if campaign.creator else 'Unbekannt'}

Zur Freigabe: {os.getenv('APP_URL', 'https://adynex.de')}/campaigns/{campaign.id}

Mit freundlichen Grüßen
Adynex
                """.strip()
            )
            log = NotificationLog(
                mandant_id=campaign.mandant_id,
                campaign_id=campaign.id,
                notif_type="campaign_started",
                subject=f"Neue Kampagne: {campaign.name}",
                sent_to=admin.email,
                success=True,
            )
            from models import db
            db.session.add(log)
        except Exception as e:
            print(f"E-Mail-Fehler: {e}")


def _send_email(to: str, subject: str, body: str):
    """
    Sendet eine E-Mail.
    Konfiguration über Umgebungsvariablen:
      MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM
    """
    import smtplib
    from email.mime.text import MIMEText

    server   = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    port     = int(os.getenv("MAIL_PORT", "587"))
    username = os.getenv("MAIL_USERNAME", "")
    password = os.getenv("MAIL_PASSWORD", "")
    sender   = os.getenv("MAIL_FROM", username)

    if not username or not password:
        print(f"[E-Mail simuliert] An: {to} | Betreff: {subject}")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = to

    with smtplib.SMTP(server, port) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.sendmail(sender, to, msg.as_string())
