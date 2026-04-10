"""Dashboard-Routes – Startseite nach dem Login."""

from flask import Blueprint, render_template
from flask_login import login_required, current_user
from models import db, Campaign, Niederlassung
from sqlalchemy import func
from datetime import datetime
from modules.tasks import run_campaign_checks

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.route("/")
@login_required
def index():
    # Auto-Pause Check – läuft max. 1x pro 10 Minuten im Hintergrund
    try:
        run_campaign_checks()
    except Exception as e:
        print(f"[Tasks] Check-Fehler: {e}")

    mandant = current_user.mandant

    # Niederlassungen die dieser User sehen darf
    if current_user.is_admin:
        niederlassungen = mandant.niederlassungen
        campaigns_query = Campaign.query.filter_by(mandant_id=mandant.id)
    else:
        niederlassungen = [current_user.niederlassung] if current_user.niederlassung else []
        campaigns_query = Campaign.query.filter_by(
            niederlassung_id=current_user.niederlassung_id
        ) if current_user.niederlassung_id else Campaign.query.filter_by(id=-1)

    # KPI-Aggregation
    all_campaigns  = campaigns_query.all()
    active_count   = sum(1 for c in all_campaigns if c.status == Campaign.STATUS_ACTIVE)
    pending_count  = sum(1 for c in all_campaigns if c.status == Campaign.STATUS_PENDING_APPROVAL)
    total_spend    = sum(c.total_cost for c in all_campaigns)
    total_conv     = sum(c.conversions for c in all_campaigns)

    # Budget-Alerts
    alerts = [c for c in all_campaigns if c.needs_budget_alert]

    # Neueste Kampagnen (max. 10)
    recent_campaigns = sorted(all_campaigns, key=lambda c: c.created_at, reverse=True)[:10]

    return render_template("dashboard/index.html",
        niederlassungen   = niederlassungen,
        active_count      = active_count,
        pending_count     = pending_count,
        total_spend       = total_spend,
        total_conversions = total_conv,
        budget_alerts     = alerts,
        recent_campaigns  = recent_campaigns,
    )
