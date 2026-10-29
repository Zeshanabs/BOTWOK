"""The 13 AgentSpecs (doc 06 §6.3 actions, §6.4 tool allowlists) + orchestration pseudo-specs for prompt management."""
from __future__ import annotations

from app.agents.base import ActionSpec, AgentSpec
from app.agents.schemas import (
    CalendarPlan,
    CompetitorAnalysis,
    CompetitorComparison,
    CompetitorList,
    ContentDraft,
    CrawlResult,
    Critique,
    FactCheck,
    GapAnalysis,
    IdeaBatch,
    Insights,
    IntentResult,
    MixRecommendation,
    OpportunitySelection,
    Plan,
    Report,
    ResearchResult,
    SocialListeningResult,
    SourceDetail,
    Strategy,
    TrendExplanation,
    TrendSet,
    Variant,
    VisualPlan,
)


def A(name: str, label: str, output, description: str = "", *, approval: bool = False, tokens: int | None = None,
      untrusted_keys: list[str] | None = None) -> ActionSpec:
    return ActionSpec(name=name, label=label, output_model=output, description=description, approval=approval,
                      expected_output_tokens=tokens, untrusted_input_keys=untrusted_keys)


SPECS: dict[str, AgentSpec] = {
    "research": AgentSpec(
        id="research", name="Research", tier="balanced", untrusted_inputs=True, output_requires_sources=True,
        description="Web search, fetch, extract, rank, dedupe, summarize with citations.",
        actions={
            "research": A("research", "Researching web", ResearchResult,
                          "research(query, scope=[web|news|rss|competitor_sites|keywords], depth, recency_days, domains_allow/deny)",
                          tokens=1800),
            "read_source": A("read_source", "Reading source", SourceDetail, "read_source(source_id, section?)", tokens=900),
            "crawl_site": A("crawl_site", "Crawling site", CrawlResult, "crawl_site(url, max_pages)", tokens=1500),
        },
        tools=["web.search", "web.fetch", "web.crawl", "rss.read", "research.save_source", "research.read_source",
               "research.find_similar", "keywords.lookup", "memory.search", "brand.get_context"],
        max_turns=10, max_tool_calls=30, expected_output_tokens=1800),
    "social_listening": AgentSpec(
        id="social_listening", name="Social Listening", tier="balanced", untrusted_inputs=True, output_requires_sources=True,
        description="Permitted public social content and audience signals via official APIs only.",
        actions={
            "collect_public_posts": A("collect_public_posts", "Checking social channels", SocialListeningResult,
                                      "collect_public_posts(targets[{platform, handle}], since)", tokens=1600),
            "search_topic": A("search_topic", "Searching social topic", SocialListeningResult,
                              "search_topic(platform, query, since)", tokens=1600),
            "audience_signals": A("audience_signals", "Reading audience signals", SocialListeningResult,
                                  "audience_signals(brand_accounts)", tokens=1400),
        },
        tools=["social.search", "social.profile", "social.hashtag", "social.own_insights", "research.save_source",
               "brand.get_context"],
        max_turns=8, max_tool_calls=20, expected_output_tokens=1600),
    "competitor_intel": AgentSpec(
        id="competitor_intel", name="Competitor Intelligence", tier="powerful", untrusted_inputs=True, output_requires_sources=True,
        description="Structured competitor intelligence, comparisons and gap analysis from allowed sources.",
        actions={
            "resolve_competitors": A("resolve_competitors", "Resolving competitors", CompetitorList, "resolve_competitors(limit)", tokens=600),
            "analyze": A("analyze", "Analyzing competitor", CompetitorAnalysis, "analyze(competitor_id, sources, posts)", tokens=2000),
            "compare": A("compare", "Comparing competitors", CompetitorComparison, "compare(competitor_ids)", tokens=1500),
            "find_gaps": A("find_gaps", "Finding opportunities", GapAnalysis, "find_gaps(analysis, brand)", tokens=1500),
        },
        tools=["competitors.get", "competitors.list", "competitors.list_posts", "competitors.list_snapshots",
               "competitors.save_analysis", "research.read_source", "research.find_similar", "stats.describe",
               "analytics.query", "brand.get_context", "memory.search"],
        max_turns=8, max_tool_calls=25, expected_output_tokens=2000),
    "trend": AgentSpec(
        id="trend", name="Trend Detection", tier="balanced", output_requires_sources=True, untrusted_inputs=True,
        description="Detect and label emerging topics from deterministic signals, news and keywords.",
        actions={
            "detect": A("detect", "Finding trends", TrendSet, "detect(industry, window_days)", tokens=1500),
            "explain": A("explain", "Explaining trend", TrendExplanation, "explain(trend_id)", tokens=900),
        },
        tools=["trends.signals", "trends.save", "trends.list", "web.search", "web.fetch", "keywords.lookup",
               "stats.describe", "brand.get_context"],
        max_turns=8, max_tool_calls=20, expected_output_tokens=1500),
    "strategy": AgentSpec(
        id="strategy", name="Strategy", tier="powerful",
        description="Pillars, mix, platform strategy, campaigns, calendar planning and opportunity selection.",
        actions={
            "build_strategy": A("build_strategy", "Building strategy", Strategy, "build_strategy(goals, platforms, horizon)", tokens=2500),
            "recommend_mix": A("recommend_mix", "Recommending mix", MixRecommendation, "recommend_mix(period)", tokens=1200),
            "plan_calendar": A("plan_calendar", "Planning calendar", CalendarPlan, "plan_calendar(period, slots)", tokens=2500),
            "select_opportunities": A("select_opportunities", "Selecting opportunities", OpportunitySelection,
                                      "select_opportunities(candidates, n)", tokens=1200),
            "propose_schedule": A("propose_schedule", "Proposing schedule", CalendarPlan,
                                  "propose_schedule(variant_ids, slots) → approval", approval=True, tokens=800),
        },
        tools=["brand.get_context", "analytics.query", "insights.list", "competitors.summary", "trends.list", "memory.search",
               "memory.remember", "strategy.save", "stats.describe", "stats.compare_groups", "publishing.propose_schedule"],
        max_turns=8, max_tool_calls=20, expected_output_tokens=2500),
    "ideation": AgentSpec(
        id="ideation", name="Ideation", tier="cheap",
        description="High-volume, diverse, on-brand content ideas tied to evidence.",
        actions={"generate": A("generate", "Generating ideas", IdeaBatch,
                               "generate(count, pillars?, platforms?, from=[trend_ids|research_run_id|insight_ids|freeform])",
                               tokens=2500)},
        tools=["brand.get_context", "ideas.list_recent", "ideas.save", "memory.search", "research.find_similar", "trends.list"],
        max_turns=6, max_tool_calls=12, expected_output_tokens=2500, temperature=0.7),
    "writer": AgentSpec(
        id="writer", name="Writer", tier="powerful",
        description="Master content and first platform draft: hook, body, CTA, hashtags, visual concept, alt text.",
        actions={
            "write": A("write", "Writing post", ContentDraft,
                       "write(brief{idea_id|prompt, platform, format, content_type, length, cta_goal, sources[]})", tokens=1800),
            "rewrite": A("rewrite", "Rewriting post", ContentDraft, "rewrite(content_id, instructions)", tokens=1800),
            "expand_to_article": A("expand_to_article", "Expanding to article", ContentDraft, "expand_to_article(content_id)",
                                   tokens=3500),
        },
        tools=["brand.get_context", "research.read_source", "hashtags.suggest", "keywords.lookup", "platform.rules",
               "content.create_draft", "content.update_draft", "content.get", "memory.search"],
        max_turns=8, max_tool_calls=15, expected_output_tokens=1800, temperature=0.6),
    "repurposer": AgentSpec(
        id="repurposer", name="Repurposer", tier="balanced",
        description="Master content → platform-native variants under platform rules (fan-out).",
        actions={"adapt": A("adapt", "Adapting for platform", Variant, "adapt(content_id, target_platform, format)", tokens=1400)},
        tools=["content.get", "platform.rules", "hashtags.suggest", "content.create_variant", "brand.get_context"],
        max_turns=6, max_tool_calls=10, expected_output_tokens=1400, temperature=0.5),
    "visual": AgentSpec(
        id="visual", name="Visual", tier="balanced",
        description="Visual concepts, image prompts, carousel layouts, video scripts; orchestrates MediaService tools.",
        actions={
            "concept": A("concept", "Designing visual concept", VisualPlan, "concept(content_id)", tokens=1200),
            "generate_image": A("generate_image", "Generating image", VisualPlan, "generate_image(content_id, concept, style)", tokens=900),
            "carousel": A("carousel", "Planning carousel", VisualPlan, "carousel(content_id, slides)", tokens=1600),
            "video_script": A("video_script", "Writing video script", VisualPlan, "video_script(content_id, duration, format)", tokens=1800),
        },
        tools=["brand.get_visual_identity", "brand.get_context", "media.generate_image", "media.edit", "media.compose_carousel",
               "media.transform_for_platform", "media.attach", "content.get"],
        max_turns=8, max_tool_calls=12, expected_output_tokens=1400, temperature=0.6),
    "critic": AgentSpec(
        id="critic", name="Critic", tier="balanced",
        description="Quality, brand, platform and policy scoring with rewrite suggestions (never edits; different model than writer).",
        actions={"critique": A("critique", "Quality checking", Critique, "critique(content_id|variant_id)", tokens=1200)},
        tools=["content.get", "brand.get_context", "platform.rules", "policy.check", "hashtags.validate"],
        max_turns=6, max_tool_calls=10, expected_output_tokens=1200, temperature=0.2),
    "fact_check": AgentSpec(
        id="fact_check", name="Fact Check", tier="balanced", untrusted_inputs=True, output_requires_sources=True,
        description="Claim extraction and verification against sources.",
        actions={"check": A("check", "Fact checking", FactCheck, "check(content_id)", tokens=1500)},
        tools=["claims.extract", "research.read_source", "research.save_source", "web.search", "web.fetch", "factcheck.save",
               "content.get"],
        max_turns=10, max_tool_calls=25, expected_output_tokens=1500, temperature=0.1),
    "performance_analyst": AgentSpec(
        id="performance_analyst", name="Performance Analyst", tier="powerful",
        description="Insights and recommendations from normalized metrics; numbers come only from tools.",
        actions={
            "analyze": A("analyze", "Analyzing performance", Insights, "analyze(brand_id, period, dimensions)", tokens=2000),
            "compare_periods": A("compare_periods", "Comparing periods", Insights, "compare_periods(period_a, period_b)", tokens=1500),
            "competitor_delta": A("competitor_delta", "Comparing with competitors", Insights, "competitor_delta(competitor_ids, period)",
                                  tokens=1500),
        },
        tools=["analytics.query", "stats.compare_groups", "stats.time_of_day", "stats.trend", "stats.describe",
               "competitors.list_snapshots", "insights.save", "recommendations.save", "memory.search", "memory.remember",
               "brand.get_context", "publishing.propose_schedule"],
        max_turns=8, max_tool_calls=20, expected_output_tokens=2000, temperature=0.2),
    "report": AgentSpec(
        id="report", name="Report", tier="balanced", output_requires_sources=True,
        description="Compose readable reports (weekly, competitor, campaign, research brief) from stored data.",
        actions={"compose": A("compose", "Composing report", Report, "compose(kind, inputs, audience, length)", tokens=3000)},
        tools=["reports.get_data", "reports.render", "reports.save", "analytics.query", "stats.describe", "brand.get_context"],
        max_turns=6, max_tool_calls=10, expected_output_tokens=3000, temperature=0.3),
}

ORCHESTRATION_SPECS: dict[str, AgentSpec] = {
    "intent_router": AgentSpec(id="intent_router", name="Intent Router", tier="cheap", orchestration=True,
                               description="Classifies messages into intents (orchestration component).",
                               actions={"route": A("route", "Understanding request", IntentResult, tokens=400)},
                               max_turns=1, max_tool_calls=0, expected_output_tokens=400, temperature=0.0),
    "planner": AgentSpec(id="planner", name="Planner", tier="powerful", orchestration=True,
                         description="Produces the plan DAG (orchestration component).",
                         actions={"plan": A("plan", "Planning", Plan, tokens=1500)},
                         max_turns=1, max_tool_calls=0, expected_output_tokens=1500, temperature=0.1),
}

ALL_SPECS: dict[str, AgentSpec] = {**SPECS, **ORCHESTRATION_SPECS}
