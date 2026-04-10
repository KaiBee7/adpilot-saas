"""
AdPilot – Hauptapplikation
===========================
Multi-Tenant SaaS für automatisierte Search-Kampagnen.
"""

import os
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_login import LoginManager, login_required, current_user
from dotenv import load_dotenv
from models import db, User, Mandant, Niederlassung, Campaign, CampaignCluster, MediaAsset
from auth import auth_bp, admin_required, branch_access_required, register_error_handlers
from routes.dashboard  import dashboard_bp
from routes.campaigns  import campaigns_bp
from routes.admin      import admin_bp
from routes.api        import api_bp

load_dotenv()


def create_app():
    app = Flask(__name__)

    # ── Konfiguration ─────────────────────────────────────────────────────
    app.config["SECRET_KEY"]           = os.getenv("FLASK_SECRET_KEY", "dev-key-change-in-prod")
    # Render nutzt postgres:// aber SQLAlchemy braucht postgresql://
    database_url = os.getenv("DATABASE_URL", "sqlite:///adpilot.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"]        = os.path.join(app.root_path, "uploads")
    app.config["MAX_CONTENT_LENGTH"]   = 50 * 1024 * 1024  # 50 MB max Upload

    # ── Datenbank ─────────────────────────────────────────────────────────
    db.init_app(app)

    # ── Login Manager ─────────────────────────────────────────────────────
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view       = "auth.login"
    login_manager.login_message    = "Bitte melden Sie sich an."
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ── Blueprints registrieren ───────────────────────────────────────────
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    # ── Fehler-Handler ────────────────────────────────────────────────────
    register_error_handlers(app)

    # ── Template-Globals ──────────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        """Macht Mandant-Daten in allen Templates verfügbar."""
        mandant = None
        if current_user.is_authenticated:
            mandant = current_user.mandant
        return dict(mandant=mandant, CampaignCluster=CampaignCluster)

    # ── Root-Redirect ─────────────────────────────────────────────────────
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    # ── DB Tabellen erstellen (nur Entwicklung) ───────────────────────────
    with app.app_context():
        db.create_all()
        _seed_demo_data()

    return app


def _seed_demo_data():
    """
    Erstellt Demo-Daten falls die DB leer ist.
    Nur für Entwicklung – in Produktion deaktivieren.
    """
    if Mandant.query.first():
        return  # Bereits Daten vorhanden

    # Demo-Mandant: Hofmann Personal
    mandant = Mandant(
        name="Hofmann Personal GmbH",
        slug="hofmann",
        plan="professional",
        primary_color="#003087",
        onboarding_done=True,
    )
    db.session.add(mandant)
    db.session.flush()

    # Admin-User
    admin = User(
        mandant_id=mandant.id,
        email="admin@hofmann.info",
        first_name="Kai",
        last_name="Admin",
        role="admin",
    )
    admin.set_password("Demo1234!")
    db.session.add(admin)

    # Demo-Niederlassungen
    niederlassungen = [
        Niederlassung(mandant_id=mandant.id, name="Leipzig",           kostenstelle="42",  city="Leipzig",           plz="04109", standort_url="https://www.hofmann.info/standorte/leipzig/",           group_id="2001"),
        Niederlassung(mandant_id=mandant.id, name="Eisenhüttenstadt",  kostenstelle="180", city="Eisenhüttenstadt",  plz="15890", standort_url="https://www.hofmann.info/standorte/eisenhuettenstadt/", group_id="2129"),
        Niederlassung(mandant_id=mandant.id, name="Hamburg",           kostenstelle="55",  city="Hamburg",           plz="20095", standort_url="https://www.hofmann.info/standorte/hamburg/",           group_id="2050"),
    ]
    for n in niederlassungen:
        db.session.add(n)
    db.session.flush()

    # Branch-User für Leipzig
    branch_user = User(
        mandant_id=mandant.id,
        niederlassung_id=niederlassungen[0].id,
        email="leipzig@hofmann.info",
        first_name="Leipzig",
        last_name="Niederlassung",
        role="branch",
    )
    branch_user.set_password("Demo1234!")
    db.session.add(branch_user)

    # Demo-Kampagne
    demo_campaign = Campaign(
        niederlassung_id=niederlassungen[1].id,
        mandant_id=mandant.id,
        name="[KST-180] Recruiter (m/w/d) | Eisenhüttenstadt | ID-898874",
        campaign_type=Campaign.TYPE_SINGLE_JOB,
        platform=Campaign.PLATFORM_BOTH,
        status=Campaign.STATUS_ACTIVE,
        job_title="Recruiter (m/w/d)",
        job_url="https://www.hofmann.info/jobs/stellenanzeige/Z18Y8HC-recruiter-mwd_15890-eisenhuettenstadt",
        job_id="898874",
        location="15890 Eisenhüttenstadt",
        kostenstelle="180",
        budget_google=125.0,
        budget_microsoft=125.0,
        conversion_limit=10,
        conversions=3,
        total_cost=67.50,
        total_clicks=142,
        total_impressions=2840,
        google_campaign_id="demo-google-001",
        microsoft_campaign_id="demo-ms-001",
    )
    db.session.add(demo_campaign)

    db.session.commit()
    print("✓ Demo-Daten erstellt (admin@hofmann.info / Demo1234!)")


if __name__ == "__main__":
    app = create_app()
    debug = os.getenv("FLASK_ENV", "production") == "development"
    app.run(debug=debug, port=5000)
