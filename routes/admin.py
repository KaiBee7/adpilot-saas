"""Admin-Routes – Mandanten, Niederlassungen, User verwalten."""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from auth import admin_required, superadmin_required
from models import db, Mandant, User, Niederlassung, Campaign

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@login_required
@admin_required
def index():
    """Admin-Übersicht: Niederlassungen, User, ausstehende Freigaben."""
    mandant    = current_user.mandant
    pending    = Campaign.query.filter_by(
        mandant_id=mandant.id,
        status=Campaign.STATUS_PENDING_APPROVAL
    ).order_by(Campaign.created_at.desc()).all()

    return render_template("admin/index.html",
        niederlassungen = mandant.niederlassungen,
        users           = mandant.users,
        pending_campaigns = pending,
    )


@admin_bp.route("/niederlassungen/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_niederlassung():
    if request.method == "POST":
        form = request.form
        n = Niederlassung(
            mandant_id   = current_user.mandant_id,
            name         = form["name"].strip(),
            kostenstelle = form["kostenstelle"].strip(),
            city         = form.get("city", "").strip(),
            plz          = form.get("plz", "").strip(),
            group_id     = form.get("group_id", "").strip(),
            standort_url = form.get("standort_url", "").strip(),
            monthly_budget_limit = float(form["monthly_budget_limit"]) if form.get("monthly_budget_limit") else None,
        )
        db.session.add(n)
        db.session.commit()
        flash(f'Niederlassung "{n.name}" (KST-{n.kostenstelle}) angelegt.', "success")
        return redirect(url_for("admin.index"))
    return render_template("admin/new_niederlassung.html")


@admin_bp.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_user():
    mandant = current_user.mandant
    if request.method == "POST":
        form = request.form
        if User.query.filter_by(email=form["email"].strip().lower()).first():
            flash("Diese E-Mail-Adresse existiert bereits.", "error")
        else:
            u = User(
                mandant_id       = current_user.mandant_id,
                niederlassung_id = int(form["niederlassung_id"]) if form.get("niederlassung_id") else None,
                email            = form["email"].strip().lower(),
                first_name       = form.get("first_name", "").strip(),
                last_name        = form.get("last_name", "").strip(),
                role             = form.get("role", "branch"),
            )
            u.set_password(form["password"])
            db.session.add(u)
            db.session.commit()
            flash(f'Benutzer "{u.email}" wurde angelegt.', "success")
            return redirect(url_for("admin.index"))
    return render_template("admin/new_user.html",
        niederlassungen = mandant.niederlassungen,
        roles = [("admin","Admin (alle Niederlassungen)"), ("branch","Niederlassung"), ("viewer","Nur Lesen")],
    )
