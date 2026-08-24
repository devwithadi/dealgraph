from collections.abc import Iterable

YC_URL = "https://yc-oss.github.io/api/companies/all.json"
HN_URL = "https://hn.algolia.com/api/v1/search_by_date"
SOURCE_REGISTRY = {
    "regulatory": {
        "access": "public_api",
        "trust": "official_filing",
        "enabled": True,
        "evidence_type": "regulatory",
        "financial_priority": 0,
    },
    "yc": {
        "url": YC_URL,
        "access": "public_api",
        "trust": "curated_directory",
        "enabled": True,
        "evidence_type": "yc_directory",
        "financial_priority": 2,
        "manifest": YC_URL,
    },
    "hacker_news": {
        "url": HN_URL,
        "access": "public_api",
        "trust": "public_community",
        "enabled": False,
        "evidence_type": "hacker_news",
        "manifest": HN_URL,
    },
    "product_hunt": {
        "access": "agent_reach_scraper",
        "trust": "product_community",
        "enabled": True,
        "evidence_type": "product_hunt",
        "manifest": "Product Hunt Discovery",
    },
    "company_website": {
        "access": "public_html",
        "trust": "first_party_self_reported",
        "enabled": False,
        "evidence_type": "company_website",
        "financial_priority": 1,
        "manifest": "company public websites",
    },
    "agent_reach": {
        "access": "exa_via_mcporter",
        "trust": "open_web",
        "enabled": True,
        "evidence_type": "agent_reach",
        "manifest": "Agent Reach / Exa web search",
    },
    "deep_diligence": {
        "access": "multi_hop_exa_via_mcporter",
        "trust": "open_web",
        "enabled": True,
        "evidence_type": "deep_diligence",
        "manifest": "Deep Diligence multi-hop research",
    },
    "pitchbook": {"access": "licensed_api_only", "trust": "licensed_vendor", "enabled": False},
}


def source_enabled(name: str) -> bool:
    return bool(SOURCE_REGISTRY.get(name, {}).get("enabled"))


def enabled_manifest_sources(names: Iterable[str] | None = None) -> list[str]:
    ordered_names = tuple(names) if names is not None else tuple(SOURCE_REGISTRY)
    return [
        str(SOURCE_REGISTRY[name]["manifest"])
        for name in ordered_names
        if name in SOURCE_REGISTRY
        and SOURCE_REGISTRY[name].get("enabled")
        and "manifest" in SOURCE_REGISTRY[name]
    ]


def financial_source_priority() -> dict[str, int]:
    return {
        str(config["evidence_type"]): int(config["financial_priority"])
        for config in SOURCE_REGISTRY.values()
        if "evidence_type" in config
        and "financial_priority" in config
    }
