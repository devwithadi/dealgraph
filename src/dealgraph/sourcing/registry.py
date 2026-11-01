"""Configured and explicitly trusted source endpoints."""

YC_URL = "https://yc-oss.github.io/api/companies/all.json"
HN_URL = "https://hn.algolia.com/api/v1/search_by_date"
SOURCE_REGISTRY = {
    "yc": {"url": YC_URL, "access": "public_api", "trust": "curated_directory", "enabled": True},
    "hacker_news": {"url": HN_URL, "access": "public_api", "trust": "public_community", "enabled": True},
    "company_website": {"access": "public_html", "trust": "first_party_self_reported", "enabled": True},
    "pitchbook": {"access": "licensed_api_only", "trust": "licensed_vendor", "enabled": False},
}
