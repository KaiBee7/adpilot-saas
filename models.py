"""
Adynex – Datenbank-Modelle
============================
Multi-Tenant SaaS Struktur:

  Mandant (z.B. "Hofmann Personal")
    └── User (Admin, Niederlassung, Viewer)
         └── Niederlassung (z.B. "Leipzig", KST 42)
              └── Campaign (Einzelstelle oder Standort-Dauerläufer)
                   └── CampaignCluster (Anzeigengruppen bei Standort-Kampagne)

  Mandant
    └── MediaAsset (Logo, Fotos, Videos – zentrale Mediathek)

Kostenstellen-Logik:
  - Jede Niederlassung hat genau eine KST
  - Alle Kampagnen erben die KST der Niederlassung
  - KST erscheint im Kampagnennamen: [KST-42] Titel | Ort
  - Im Reporting kann nach KST gefiltert werden
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ════════════════════════════════════════════════════════════════════════════
# MANDANT (Tenant)
# ════════════════════════════════════════════════════════════════════════════
class Mandant(db.Model):
    """
    Ein Mandant = ein Unternehmen das Adynex nutzt.
    Beispiel: Hofmann Personal GmbH & Co. KG
    """
    __tablename__ = "mandanten"

    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(200), nullable=False)
    slug            = db.Column(db.String(100), unique=True, nullable=False)  # URL-freundlicher Name
    plan            = db.Column(db.String(50), default="starter")             # starter/professional/business/enterprise

    # Branding
    logo_url        = db.Column(db.String(500))
    primary_color   = db.Column(db.String(7), default="#003087")              # Hex
    secondary_color = db.Column(db.String(7), default="#E8EEF7")

    # Google Ads Zugangsdaten (verschlüsselt gespeichert)
    google_mcc_id            = db.Column(db.String(50))
    google_customer_id       = db.Column(db.String(50))
    google_developer_token   = db.Column(db.String(200))
    google_client_id         = db.Column(db.String(200))
    google_client_secret     = db.Column(db.String(200))
    google_refresh_token     = db.Column(db.String(500))

    # Microsoft Ads Zugangsdaten
    microsoft_customer_id    = db.Column(db.String(50))
    microsoft_account_id     = db.Column(db.String(50))
    microsoft_developer_token= db.Column(db.String(200))
    microsoft_client_id      = db.Column(db.String(200))
    microsoft_client_secret  = db.Column(db.String(200))
    microsoft_refresh_token  = db.Column(db.String(500))

    # Status
    is_active       = db.Column(db.Boolean, default=True)
    onboarding_done = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    # Beziehungen
    users           = db.relationship("User",          backref="mandant", lazy=True, cascade="all, delete-orphan")
    niederlassungen = db.relationship("Niederlassung", backref="mandant", lazy=True, cascade="all, delete-orphan")
    media_assets    = db.relationship("MediaAsset",    backref="mandant", lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Mandant {self.name}>"

    @property
    def logo(self):
        """Gibt das Logo-Asset zurück, oder None."""
        return MediaAsset.query.filter_by(
            mandant_id=self.id, asset_type="logo"
        ).first()

    @property
    def campaign_count(self):
        return sum(len(n.campaigns) for n in self.niederlassungen)


# ════════════════════════════════════════════════════════════════════════════
# USER
# ════════════════════════════════════════════════════════════════════════════
class User(db.Model, UserMixin):
    """
    Ein Nutzer innerhalb eines Mandanten.
    Rollen:
      - superadmin: Adynex-interner Admin (plattformübergreifend)
      - admin:      Mandanten-Admin (sieht alle Niederlassungen des Mandanten)
      - branch:     Niederlassung (sieht nur eigene Kampagnen, KST ist fest)
      - viewer:     Nur Lese-Zugriff auf Dashboard & Reports
    """
    __tablename__ = "users"

    ROLES = ["superadmin", "admin", "branch", "viewer"]

    id              = db.Column(db.Integer, primary_key=True)
    mandant_id      = db.Column(db.Integer, db.ForeignKey("mandanten.id"), nullable=False)
    niederlassung_id= db.Column(db.Integer, db.ForeignKey("niederlassungen.id"), nullable=True)

    email           = db.Column(db.String(200), unique=True, nullable=False)
    password_hash   = db.Column(db.String(512), nullable=False)
    first_name      = db.Column(db.String(100))
    last_name       = db.Column(db.String(100))
    role            = db.Column(db.String(20), default="branch")

    # Status
    is_active       = db.Column(db.Boolean, default=True)
    last_login      = db.Column(db.DateTime)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    # Benachrichtigungen
    notify_campaign_start   = db.Column(db.Boolean, default=True)
    notify_budget_alert     = db.Column(db.Boolean, default=True)
    notify_conversion_limit = db.Column(db.Boolean, default=True)

    # Passwort-Reset
    reset_token         = db.Column(db.String(100), unique=True, nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.email

    @property
    def is_admin(self):
        return self.role in ("admin", "superadmin")

    @property
    def is_superadmin(self):
        return self.role == "superadmin"

    def can_see_niederlassung(self, niederlassung_id: int) -> bool:
        """Prüft ob dieser User auf eine bestimmte Niederlassung zugreifen darf."""
        if self.is_admin:
            return True
        return self.niederlassung_id == niederlassung_id

    def __repr__(self):
        return f"<User {self.email} [{self.role}]>"


# ════════════════════════════════════════════════════════════════════════════
# NIEDERLASSUNG (Branch)
# ════════════════════════════════════════════════════════════════════════════
class Niederlassung(db.Model):
    """
    Eine Niederlassung/Filiale eines Mandanten.
    Jede Niederlassung hat genau eine Kostenstelle (KST).
    Die KST ist unveränderlich und wird in alle Kampagnen übernommen.
    """
    __tablename__ = "niederlassungen"

    id              = db.Column(db.Integer, primary_key=True)
    mandant_id      = db.Column(db.Integer, db.ForeignKey("mandanten.id"), nullable=False)

    name            = db.Column(db.String(200), nullable=False)       # z.B. "Leipzig"
    group_id        = db.Column(db.String(50))                        # Hofmann GruppenID
    kostenstelle    = db.Column(db.String(50), nullable=False)         # z.B. "42" – PFLICHT
    city            = db.Column(db.String(100))                        # z.B. "Leipzig"
    plz             = db.Column(db.String(10))                         # Postleitzahl
    standort_url    = db.Column(db.String(500))                        # Dauerkampagnen-URL

    # Optionales Monatsbudget-Limit für diese Niederlassung
    monthly_budget_limit = db.Column(db.Float)

    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    # Beziehungen
    users           = db.relationship("User",     backref="niederlassung", lazy=True)
    campaigns       = db.relationship("Campaign", backref="niederlassung", lazy=True, cascade="all, delete-orphan")

    @property
    def kst_label(self):
        return f"KST-{self.kostenstelle}"

    @property
    def active_campaigns(self):
        return [c for c in self.campaigns if c.status in ("active", "pending_approval")]

    @property
    def total_spend_this_month(self):
        from calendar import monthrange
        now = datetime.utcnow()
        first_day = now.replace(day=1, hour=0, minute=0, second=0)
        return db.session.query(
            db.func.sum(Campaign.total_cost)
        ).filter(
            Campaign.niederlassung_id == self.id,
            Campaign.created_at >= first_day
        ).scalar() or 0.0

    def __repr__(self):
        return f"<Niederlassung {self.name} [{self.kst_label}]>"


# ════════════════════════════════════════════════════════════════════════════
# CAMPAIGN
# ════════════════════════════════════════════════════════════════════════════
class Campaign(db.Model):
    """
    Eine Werbekampagne – entweder Einzelstelle oder Standort-Dauerkampagne.

    Status-Flow:
      draft → pending_approval → active → paused → completed

    Kostenstelle wird immer von der Niederlassung geerbt.
    Kampagnenname-Format: [KST-{kst}] {Titel} | {Ort} | ID-{job_id}
    """
    __tablename__ = "campaigns"

    # Kampagnen-Typen
    TYPE_SINGLE_JOB = "single_job"     # Einzelne Stellenanzeige
    TYPE_STANDORT   = "standort"       # Dauerkampagne auf Standortseite

    # Plattformen
    PLATFORM_GOOGLE    = "google"
    PLATFORM_MICROSOFT = "microsoft"
    PLATFORM_BOTH      = "both"

    # Status
    STATUS_DRAFT            = "draft"
    STATUS_PENDING_APPROVAL = "pending_approval"
    STATUS_ACTIVE           = "active"
    STATUS_PAUSED           = "paused"
    STATUS_COMPLETED        = "completed"
    STATUS_REJECTED         = "rejected"

    id               = db.Column(db.Integer, primary_key=True)
    niederlassung_id = db.Column(db.Integer, db.ForeignKey("niederlassungen.id"), nullable=False)
    mandant_id       = db.Column(db.Integer, db.ForeignKey("mandanten.id"), nullable=False)
    created_by       = db.Column(db.Integer, db.ForeignKey("users.id"))

    # Kampagnen-Grunddaten
    name             = db.Column(db.String(300), nullable=False)   # [KST-42] Titel | Ort
    campaign_type    = db.Column(db.String(20), default=TYPE_SINGLE_JOB)
    platform         = db.Column(db.String(20), default=PLATFORM_BOTH)
    status           = db.Column(db.String(30), default=STATUS_PENDING_APPROVAL)

    # Job-Daten (bei Einzelstellen-Kampagne)
    job_title        = db.Column(db.String(200))
    job_url          = db.Column(db.String(500))
    job_id           = db.Column(db.String(100))
    location         = db.Column(db.String(200))

    # Kostenstelle (von Niederlassung geerbt, zur Sicherheit auch hier gespeichert)
    kostenstelle     = db.Column(db.String(50), nullable=False)

    # Budget
    budget_google    = db.Column(db.Float, default=0)   # Budget für Google Ads
    budget_microsoft = db.Column(db.Float, default=0)   # Budget für Microsoft Ads
    is_monthly       = db.Column(db.Boolean, default=False)  # True = Monatsbudget (Standort)

    # Conversion-Limit (auto-pause nach X Conversions)
    conversion_limit = db.Column(db.Integer)            # None = kein Limit
    conversions      = db.Column(db.Integer, default=0)

    # API-IDs (gesetzt nach erfolgreicher Kampagnenerstellung)
    google_campaign_id    = db.Column(db.String(100))
    microsoft_campaign_id = db.Column(db.String(100))

    # Performance-Daten (täglich via API aktualisiert)
    total_cost       = db.Column(db.Float, default=0)
    total_clicks     = db.Column(db.Integer, default=0)
    total_impressions= db.Column(db.Integer, default=0)
    ctr              = db.Column(db.Float, default=0)    # Click-Through-Rate
    cpa              = db.Column(db.Float, default=0)    # Cost per Acquisition

    # Timestamps
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at      = db.Column(db.DateTime)
    approved_by      = db.Column(db.Integer, db.ForeignKey("users.id"))
    paused_at        = db.Column(db.DateTime)
    pause_reason     = db.Column(db.String(200))         # "conversion_limit" / "budget" / "manual"

    # Beziehungen
    clusters         = db.relationship("CampaignCluster", backref="campaign", lazy=True, cascade="all, delete-orphan")
    creator          = db.relationship("User", foreign_keys=[created_by])
    approver         = db.relationship("User", foreign_keys=[approved_by])

    @property
    def total_budget(self):
        return (self.budget_google or 0) + (self.budget_microsoft or 0)

    @property
    def budget_spent_pct(self):
        if not self.total_budget:
            return 0
        return min(100, round((self.total_cost / self.total_budget) * 100, 1))

    @property
    def conversion_limit_reached(self):
        if not self.conversion_limit:
            return False
        return self.conversions >= self.conversion_limit

    @property
    def needs_budget_alert(self):
        return self.budget_spent_pct >= 80 and self.status == self.STATUS_ACTIVE

    @property
    def performance_score(self):
        """
        Adynex Performance Score (0–100).
        Bewertet die Kampagne nach CTR, Conversion Rate, Budget-Effizienz
        und Aktivitätsstatus – ähnlich dem Staffery Relevanz Score.

        Bewertung:
          80–100  → Sehr gut  (grün)
          60–79   → Gut       (blau)
          40–59   → Mittel    (orange)
          0–39    → Schwach   (rot)
        """
        score = 0

        # ── 1. CTR-Punkte (0–30) ────────────────────────────────
        # Benchmark: 5% CTR = voll, 2% = halb, <0.5% = 0
        if self.total_impressions and self.total_impressions > 0:
            ctr = (self.total_clicks or 0) / self.total_impressions * 100
            if ctr >= 5.0:
                score += 30
            elif ctr >= 2.0:
                score += int(15 + (ctr - 2.0) / 3.0 * 15)
            elif ctr >= 0.5:
                score += int((ctr - 0.5) / 1.5 * 15)
            # else: 0
        elif self.status == self.STATUS_ACTIVE:
            score += 10  # Läuft noch, noch keine Daten

        # ── 2. Conversion Rate (0–35) ────────────────────────────
        # Benchmark: 5% ConvRate = voll, 2% = halb, <0.5% = 0
        if self.total_clicks and self.total_clicks > 0:
            conv_rate = (self.conversions or 0) / self.total_clicks * 100
            if conv_rate >= 5.0:
                score += 35
            elif conv_rate >= 2.0:
                score += int(17 + (conv_rate - 2.0) / 3.0 * 18)
            elif conv_rate >= 0.5:
                score += int((conv_rate - 0.5) / 1.5 * 17)
            # else: 0
        elif self.status == self.STATUS_ACTIVE:
            score += 10  # Läuft noch, noch keine Conversions

        # ── 3. Budget-Effizienz (0–20) ───────────────────────────
        # Ideal: 40–85% Auslastung = voll, <10% = 0, >95% = gut aber nicht perfekt
        pct = self.budget_spent_pct
        if 40 <= pct <= 85:
            score += 20
        elif 85 < pct <= 95:
            score += 15
        elif pct > 95:
            score += 10
        elif pct >= 20:
            score += int((pct - 20) / 20 * 10)
        # <20%: 0

        # ── 4. Status-Bonus (0–15) ────────────────────────────────
        if self.status == self.STATUS_ACTIVE:
            score += 15
        elif self.status == self.STATUS_COMPLETED:
            score += 10
        elif self.status == self.STATUS_PENDING_APPROVAL:
            score += 5
        # paused/rejected: 0

        return min(100, max(0, score))

    @property
    def performance_label(self):
        """Gibt ein Label + CSS-Klasse für den Score zurück."""
        s = self.performance_score
        if s >= 80:
            return ("Sehr gut",  "good")
        elif s >= 60:
            return ("Gut",       "")
        elif s >= 40:
            return ("Mittel",    "warn")
        else:
            return ("Schwach",   "alert")

    def __repr__(self):
        return f"<Campaign '{self.name}' [{self.status}]>"


# ════════════════════════════════════════════════════════════════════════════
# CAMPAIGN CLUSTER (Anzeigengruppen bei Standort-Kampagne)
# ════════════════════════════════════════════════════════════════════════════
class CampaignCluster(db.Model):
    """
    Ein aktivierter Cluster innerhalb einer Standort-Dauerkampagne.
    Entspricht einer Anzeigengruppe in Google/Microsoft Ads.

    Beispiel: Kampagne "Leipzig Standort" hat Cluster:
      - "kaufmaennisch" (Budget: 150 €/Monat, aktiv)
      - "facharbeiter"  (Budget: 200 €/Monat, aktiv)
      - "hilfsjobs"     (Budget: 0, inaktiv)
    """
    __tablename__ = "campaign_clusters"

    # Verfügbare Cluster-Typen
    TYPES = [
        ("hilfsjobs",      "Hilfsjobs & Ungelernte"),
        ("kaufmaennisch",  "Kaufmännisch & Verwaltung"),
        ("facharbeiter",   "Facharbeiter & Handwerk"),
        ("lager_logistik", "Lager & Logistik"),
        ("industrie",      "Industrie & Produktion"),
        ("it_technik",     "IT & Technik"),
        ("pflege",         "Pflege & Soziales"),
        ("gastronomie",    "Gastronomie & Hotel"),
    ]

    id               = db.Column(db.Integer, primary_key=True)
    campaign_id      = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)

    cluster_type     = db.Column(db.String(50), nullable=False)   # z.B. "kaufmaennisch"
    cluster_label    = db.Column(db.String(100))                  # z.B. "Kaufmännisch & Verwaltung"
    budget_monthly   = db.Column(db.Float, default=0)
    is_active        = db.Column(db.Boolean, default=True)

    # API-IDs
    google_ad_group_id    = db.Column(db.String(100))
    microsoft_ad_group_id = db.Column(db.String(100))

    # Performance
    conversions      = db.Column(db.Integer, default=0)
    cost             = db.Column(db.Float, default=0)
    clicks           = db.Column(db.Integer, default=0)
    conversion_limit = db.Column(db.Integer)   # Monatslimit pro Cluster

    def __repr__(self):
        return f"<Cluster {self.cluster_type} [{self.campaign_id}]>"


# ════════════════════════════════════════════════════════════════════════════
# MEDIA ASSET (Logo, Fotos, Videos)
# ════════════════════════════════════════════════════════════════════════════
class MediaAsset(db.Model):
    """
    Mediathek eines Mandanten.
    Assets werden mandantenweit geteilt, können aber einer
    spezifischen Niederlassung zugeordnet sein.
    """
    __tablename__ = "media_assets"

    TYPES = ["logo", "photo", "video"]

    id               = db.Column(db.Integer, primary_key=True)
    mandant_id       = db.Column(db.Integer, db.ForeignKey("mandanten.id"), nullable=False)
    niederlassung_id = db.Column(db.Integer, db.ForeignKey("niederlassungen.id"), nullable=True)

    asset_type       = db.Column(db.String(20), nullable=False)   # logo / photo / video
    filename         = db.Column(db.String(300), nullable=False)
    file_url         = db.Column(db.String(500), nullable=False)
    file_size_kb     = db.Column(db.Integer)
    width_px         = db.Column(db.Integer)
    height_px        = db.Column(db.Integer)

    # Welche Cluster passt dieses Bild? (kommagetrennt, z.B. "kaufmaennisch,facharbeiter")
    cluster_tags     = db.Column(db.String(500), default="")

    uploaded_by      = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_logo(self):
        return self.asset_type == "logo"

    @property
    def cluster_tag_list(self):
        return [t.strip() for t in self.cluster_tags.split(",") if t.strip()]

    def __repr__(self):
        return f"<MediaAsset {self.asset_type}: {self.filename}>"


# ════════════════════════════════════════════════════════════════════════════
# NOTIFICATION LOG
# ════════════════════════════════════════════════════════════════════════════
class NotificationLog(db.Model):
    """
    Protokoll aller versendeten Benachrichtigungen.
    Budget-Alerts, Kampagnen-Starts, Conversion-Limits etc.
    """
    __tablename__ = "notification_logs"

    TYPES = [
        "campaign_started",
        "campaign_approved",
        "campaign_rejected",
        "budget_alert_80",
        "budget_alert_100",
        "conversion_limit_reached",
        "campaign_paused_auto",
    ]

    id           = db.Column(db.Integer, primary_key=True)
    mandant_id   = db.Column(db.Integer, db.ForeignKey("mandanten.id"))
    campaign_id  = db.Column(db.Integer, db.ForeignKey("campaigns.id"))
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id"))

    notif_type   = db.Column(db.String(50))
    subject      = db.Column(db.String(300))
    sent_to      = db.Column(db.String(300))   # E-Mail-Adresse
    sent_at      = db.Column(db.DateTime, default=datetime.utcnow)
    success      = db.Column(db.Boolean, default=True)
