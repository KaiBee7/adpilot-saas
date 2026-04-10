"""API-Routes – JSON-Endpunkte für Frontend und externe Integrationen."""

import os
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from models import db, Campaign, Niederlassung
from modules.email_parser import parse_email
from modules.job_scraper import scrape_job
from modules.tasks import run_campaign_checks

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/parse-email", methods=["POST"])
@login_required
def parse_email_route():
    """Parst Hofmann SEA-Beauftragungsmail → JSON mit allen Feldern."""
    email_text = request.json.get("email_text", "")
    try:
        data = parse_email(email_text)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@api_bp.route("/scrape-job", methods=["POST"])
@login_required
def scrape_job_route():
    """Scrapt eine Stellenanzeigen-URL → JSON mit Job-Daten."""
    url = request.json.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "Keine URL angegeben."})
    try:
        data = scrape_job(url)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@api_bp.route("/campaigns/<int:campaign_id>/kpis")
@login_required
def campaign_kpis(campaign_id):
    """Gibt aktuelle KPIs einer Kampagne zurück."""
    campaign = Campaign.query.get_or_404(campaign_id)
    if not current_user.can_see_niederlassung(campaign.niederlassung_id):
        return jsonify({"error": "Kein Zugriff"}), 403

    return jsonify({
        "cost":        campaign.total_cost,
        "clicks":      campaign.total_clicks,
        "impressions": campaign.total_impressions,
        "conversions": campaign.conversions,
        "ctr":         campaign.ctr,
        "cpa":         campaign.cpa,
        "budget_pct":  campaign.budget_spent_pct,
        "status":      campaign.status,
    })


@api_bp.route("/cron/check-campaigns", methods=["GET", "POST"])
def cron_check_campaigns():
    """
    Cron-Endpoint: Prüft alle aktiven Kampagnen auf Conversion-Limit und Budget.
    Wird von Render Cron Job oder externem Dienst aufgerufen.
    Gesichert mit CRON_SECRET Umgebungsvariable.
    """
    secret = os.getenv("CRON_SECRET", "")
    if secret and request.headers.get("X-Cron-Secret") != secret:
        return jsonify({"error": "Unauthorized"}), 401

    result = run_campaign_checks(force=True)
    return jsonify({"success": True, "result": result})


@api_bp.route("/niederlassungen/<int:nl_id>/budget")
@login_required
def niederlassung_budget(nl_id):
    """Monats-Ausgaben einer Niederlassung."""
    if not current_user.can_see_niederlassung(nl_id):
        return jsonify({"error": "Kein Zugriff"}), 403
    nl = Niederlassung.query.get_or_404(nl_id)
    return jsonify({
        "spent":   nl.total_spend_this_month,
        "limit":   nl.monthly_budget_limit,
        "pct":     round(nl.total_spend_this_month / nl.monthly_budget_limit * 100, 1)
                   if nl.monthly_budget_limit else None,
    })
