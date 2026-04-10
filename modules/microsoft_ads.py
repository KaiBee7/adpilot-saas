"""
Microsoft Advertising (Bing Ads) API Integration für Hofmann SEA-Kampagnen
============================================================================
Legt Search-Kampagnen im zentralen Microsoft Ads Account an.

Voraussetzungen:
  - Microsoft Ads Kundenkonto (Customer Account)
  - Developer Token (aus developer.microsoft.com/advertising)
  - OAuth2 Credentials (Client ID + Client Secret + Refresh Token)
  - Bingads Python SDK installiert (pip install bingads)

Kampagnenstruktur (identisch zu Google Ads):
  Campaign
  └── Ad Group: "{Jobtitel} - {Ort}"
      ├── Keywords (Broad + Phrase + Exact)
      └── Responsive Search Ad (RSA)

Kostenstellen-Abrechnung:
  - Kampagnenname enthält [KST-{nummer}]
  - Custom Parameters auf Kampagnenebene für Reporting
"""

import os
from bingads.service_client import ServiceClient
from bingads.authorization import (
    AuthorizationData,
    OAuthDesktopMobileAuthCodeGrant,
    OAuthWebAuthCodeGrant,
)
from bingads.v13.bulk import *
from bingads import ServiceClient


class MicrosoftAdsManager:
    """Verwaltet Microsoft Ads Kampagnen-Erstellung für Hofmann."""

    def __init__(self):
        """
        Initialisiert den Microsoft Ads Client mit OAuth2.
        """
        self.developer_token = os.getenv("MICROSOFT_ADS_DEVELOPER_TOKEN", "")
        self.client_id = os.getenv("MICROSOFT_ADS_CLIENT_ID", "")
        self.client_secret = os.getenv("MICROSOFT_ADS_CLIENT_SECRET", "")
        self.refresh_token = os.getenv("MICROSOFT_ADS_REFRESH_TOKEN", "")
        self.customer_id = os.getenv("MICROSOFT_ADS_CUSTOMER_ID", "")
        self.account_id = os.getenv("MICROSOFT_ADS_ACCOUNT_ID", "")

        # Auth-Objekt aufbauen
        self.authorization_data = AuthorizationData(
            account_id=self.account_id,
            customer_id=self.customer_id,
            developer_token=self.developer_token,
        )

        oauth = OAuthWebAuthCodeGrant(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirection_uri="",  # Kein Redirect für Server-to-Server
        )
        oauth._oauth_tokens.refresh_token = self.refresh_token
        self.authorization_data.authentication = oauth

        # Service Clients
        self.campaign_service = ServiceClient(
            service="CampaignManagementService",
            version=13,
            authorization_data=self.authorization_data,
            environment="production",
        )

    def create_search_campaign(self, config: dict) -> dict:
        """
        Erstellt eine vollständige Search-Kampagne in Microsoft Ads.

        Args:
            config: dict mit campaign_name, budget_eur, keywords, ad_copy,
                    final_url, kostenstelle, job_title, location, etc.

        Returns:
            dict mit campaign_id, ad_group_id und Status-Infos
        """
        try:
            # 1. Kampagne erstellen
            campaign_id = self._create_campaign(config)

            # 2. Anzeigengruppe erstellen
            ad_group_name = (
                f"{config['job_title']} | "
                f"{config.get('city', config.get('location', ''))}"
            )
            ad_group_id = self._create_ad_group(campaign_id, ad_group_name)

            # 3. Keywords hinzufügen
            kw_count = self._add_keywords(ad_group_id, config["keywords"])

            # 4. RSA-Anzeige erstellen
            self._create_rsa(
                ad_group_id=ad_group_id,
                headlines=config["ad_copy"]["headlines"],
                descriptions=config["ad_copy"]["descriptions"],
                final_url=config["final_url"],
            )

            return {
                "platform": "Microsoft Ads",
                "status": "created",
                "campaign_id": str(campaign_id),
                "campaign_name": config["name"],
                "ad_group_id": str(ad_group_id),
                "keywords_added": kw_count,
                "budget_eur": config["budget_eur"],
                "kostenstelle": config["kostenstelle"],
            }

        except Exception as e:
            raise RuntimeError(f"Microsoft Ads API Fehler: {e}") from e

    # ---- Private Methoden ----

    def _create_campaign(self, config: dict) -> int:
        """Erstellt eine Search-Kampagne und gibt die Campaign ID zurück."""
        campaign_service = self.campaign_service
        campaign_service_client = campaign_service.factory.create("Campaign")

        # Kampagnen-Typ: SearchAndContent (Standard Search)
        campaign_service_client.CampaignType = "Search"
        campaign_service_client.Name = config["name"]
        campaign_service_client.Description = (
            f"KST: {config['kostenstelle']} | "
            f"Niederlassung: {config.get('group_id', '')} | "
            f"Job-ID: {config.get('job_id', '')}"
        )

        # Budget (Tagesbudget)
        budget = campaign_service.factory.create("DailyBudget")
        budget.Amount = float(config["budget_eur"])
        campaign_service_client.BudgetType = "DailyBudgetStandard"
        campaign_service_client.DailyBudget = float(config["budget_eur"])

        # Status: Paused (erst manuell aktivieren nach Prüfung)
        campaign_service_client.Status = "Paused"

        # Bidding: ManualCpc
        bidding = campaign_service.factory.create("ManualCpc")
        campaign_service_client.BiddingScheme = bidding

        # Custom Parameter für Kostenstelle (für Reporting)
        custom_params = campaign_service.factory.create("CustomParameters")
        param = campaign_service.factory.create("CustomParameter")
        param.Key = "kst"
        param.Value = str(config["kostenstelle"])
        custom_params.Parameters = {"CustomParameter": [param]}
        campaign_service_client.UrlCustomParameters = custom_params

        response = campaign_service.AddCampaigns(
            AccountId=self.account_id,
            Campaigns={"Campaign": [campaign_service_client]},
        )

        return response.CampaignIds.long[0]

    def _create_ad_group(self, campaign_id: int, name: str) -> int:
        """Erstellt eine Anzeigengruppe und gibt die Ad Group ID zurück."""
        ad_group = self.campaign_service.factory.create("AdGroup")
        ad_group.Name = name[:256]
        ad_group.CampaignId = campaign_id
        ad_group.Status = "Active"

        # Standard-CPC: 0,50 €
        cpc_bid = self.campaign_service.factory.create("Bid")
        cpc_bid.Amount = 0.50
        ad_group.CpcBid = cpc_bid

        # Suchnetzwerk: Nur Bing Search
        ad_group.AdDistribution = "Search"

        response = self.campaign_service.AddAdGroups(
            CampaignId=campaign_id,
            AdGroups={"AdGroup": [ad_group]},
        )
        return response.AdGroupIds.long[0]

    def _add_keywords(self, ad_group_id: int, keywords: dict) -> int:
        """Fügt Keywords zur Anzeigengruppe hinzu."""
        keyword_objects = []

        match_type_map = {
            "broad_match": "Broad",
            "phrase_match": "Phrase",
            "exact_match": "Exact",
        }

        for kw_type, ms_match_type in match_type_map.items():
            for kw_text in keywords.get(kw_type, []):
                clean_kw = kw_text.strip('"[]')
                kw = self.campaign_service.factory.create("Keyword")
                kw.Text = clean_kw[:100]
                kw.MatchType = ms_match_type
                kw.Status = "Active"
                keyword_objects.append(kw)

        if not keyword_objects:
            return 0

        self.campaign_service.AddKeywords(
            AdGroupId=ad_group_id,
            Keywords={"Keyword": keyword_objects},
        )
        return len(keyword_objects)

    def _create_rsa(
        self,
        ad_group_id: int,
        headlines: list,
        descriptions: list,
        final_url: str,
    ) -> int:
        """Erstellt eine Responsive Search Ad."""
        ad = self.campaign_service.factory.create("ResponsiveSearchAd")
        ad.Type = "ResponsiveSearch"
        ad.Status = "Active"

        # Final URL
        final_urls = self.campaign_service.factory.create("ArrayOfstring")
        final_urls.string = [final_url]
        ad.FinalUrls = final_urls

        # Headlines
        headline_list = self.campaign_service.factory.create("ArrayOfAssetLink")
        for headline_text in headlines[:15]:
            asset_link = self.campaign_service.factory.create("AssetLink")
            text_asset = self.campaign_service.factory.create("TextAsset")
            text_asset.Text = headline_text[:30]
            asset_link.Asset = text_asset
            asset_link.PinnedField = None
            headline_list.AssetLink.append(asset_link)
        ad.Headlines = headline_list

        # Descriptions
        desc_list = self.campaign_service.factory.create("ArrayOfAssetLink")
        for desc_text in descriptions[:4]:
            asset_link = self.campaign_service.factory.create("AssetLink")
            text_asset = self.campaign_service.factory.create("TextAsset")
            text_asset.Text = desc_text[:90]
            asset_link.Asset = text_asset
            asset_link.PinnedField = None
            desc_list.AssetLink.append(asset_link)
        ad.Descriptions = desc_list

        response = self.campaign_service.AddAds(
            AdGroupId=ad_group_id,
            Ads={"Ad": [ad]},
        )
        return response.AdIds.long[0]
