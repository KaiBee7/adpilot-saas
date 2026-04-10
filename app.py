"""
Adynex – Hauptapplikation
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
from routes.reporting   import reporting_bp
from routes.export      import export_bp
from routes.onboarding  import onboarding_bp

load_dotenv()


def create_app():
    app = Flask(__name__)

    # ── Konfiguration ─────────────────────────────────────────────────────
    app.config["SECRET_KEY"]           = os.getenv("FLASK_SECRET_KEY", "dev-key-change-in-prod")
    # Render nutzt postgres:// aber SQLAlchemy braucht postgresql://
    database_url = os.getenv("DATABASE_URL", "sqlite:///adynex.db")
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
    app.register_blueprint(reporting_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(onboarding_bp)

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
        return render_template("landing.html")

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

    # Demo-Mandant: Musterfirma
    mandant = Mandant(
        name="Musterfirma GmbH",
        slug="demo",
        plan="professional",
        primary_color="#003087",
        onboarding_done=True,
    )
    db.session.add(mandant)
    db.session.flush()

    # Admin-User
    admin = User(
        mandant_id=mandant.id,
        email="admin@adynex.de",
        first_name="Demo",
        last_name="Admin",
        role="admin",
    )
    admin.set_password("Demo1234!")
    db.session.add(admin)

    # Demo-Niederlassungen
    niederlassungen = [
        Niederlassung(mandant_id=mandant.id, name="Berlin",   kostenstelle="10", city="Berlin",   plz="10115", standort_url="https://www.beispiel.de/standorte/berlin/",   group_id="1001"),
        Niederlassung(mandant_id=mandant.id, name="Hamburg",  kostenstelle="20", city="Hamburg",  plz="20095", standort_url="https://www.beispiel.de/standorte/hamburg/",  group_id="1002"),
        Niederlassung(mandant_id=mandant.id, name="München",  kostenstelle="30", city="München",  plz="80331", standort_url="https://www.beispiel.de/standorte/muenchen/", group_id="1003"),
    ]
    for n in niederlassungen:
        db.session.add(n)
    db.session.flush()

    # Branch-User
    branch_user = User(
        mandant_id=mandant.id,
        niederlassung_id=niederlassungen[0].id,
        email="branch@adynex.de",
        first_name="Demo",
        last_name="Niederlassung",
        role="branch",
    )
    branch_user.set_password("Demo1234!")
    db.session.add(branch_user)

    # Demo-Kampagne
    demo_campaign = Campaign(
        niederlassung_id=niederlassungen[1].id,
        mandant_id=mandant.id,
        name="[KST-20] Vertriebsmitarbeiter (m/w/d) | Hamburg | ID-100001",
        campaign_type=Campaign.TYPE_SINGLE_JOB,
        platform=Campaign.PLATFORM_BOTH,
        status=Campaign.STATUS_ACTIVE,
        job_title="Vertriebsmitarbeiter (m/w/d)",
        job_url="https://www.beispiel.de/jobs/vertrieb-hamburg",
        job_id="100001",
        location="Hamburg",
        kostenstelle="20",
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
