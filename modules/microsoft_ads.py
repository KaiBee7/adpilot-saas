"""
Microsoft Advertising (Bing Ads) API Integration für Hofmann SEA-Kampagnen
============================================================================
"""

import os

# Bedingter Import – bingads Paket nur wenn installiert
try:
    from bingads.service_client import ServiceClient
    from bingads.authorization import AuthorizationData, OAuthWebAuthCodeGrant
    MICROSOFT_ADS_AVAILABLE = True
except ImportError:
    MICROSOFT_ADS_AVAILABLE = False
    ServiceClient = None
    AuthorizationData = None
    OAuthWebAuthCodeGrant = None


class MicrosoftAdsManager:
    """Verwaltet Microsoft Ads Kampagnen-Erstellung für Hofmann."""

    def __init__(self):
        if not MICROSOFT_ADS_AVAILABLE:
            raise RuntimeError(
                "Microsoft Ads Paket nicht installiert. "
                "Bitte 'bingads' in requirements.txt aktivieren und API-Credentials konfigurieren."
            )

        self.developer_token = os.getenv("MICROSOFT_ADS_DEVELOPER_TOKEN", "")
        self.client_id       = os.getenv("MICROSOFT_ADS_CLIENT_ID", "")
        self.client_secret   = os.getenv("MICROSOFT_ADS_CLIENT_SECRET", "")
        self.refresh_token   = os.getenv("MICROSOFT_ADS_REFRESH_TOKEN", "")
        self.customer_id     = os.getenv("MICROSOFT_ADS_CUSTOMER_ID", "")
        self.account_id      = os.getenv("MICROSOFT_ADS_ACCOUNT_ID", "")

        self.authorization_data = AuthorizationData(
            account_id=self.account_id,
            customer_id=self.customer_id,
            developer_token=self.developer_token,
        )
        oauth = OAuthWebAuthCodeGrant(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirection_uri="",
        )
        oauth._oauth_tokens.refresh_token = self.refresh_token
        self.authorization_data.authentication = oauth

        self.campaign_service = ServiceClient(
            service="CampaignManagementService",
            version=13,
            authorization_data=self.authorization_data,
            environment="production",
        )

    def create_search_campaign(self, config: dict) -> dict:
        try:
            campaign_id  = self._create_campaign(config)
            ad_group_name = f"{config['job_title']} | {config.get('city', config.get('location', ''))}"
            ad_group_id  = self._create_ad_group(campaign_id, ad_group_name)
            kw_count     = self._add_keywords(ad_group_id, config["keywords"])
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

    def _create_campaign(self, config):
        svc = self.campaign_service
        c = svc.factory.create("Campaign")
        c.CampaignType = "Search"
        c.Name = config["name"]
        c.Description = f"KST: {config['kostenstelle']} | Job-ID: {config.get('job_id', '')}"
        c.BudgetType = "DailyBudgetStandard"
        c.DailyBudget = float(config["budget_eur"])
        c.Status = "Paused"
        c.BiddingScheme = svc.factory.create("ManualCpc")
        response = svc.AddCampaigns(
            AccountId=self.account_id,
            Campaigns={"Campaign": [c]},
        )
        return response.CampaignIds.long[0]

    def _create_ad_group(self, campaign_id, name):
        svc = self.campaign_service
        ag = svc.factory.create("AdGroup")
        ag.Name = name[:256]
        ag.CampaignId = campaign_id
        ag.Status = "Active"
        bid = svc.factory.create("Bid")
        bid.Amount = 0.50
        ag.CpcBid = bid
        ag.AdDistribution = "Search"
        response = svc.AddAdGroups(CampaignId=campaign_id, AdGroups={"AdGroup": [ag]})
        return response.AdGroupIds.long[0]

    def _add_keywords(self, ad_group_id, keywords):
        svc = self.campaign_service
        kws = []
        for kw_type, ms_type in [("broad_match","Broad"),("phrase_match","Phrase"),("exact_match","Exact")]:
            for kw_text in keywords.get(kw_type, []):
                kw = svc.factory.create("Keyword")
                kw.Text = kw_text.strip('"[]')[:100]
                kw.MatchType = ms_type
                kw.Status = "Active"
                kws.append(kw)
        if not kws:
            return 0
        svc.AddKeywords(AdGroupId=ad_group_id, Keywords={"Keyword": kws})
        return len(kws)

    def _create_rsa(self, ad_group_id, headlines, descriptions, final_url):
        svc = self.campaign_service
        ad = svc.factory.create("ResponsiveSearchAd")
        ad.Type = "ResponsiveSearch"
        ad.Status = "Active"
        urls = svc.factory.create("ArrayOfstring")
        urls.string = [final_url]
        ad.FinalUrls = urls
        hl_list = svc.factory.create("ArrayOfAssetLink")
        for hl in headlines[:15]:
            link = svc.factory.create("AssetLink")
            asset = svc.factory.create("TextAsset")
            asset.Text = hl[:30]
            link.Asset = asset
            hl_list.AssetLink.append(link)
        ad.Headlines = hl_list
        desc_list = svc.factory.create("ArrayOfAssetLink")
        for desc in descriptions[:4]:
            link = svc.factory.create("AssetLink")
            asset = svc.factory.create("TextAsset")
            asset.Text = desc[:90]
            link.Asset = asset
            desc_list.AssetLink.append(link)
        ad.Descriptions = desc_list
        response = svc.AddAds(AdGroupId=ad_group_id, Ads={"Ad": [ad]})
        return response.AdIds.long[0]
