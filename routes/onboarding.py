"""
Onboarding-Wizard – neue Mandanten durch die ersten Schritte führen.

Schritte:
  1. Willkommen + Firmendaten prüfen
  2. Erste Niederlassung anlegen (KST)
  3. API-Zugangsdaten (optional, übersprингbar)
  4. Erste Kampagne anlegen (optional)
  5. Fertig!
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from models import db, Niederlassung, Campaign
from routes.admin import admin_bp

onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")


def _require_onboarding_incomplete(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            return redirect(url_for("dashboard.index"))
        return f(*args, **kwargs)
    return decorated


@onboarding_bp.route("/")
@login_required
def start():
    return redirect(url_for("onboarding.step1"))


@onboarding_bp.route("/step/1", methods=["GET", "POST"])
@login_required
@_require_onboarding_incomplete
def step1():
    """Schritt 1: Willkommen & Firmendaten bestätigen."""
    mandant = current_user.mandant

    if request.method == "POST":
        mandant.name = request.form.get("name", mandant.name).strip()
        db.session.commit()
        return redirect(url_for("onboarding.step2"))

    return render_template("onboarding/step1.html", mandant=mandant, step=1, total=4)


@onboarding_bp.route("/step/2", methods=["GET", "POST"])
@login_required
@_require_onboarding_incomplete
def step2():
    """Schritt 2: Erste Niederlassung anlegen."""
    mandant = current_user.mandant

    if request.method == "POST":
        form = request.form
        if not form.get("name") or not form.get("kostenstelle"):
            flash("Name und Kostenstelle sind Pflichtfelder.", "error")
        else:
            n = Niederlassung(
                mandant_id   = current_user.mandant_id,
                name         = form["name"].strip(),
                kostenstelle = form["kostenstelle"].strip(),
                city         = form.get("city", "").strip(),
                plz          = form.get("plz", "").strip(),
                standort_url = form.get("standort_url", "").strip(),
                monthly_budget_limit = float(form["monthly_budget_limit"]) if form.get("monthly_budget_limit") else None,
            )
            db.session.add(n)
            db.session.commit()
            flash(f'Niederlassung "{n.name}" (KST-{n.kostenstelle}) angelegt.', "success")
            return redirect(url_for("onboarding.step3"))

    return render_template("onboarding/step2.html", mandant=mandant, step=2, total=4)


@onboarding_bp.route("/step/3", methods=["GET", "POST"])
@login_required
@_require_onboarding_incomplete
def step3():
    """Schritt 3: API-Zugangsdaten (übersprингbar)."""
    mandant = current_user.mandant

    if request.method == "POST":
        action = request.form.get("action", "save")

        if action == "skip":
            return redirect(url_for("onboarding.step4"))

        mandant.google_customer_id     = request.form.get("google_customer_id", "").strip() or None
        mandant.google_developer_token = request.form.get("google_developer_token", "").strip() or None
        mandant.google_client_id       = request.form.get("google_client_id", "").strip() or None
        mandant.google_client_secret   = request.form.get("google_client_secret", "").strip() or None
        mandant.google_refresh_token   = request.form.get("google_refresh_token", "").strip() or None
        db.session.commit()
        flash("API-Zugangsdaten gespeichert.", "success")
        return redirect(url_for("onboarding.step4"))

    return render_template("onboarding/step3.html", mandant=mandant, step=3, total=4)


@onboarding_bp.route("/step/4")
@login_required
@_require_onboarding_incomplete
def step4():
    """Schritt 4: Fertig! Zusammenfassung."""
    mandant = current_user.mandant
    mandant.onboarding_done = True
    db.session.commit()

    return render_template("onboarding/step4.html",
        mandant          = mandant,
        niederlassungen  = mandant.niederlassungen,
        has_google       = bool(mandant.google_customer_id),
        has_microsoft    = bool(mandant.microsoft_account_id),
        step=4, total=4,
    )
