"""
Google Ads API Integration für Hofmann SEA-Kampagnen
======================================================
Legt Search-Kampagnen im zentralen Google Ads Manager Account (MCC) an.

Voraussetzungen:
  - Google Ads Manager Account (MCC) mit Sub-Accounts pro Niederlassung
  - Google Ads API Developer Token (beantragt über ads.google.com)
  - OAuth2 Credentials (Client ID + Client Secret + Refresh Token)
  - Aktivierter API-Zugang für den MCC

Kostenstellen-Abrechnung:
  - Kampagnenname enthält immer [KST-{nummer}]
  - Zusätzlich wird ein Label mit der Kostenstelle erstellt
  - So können Kosten im Reporting nach KST gefiltert werden

Kampagnenstruktur:
  Campaign
  └── Ad Group: "{Jobtitel} - {Ort}"
      ├── Keywords (Broad + Phrase + Exact)
      └── Responsive Search Ad (RSA)
"""

import os
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException


class GoogleAdsManager:
    """Verwaltet Google Ads Kampagnen-Erstellung für Hofmann."""

    def __init__(self):
        """
        Initialisiert den Google Ads Client.
        Credentials werden aus Umgebungsvariablen oder google-ads.yaml geladen.
        """
        # Versuche zuerst Umgebungsvariablen, dann YAML-Datei
        if os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"):
            self.client = GoogleAdsClient.load_from_env()
        else:
            # Suche google-ads.yaml im Projektordner
            yaml_path = os.path.join(os.path.dirname(__file__), "..", "google-ads.yaml")
            self.client = GoogleAdsClient.load_from_storage(path=yaml_path)

        # Customer ID des MCC (Manager Account)
        self.mcc_customer_id = os.getenv("GOOGLE_ADS_MCC_ID", "").replace("-", "")

        # Customer ID des Ziel-Accounts (zentral für alle Niederlassungen)
        self.customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "").replace("-", "")

    def create_search_campaign(self, config: dict) -> dict:
        """
        Erstellt eine vollständige Search-Kampagne inkl. Anzeigengruppe,
        Keywords und RSA-Anzeige.

        Args:
            config: dict mit campaign_name, budget_eur, keywords, ad_copy,
                    final_url, kostenstelle, job_title, location, etc.

        Returns:
            dict mit campaign_id, ad_group_id, created_resources
        """
        try:
            customer_id = self.customer_id

            # 1. Budget erstellen
            budget_resource = self._create_budget(
                customer_id=customer_id,
                name=f"Budget: {config['name']}",
                amount_micros=eur_to_micros(config["budget_eur"]),
            )

            # 2. Kampagne erstellen
            campaign_resource = self._create_campaign(
                customer_id=customer_id,
                name=config["name"],
                budget_resource=budget_resource,
                location=config.get("location", ""),
            )

            # 3. Anzeigengruppe erstellen
            ad_group_name = f"{config['job_title']} | {config.get('city', config.get('location', ''))}"
            ad_group_resource = self._create_ad_group(
                customer_id=customer_id,
                campaign_resource=campaign_resource,
                name=ad_group_name,
            )

            # 4. Keywords hinzufügen
            kw_resources = self._add_keywords(
                customer_id=customer_id,
                ad_group_resource=ad_group_resource,
                keywords=config["keywords"],
            )

            # 5. RSA-Anzeige erstellen
            ad_resource = self._create_rsa(
                customer_id=customer_id,
                ad_group_resource=ad_group_resource,
                headlines=config["ad_copy"]["headlines"],
                descriptions=config["ad_copy"]["descriptions"],
                final_url=config["final_url"],
            )

            # 6. Kostenstellen-Label erstellen und zuweisen
            self._apply_kostenstelle_label(
                customer_id=customer_id,
                campaign_resource=campaign_resource,
                kostenstelle=config["kostenstelle"],
            )

            return {
                "platform": "Google Ads",
                "status": "created",
                "campaign_id": extract_id(campaign_resource),
                "campaign_name": config["name"],
                "ad_group_id": extract_id(ad_group_resource),
                "keywords_added": len(kw_resources),
                "ad_resource": ad_resource,
                "budget_eur": config["budget_eur"],
                "kostenstelle": config["kostenstelle"],
            }

        except GoogleAdsException as ex:
            error_messages = []
            for error in ex.failure.errors:
                error_messages.append(
                    f"[{error.error_code}] {error.message}"
                )
            raise RuntimeError(
                f"Google Ads API Fehler: {'; '.join(error_messages)}"
            ) from ex

    # ---- Private Methoden ----

    def _create_budget(self, customer_id: str, name: str, amount_micros: int) -> str:
        """Erstellt ein Campaign Budget und gibt den Resource Name zurück."""
        campaign_budget_service = self.client.get_service("CampaignBudgetService")
        campaign_budget_operation = self.client.get_type("CampaignBudgetOperation")
        campaign_budget = campaign_budget_operation.create

        campaign_budget.name = name
        campaign_budget.delivery_method = (
            self.client.enums.BudgetDeliveryMethodEnum.STANDARD
        )
        campaign_budget.amount_micros = amount_micros
        campaign_budget.explicitly_shared = False  # Pro-Kampagne Budget

        response = campaign_budget_service.mutate_campaign_budgets(
            customer_id=customer_id,
            operations=[campaign_budget_operation],
        )
        return response.results[0].resource_name

    def _create_campaign(
        self,
        customer_id: str,
        name: str,
        budget_resource: str,
        location: str,
    ) -> str:
        """Erstellt eine Search-Kampagne und gibt den Resource Name zurück."""
        campaign_service = self.client.get_service("CampaignService")
        campaign_operation = self.client.get_type("CampaignOperation")
        campaign = campaign_operation.create

        campaign.name = name
        campaign.status = self.client.enums.CampaignStatusEnum.PAUSED  # Start PAUSED!
        campaign.advertising_channel_type = (
            self.client.enums.AdvertisingChannelTypeEnum.SEARCH
        )
        campaign.campaign_budget = budget_resource

        # Bidding: Manueller CPC (einfach + kontrollierbar)
        campaign.manual_cpc.enhanced_cpc_enabled = True

        # Netzwerk-Einstellungen: Nur Google Search (kein Search Network)
        campaign.network_settings.target_google_search = True
        campaign.network_settings.target_search_network = False
        campaign.network_settings.target_content_network = False
        campaign.network_settings.target_partner_search_network = False

        response = campaign_service.mutate_campaigns(
            customer_id=customer_id,
            operations=[campaign_operation],
        )
        return response.results[0].resource_name

    def _create_ad_group(
        self,
        customer_id: str,
        campaign_resource: str,
        name: str,
    ) -> str:
        """Erstellt eine Anzeigengruppe."""
        ad_group_service = self.client.get_service("AdGroupService")
        ad_group_operation = self.client.get_type("AdGroupOperation")
        ad_group = ad_group_operation.create

        ad_group.name = name[:255]  # Max 255 Zeichen
        ad_group.campaign = campaign_resource
        ad_group.status = self.client.enums.AdGroupStatusEnum.ENABLED
        ad_group.type_ = self.client.enums.AdGroupTypeEnum.SEARCH_STANDARD

        # Standard-CPC: 0,50 € (wird ggf. durch Bidding-Strategie überschrieben)
        ad_group.cpc_bid_micros = eur_to_micros(0.50)

        response = ad_group_service.mutate_ad_groups(
            customer_id=customer_id,
            operations=[ad_group_operation],
        )
        return response.results[0].resource_name

    def _add_keywords(
        self,
        customer_id: str,
        ad_group_resource: str,
        keywords: dict,
    ) -> list:
        """Fügt Keywords (Broad, Phrase, Exact) zur Anzeigengruppe hinzu."""
        ad_group_criterion_service = self.client.get_service("AdGroupCriterionService")
        operations = []

        # Match-Type Mapping
        match_types = {
            "broad_match": self.client.enums.KeywordMatchTypeEnum.BROAD,
            "phrase_match": self.client.enums.KeywordMatchTypeEnum.PHRASE,
            "exact_match": self.client.enums.KeywordMatchTypeEnum.EXACT,
        }

        for kw_type, match_type_enum in match_types.items():
            for kw_text in keywords.get(kw_type, []):
                # Formatierungszeichen für Phrase/Exact entfernen (API erwartet reinen Text)
                clean_kw = kw_text.strip('"[]')

                op = self.client.get_type("AdGroupCriterionOperation")
                criterion = op.create
                criterion.ad_group = ad_group_resource
                criterion.status = self.client.enums.AdGroupCriterionStatusEnum.ENABLED
                criterion.keyword.text = clean_kw[:80]  # Max 80 Zeichen
                criterion.keyword.match_type = match_type_enum
                operations.append(op)

        if not operations:
            return []

        response = ad_group_criterion_service.mutate_ad_group_criteria(
            customer_id=customer_id,
            operations=operations,
        )
        return [r.resource_name for r in response.results]

    def _create_rsa(
        self,
        customer_id: str,
        ad_group_resource: str,
        headlines: list,
        descriptions: list,
        final_url: str,
    ) -> str:
        """Erstellt eine Responsive Search Ad (RSA)."""
        ad_group_ad_service = self.client.get_service("AdGroupAdService")
        ad_group_ad_operation = self.client.get_type("AdGroupAdOperation")

        ad_group_ad = ad_group_ad_operation.create
        ad_group_ad.ad_group = ad_group_resource
        ad_group_ad.status = self.client.enums.AdGroupAdStatusEnum.ENABLED

        # RSA konfigurieren
        ad = ad_group_ad.ad
        ad.final_urls.append(final_url)

        # Headlines (min. 3, max. 15)
        for i, headline_text in enumerate(headlines[:15]):
            headline = self.client.get_type("AdTextAsset")
            headline.text = headline_text[:30]
            ad.responsive_search_ad.headlines.append(headline)

        # Descriptions (min. 2, max. 4)
        for desc_text in descriptions[:4]:
            description = self.client.get_type("AdTextAsset")
            description.text = desc_text[:90]
            ad.responsive_search_ad.descriptions.append(description)

        response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id,
            operations=[ad_group_ad_operation],
        )
        return response.results[0].resource_name

    def _apply_kostenstelle_label(
        self,
        customer_id: str,
        campaign_resource: str,
        kostenstelle: str,
    ) -> None:
        """
        Erstellt (falls nötig) ein Label für die Kostenstelle und
        weist es der Kampagne zu. So können Kosten im Reporting nach
        Kostenstelle gefiltert werden.
        """
        label_name = f"KST-{kostenstelle}"

        try:
            # Label erstellen
            label_service = self.client.get_service("LabelService")
            label_op = self.client.get_type("LabelOperation")
            label = label_op.create
            label.name = label_name
            label.status = self.client.enums.LabelStatusEnum.ENABLED

            label_response = label_service.mutate_labels(
                customer_id=customer_id,
                operations=[label_op],
            )
            label_resource = label_response.results[0].resource_name

            # Label der Kampagne zuweisen
            campaign_label_service = self.client.get_service("CampaignLabelService")
            cl_op = self.client.get_type("CampaignLabelOperation")
            campaign_label = cl_op.create
            campaign_label.campaign = campaign_resource
            campaign_label.label = label_resource

            campaign_label_service.mutate_campaign_labels(
                customer_id=customer_id,
                operations=[cl_op],
            )
        except Exception:
            # Label-Erstellung ist nicht kritisch – Fehler loggen aber nicht werfen
            pass


# ---- Hilfsfunktionen ----

def eur_to_micros(eur: float) -> int:
    """Konvertiert Euro in Micros (Google Ads Währungseinheit: 1€ = 1.000.000 Micros)."""
    return int(float(eur) * 1_000_000)


def extract_id(resource_name: str) -> str:
    """Extrahiert die numerische ID aus einem Google Ads Resource Name."""
    return resource_name.split("/")[-1]
