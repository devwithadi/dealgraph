from dataclasses import dataclass

BLOCKED_HOSTS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AgentReachDirectorySource:
    host: str
    site_filter: str
    batch: str
    tag: str
    label: str


@dataclass(frozen=True)
class AgentReachConstants:
    discovery_candidate_limit: int = 15
    discovery_max_search_results: int = 20
    research_result_limit: int = 5
    mcporter_timeout_milliseconds: int = 30_000
    subprocess_timeout_seconds: int = 35
    max_output_bytes: int = 200_000
    discovery_model_max_tokens: int = 2_000
    highlight_max_characters: int = 350
    default_batch: str = "Agent Reach Discovery"
    default_tags: tuple[str, ...] = ("Agent Reach", "Discovery", "AI")
    product_hunt_batch: str = "Product Hunt Launch"
    techcrunch_batch: str = "TechCrunch Featured"
    directory_sources: tuple[AgentReachDirectorySource, ...] = (
        AgentReachDirectorySource(
            host="pitchbook.com",
            site_filter="site:pitchbook.com",
            batch="PitchBook Profile",
            tag="PitchBook",
            label="PitchBook",
        ),
        AgentReachDirectorySource(
            host="crunchbase.com",
            site_filter="site:crunchbase.com",
            batch="Crunchbase Profile",
            tag="Crunchbase",
            label="Crunchbase",
        ),
        AgentReachDirectorySource(
            host="linkedin.com",
            site_filter="site:linkedin.com/company",
            batch="LinkedIn Company Profile",
            tag="LinkedIn",
            label="LinkedIn",
        ),
    )

    @property
    def directory_hosts(self) -> tuple[str, ...]:
        return tuple(source.host for source in self.directory_sources)

    @property
    def directory_site_filters(self) -> tuple[str, ...]:
        return tuple(source.site_filter for source in self.directory_sources)

    @property
    def directory_labels_text(self) -> str:
        labels = [source.label for source in self.directory_sources]
        if len(labels) == 1:
            return labels[0]
        return f"{', '.join(labels[:-1])}, and {labels[-1]}"

    @property
    def pitchbook_batch(self) -> str:
        return self.directory_sources[0].batch

    @property
    def crunchbase_batch(self) -> str:
        return self.directory_sources[1].batch

    @property
    def linkedin_batch(self) -> str:
        return self.directory_sources[2].batch


AGENT_REACH = AgentReachConstants()
DIRECTORY_HOSTS: frozenset[str] = frozenset(AGENT_REACH.directory_hosts)
