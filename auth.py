"""
Adynex – Authentifizierung & Autorisierung
============================================
Login, Logout, Passwort-Reset, Rollen-Checks.

Rollen-Hierarchie:
  superadmin → admin → viewer
                    → branch (sieht nur eigene Niederlassung)

Mandanten-Isolation:
  Jede Datenbankabfrage filtert automatisch nach mandant_id des
  eingeloggten Users. Ein User kann NIEMALS Daten eines anderen
  Mandanten sehen – auch nicht durch URL-Manipulation.
"""

from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, Mandant
from datetime import datetime, timedelta
import secrets, os

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ── Rollen-Dekoratoren ────────────────────────────────────────────────────

def admin_required(f):
    """Nur Admins und Superadmins dürfen diese Route aufrufen."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def superadmin_required(f):
    """Nur Adynex-interne Superadmins."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superadmin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def branch_access_required(f):
    """
    Stellt sicher dass der User nur auf Daten seiner eigenen
    Niederlassung zugreifen kann. Admins dürfen alles.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        niederlassung_id = kwargs.get("niederlassung_id")
        if niederlassung_id and not current_user.can_see_niederlassung(niederlassung_id):
            abort(403)
        return f(*args, **kwargs)
    return decorated


def same_mandant_required(f):
    """
    Kritische Mandanten-Isolation: Prüft ob die angeforderte
    Ressource zum Mandanten des eingeloggten Users gehört.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # mandant_id aus URL oder kwargs
        mandant_id = kwargs.get("mandant_id") or request.view_args.get("mandant_id")
        if mandant_id and not current_user.is_superadmin:
            if int(mandant_id) != current_user.mandant_id:
                abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Login ─────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    from flask_login import current_user
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            flash("E-Mail oder Passwort falsch.", "error")
            return render_template("auth/login.html")

        if not user.is_active:
            flash("Ihr Account ist deaktiviert. Bitte wenden Sie sich an den Administrator.", "error")
            return render_template("auth/login.html")

        if not user.mandant.is_active:
            flash("Ihr Unternehmen ist nicht aktiv. Bitte kontaktieren Sie Adynex.", "error")
            return render_template("auth/login.html")

        login_user(user, remember=remember)
        user.last_login = datetime.utcnow()
        db.session.commit()

        next_page = request.args.get("next")
        return redirect(next_page or url_for("dashboard.index"))

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sie wurden erfolgreich abgemeldet.", "info")
    return redirect(url_for("auth.login"))


# ── Passwort ändern ───────────────────────────────────────────────────────

@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_pw  = request.form.get("current_password", "")
        new_pw      = request.form.get("new_password", "")
        confirm_pw  = request.form.get("confirm_password", "")

        if not current_user.check_password(current_pw):
            flash("Aktuelles Passwort ist falsch.", "error")
        elif len(new_pw) < 8:
            flash("Neues Passwort muss mindestens 8 Zeichen lang sein.", "error")
        elif new_pw != confirm_pw:
            flash("Passwörter stimmen nicht überein.", "error")
        else:
            current_user.set_password(new_pw)
            db.session.commit()
            flash("Passwort erfolgreich geändert.", "success")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/change_password.html")


# ── Passwort vergessen ────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user  = User.query.filter_by(email=email).first()

        # Immer gleiche Meldung (kein User-Enumeration-Angriff)
        success_msg = "Falls diese E-Mail-Adresse bekannt ist, erhältst du in Kürze einen Reset-Link."

        if user and user.is_active:
            token = secrets.token_urlsafe(32)
            user.reset_token         = token
            user.reset_token_expires = datetime.utcnow() + timedelta(hours=2)
            db.session.commit()

            reset_url = f"{os.getenv('APP_URL', 'https://adynex.de')}/auth/reset-password/{token}"

            # E-Mail senden (oder in Konsole loggen wenn kein SMTP)
            _send_reset_email(user, reset_url)

        flash(success_msg, "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        flash("Dieser Reset-Link ist ungültig oder abgelaufen.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        new_pw  = request.form.get("new_password", "")
        new_pw2 = request.form.get("new_password2", "")
        if len(new_pw) < 8:
            flash("Passwort muss mindestens 8 Zeichen haben.", "error")
        elif new_pw != new_pw2:
            flash("Passwörter stimmen nicht überein.", "error")
        else:
            user.set_password(new_pw)
            user.reset_token         = None
            user.reset_token_expires = None
            db.session.commit()
            flash("Passwort erfolgreich geändert. Bitte jetzt einloggen.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)


def _send_reset_email(user, reset_url):
    import smtplib
    from email.mime.text import MIMEText

    server   = os.getenv("MAIL_SERVER", "")
    username = os.getenv("MAIL_USERNAME", "")
    password = os.getenv("MAIL_PASSWORD", "")

    body = f"""Hallo {user.full_name},

du hast einen Passwort-Reset für deinen Adynex-Account angefordert.

Klicke auf den folgenden Link um dein Passwort zu ändern (gültig 2 Stunden):

{reset_url}

Falls du keinen Reset angefordert hast, kannst du diese E-Mail ignorieren.

Mit freundlichen Grüßen
Adynex
    """.strip()

    if not server or not username or not password:
        print(f"[Passwort-Reset] Link für {user.email}: {reset_url}")
        return

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = "Adynex – Passwort zurücksetzen"
        msg["From"]    = os.getenv("MAIL_FROM", username)
        msg["To"]      = user.email
        with smtplib.SMTP(server, int(os.getenv("MAIL_PORT", "587"))) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(msg["From"], user.email, msg.as_string())
    except Exception as e:
        print(f"[E-Mail Fehler] {e}")


# ── Fehlerseiten ──────────────────────────────────────────────────────────

def register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500
