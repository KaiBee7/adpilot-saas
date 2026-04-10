"""Reporting-Routes – Auswertungen nach KST, Zeitraum und Plattform."""

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from models import Campaign, Niederlassung
from datetime import datetime, timedelta

reporting_bp = Blueprint("reporting", __name__, url_prefix="/reporting")


@reporting_bp.route("/")
@login_required
def index():
    mandant  = current_user.mandant
    platform = request.args.get("platform", "all")
    period   = int(request.args.get("period", 30))

    # Zeitraum bestimmen
    if period > 0:
        since = datetime.utcnow() - timedelta(days=period)
    else:
        since = None

    # Kampagnen laden
    if current_user.is_admin:
        query = Campaign.query.filter_by(mandant_id=mandant.id)
        niederlassungen = mandant.niederlassungen
    else:
        query = Campaign.query.filter_by(niederlassung_id=current_user.niederlassung_id)
        niederlassungen = [current_user.niederlassung] if current_user.niederlassung else []

    if since:
        query = query.filter(Campaign.created_at >= since)
    if platform != "all":
        query = query.filter(
            (Campaign.platform == platform) | (Campaign.platform == "both")
        )

    campaigns = query.order_by(Campaign.created_at.desc()).all()

    # Gesamt-Stats
    stats = {
        "total_campaigns":  len(campaigns),
        "active_campaigns": sum(1 for c in campaigns if c.status == "active"),
        "total_spend":      sum(c.total_cost or 0 for c in campaigns),
        "total_budget":     sum(c.total_budget or 0 for c in campaigns),
        "total_conversions":sum(c.conversions or 0 for c in campaigns),
        "total_clicks":     sum(c.total_clicks or 0 for c in campaigns),
        "total_impressions":sum(c.total_impressions or 0 for c in campaigns),
    }

    # Auswertung nach Kostenstelle
    kst_map = {}
    for c in campaigns:
        kst = c.kostenstelle
        if kst not in kst_map:
            kst_map[kst] = {
                "kostenstelle":   kst,
                "name":           c.niederlassung.name,
                "campaign_count": 0,
                "spend":          0,
                "budget":         0,
                "clicks":         0,
                "conversions":    0,
                "impressions":    0,
            }
        kst_map[kst]["campaign_count"] += 1
        kst_map[kst]["spend"]       += c.total_cost or 0
        kst_map[kst]["budget"]      += c.total_budget or 0
        kst_map[kst]["clicks"]      += c.total_clicks or 0
        kst_map[kst]["conversions"] += c.conversions or 0
        kst_map[kst]["impressions"] += c.total_impressions or 0

    kst_rows = sorted(kst_map.values(), key=lambda x: x["spend"], reverse=True)

    return render_template("reporting/index.html",
        campaigns = campaigns,
        stats     = stats,
        kst_rows  = kst_rows,
        platform  = platform,
        period    = period,
    )
