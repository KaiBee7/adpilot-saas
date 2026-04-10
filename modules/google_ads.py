"""
Google Ads API Integration für Hofmann SEA-Kampagnen
======================================================
Legt Search-Kampagnen im zentralen Google Ads Manager Account (MCC) an.
"""

import os

# Bedingter Import – google-ads Paket nur wenn installiert
try:
    from google.ads.googleads.client import GoogleAdsClient
    from google.ads.googleads.errors import GoogleAdsException
    GOOGLE_ADS_AVAILABLE = True
except ImportError:
    GOOGLE_ADS_AVAILABLE = False
    GoogleAdsClient = None
    GoogleAdsException = Exception


class GoogleAdsManager:
    """Verwaltet Google Ads Kampagnen-Erstellung für Hofmann."""

    def __init__(self):
        if not GOOGLE_ADS_AVAILABLE:
            raise RuntimeError(
                "Google Ads Paket nicht installiert. "
                "Bitte 'google-ads' in requirements.txt aktivieren und API-Credentials konfigurieren."
            )

        if os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"):
            self.client = GoogleAdsClient.load_from_env()
        else:
            yaml_path = os.path.join(os.path.dirname(__file__), "..", "google-ads.yaml")
            self.client = GoogleAdsClient.load_from_storage(path=yaml_path)

        self.mcc_customer_id = os.getenv("GOOGLE_ADS_MCC_ID", "").replace("-", "")
        self.customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "").replace("-", "")

    def create_search_campaign(self, config: dict) -> dict:
        try:
            customer_id = self.customer_id

            budget_resource = self._create_budget(
                customer_id=customer_id,
                name=f"Budget: {config['name']}",
                amount_micros=eur_to_micros(config["budget_eur"]),
            )

            campaign_resource = self._create_campaign(
                customer_id=customer_id,
                name=config["name"],
                budget_resource=budget_resource,
                location=config.get("location", ""),
            )

            ad_group_name = f"{config['job_title']} | {config.get('city', config.get('location', ''))}"
            ad_group_resource = self._create_ad_group(
                customer_id=customer_id,
                campaign_resource=campaign_resource,
                name=ad_group_name,
            )

            kw_resources = self._add_keywords(
                customer_id=customer_id,
                ad_group_resource=ad_group_resource,
                keywords=config["keywords"],
            )

            ad_resource = self._create_rsa(
                customer_id=customer_id,
                ad_group_resource=ad_group_resource,
                headlines=config["ad_copy"]["headlines"],
                descriptions=config["ad_copy"]["descriptions"],
                final_url=config["final_url"],
            )

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
                "budget_eur": config["budget_eur"],
                "kostenstelle": config["kostenstelle"],
            }

        except GoogleAdsException as ex:
            error_messages = [f"[{e.error_code}] {e.message}" for e in ex.failure.errors]
            raise RuntimeError(f"Google Ads API Fehler: {'; '.join(error_messages)}") from ex

    def _create_budget(self, customer_id, name, amount_micros):
        service = self.client.get_service("CampaignBudgetService")
        op = self.client.get_type("CampaignBudgetOperation")
        budget = op.create
        budget.name = name
        budget.delivery_method = self.client.enums.BudgetDeliveryMethodEnum.STANDARD
        budget.amount_micros = amount_micros
        budget.explicitly_shared = False
        response = service.mutate_campaign_budgets(customer_id=customer_id, operations=[op])
        return response.results[0].resource_name

    def _create_campaign(self, customer_id, name, budget_resource, location):
        service = self.client.get_service("CampaignService")
        op = self.client.get_type("CampaignOperation")
        campaign = op.create
        campaign.name = name
        campaign.status = self.client.enums.CampaignStatusEnum.PAUSED
        campaign.advertising_channel_type = self.client.enums.AdvertisingChannelTypeEnum.SEARCH
        campaign.campaign_budget = budget_resource
        campaign.manual_cpc.enhanced_cpc_enabled = True
        campaign.network_settings.target_google_search = True
        campaign.network_settings.target_search_network = False
        campaign.network_settings.target_content_network = False
        response = self.client.get_service("CampaignService").mutate_campaigns(
            customer_id=customer_id, operations=[op]
        )
        return response.results[0].resource_name

    def _create_ad_group(self, customer_id, campaign_resource, name):
        service = self.client.get_service("AdGroupService")
        op = self.client.get_type("AdGroupOperation")
        ag = op.create
        ag.name = name[:255]
        ag.campaign = campaign_resource
        ag.status = self.client.enums.AdGroupStatusEnum.ENABLED
        ag.type_ = self.client.enums.AdGroupTypeEnum.SEARCH_STANDARD
        ag.cpc_bid_micros = eur_to_micros(0.50)
        response = service.mutate_ad_groups(customer_id=customer_id, operations=[op])
        return response.results[0].resource_name

    def _add_keywords(self, customer_id, ad_group_resource, keywords):
        service = self.client.get_service("AdGroupCriterionService")
        operations = []
        match_types = {
            "broad_match": self.client.enums.KeywordMatchTypeEnum.BROAD,
            "phrase_match": self.client.enums.KeywordMatchTypeEnum.PHRASE,
            "exact_match": self.client.enums.KeywordMatchTypeEnum.EXACT,
        }
        for kw_type, match_type_enum in match_types.items():
            for kw_text in keywords.get(kw_type, []):
                op = self.client.get_type("AdGroupCriterionOperation")
                criterion = op.create
                criterion.ad_group = ad_group_resource
                criterion.status = self.client.enums.AdGroupCriterionStatusEnum.ENABLED
                criterion.keyword.text = kw_text.strip('"[]')[:80]
                criterion.keyword.match_type = match_type_enum
                operations.append(op)
        if not operations:
            return []
        response = service.mutate_ad_group_criteria(customer_id=customer_id, operations=operations)
        return [r.resource_name for r in response.results]

    def _create_rsa(self, customer_id, ad_group_resource, headlines, descriptions, final_url):
        service = self.client.get_service("AdGroupAdService")
        op = self.client.get_type("AdGroupAdOperation")
        aga = op.create
        aga.ad_group = ad_group_resource
        aga.status = self.client.enums.AdGroupAdStatusEnum.ENABLED
        ad = aga.ad
        ad.final_urls.append(final_url)
        for hl in headlines[:15]:
            h = self.client.get_type("AdTextAsset")
            h.text = hl[:30]
            ad.responsive_search_ad.headlines.append(h)
        for desc in descriptions[:4]:
            d = self.client.get_type("AdTextAsset")
            d.text = desc[:90]
            ad.responsive_search_ad.descriptions.append(d)
        response = service.mutate_ad_group_ads(customer_id=customer_id, operations=[op])
        return response.results[0].resource_name

    def _apply_kostenstelle_label(self, customer_id, campaign_resource, kostenstelle):
        try:
            label_service = self.client.get_service("LabelService")
            label_op = self.client.get_type("LabelOperation")
            label = label_op.create
            label.name = f"KST-{kostenstelle}"
            label.status = self.client.enums.LabelStatusEnum.ENABLED
            label_response = label_service.mutate_labels(customer_id=customer_id, operations=[label_op])
            label_resource = label_response.results[0].resource_name
            cl_service = self.client.get_service("CampaignLabelService")
            cl_op = self.client.get_type("CampaignLabelOperation")
            cl = cl_op.create
            cl.campaign = campaign_resource
            cl.label = label_resource
            cl_service.mutate_campaign_labels(customer_id=customer_id, operations=[cl_op])
        except Exception:
            pass


def eur_to_micros(eur: float) -> int:
    return int(float(eur) * 1_000_000)

def extract_id(resource_name: str) -> str:
    return resource_name.split("/")[-1]
