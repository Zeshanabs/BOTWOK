"""Seeded domain-reputation priors for credibility scoring (doc 07 §7.4 ``domain_prior``).

Values are 0–1 priors, not verdicts: gov/edu/intergovernmental, wire services and major outlets, official vendor/platform
documentation rank high; user-generated platforms and known content farms rank low; everything else defaults to 0.5.
A workspace can pin overrides (passed in as ``overrides``).
"""
from __future__ import annotations

from collections.abc import Mapping

from app.research.urls import domain_of

DEFAULT_PRIOR = 0.5

SEEDED: dict[str, float] = {
    # wire services & major outlets
    "reuters.com": 0.92, "apnews.com": 0.92, "afp.com": 0.9, "bbc.co.uk": 0.88, "bbc.com": 0.88, "nytimes.com": 0.86,
    "washingtonpost.com": 0.85, "wsj.com": 0.86, "ft.com": 0.87, "economist.com": 0.87, "bloomberg.com": 0.87,
    "theguardian.com": 0.84, "npr.org": 0.85, "pbs.org": 0.84, "cnbc.com": 0.8, "cnn.com": 0.76, "axios.com": 0.8,
    "politico.com": 0.8, "theatlantic.com": 0.8, "latimes.com": 0.8, "usatoday.com": 0.74, "time.com": 0.78,
    "nature.com": 0.93, "science.org": 0.93, "sciencedirect.com": 0.85, "thelancet.com": 0.93, "nejm.org": 0.93,
    "arxiv.org": 0.75, "pubmed.ncbi.nlm.nih.gov": 0.9, "statista.com": 0.75, "pewresearch.org": 0.9,
    "hbr.org": 0.82, "mckinsey.com": 0.78, "gartner.com": 0.78, "forrester.com": 0.76, "deloitte.com": 0.74,
    # tech & marketing trade press
    "techcrunch.com": 0.76, "theverge.com": 0.76, "wired.com": 0.78, "arstechnica.com": 0.8, "engadget.com": 0.72,
    "zdnet.com": 0.7, "venturebeat.com": 0.7, "theinformation.com": 0.82, "adage.com": 0.78, "adweek.com": 0.76,
    "marketingweek.com": 0.74, "digiday.com": 0.76, "socialmediatoday.com": 0.66, "searchengineland.com": 0.72,
    "searchenginejournal.com": 0.66, "marketingland.com": 0.68, "businessinsider.com": 0.66, "forbes.com": 0.62,
    "fastcompany.com": 0.7, "inc.com": 0.62, "entrepreneur.com": 0.58, "mashable.com": 0.6,
    # official platform / vendor documentation and newsrooms
    "developers.facebook.com": 0.92, "about.fb.com": 0.86, "about.meta.com": 0.86, "transparency.meta.com": 0.88,
    "business.instagram.com": 0.86, "help.instagram.com": 0.86, "developers.google.com": 0.92, "blog.google": 0.84,
    "support.google.com": 0.86, "developer.x.com": 0.9, "developer.twitter.com": 0.9, "blog.x.com": 0.82,
    "learn.microsoft.com": 0.9, "docs.microsoft.com": 0.9, "learn.linkedin.com": 0.86, "developer.linkedin.com": 0.9,
    "news.linkedin.com": 0.84, "developers.tiktok.com": 0.9, "newsroom.tiktok.com": 0.82, "developers.pinterest.com": 0.9,
    "newsroom.pinterest.com": 0.82, "developers.google.com/youtube": 0.92, "blog.youtube": 0.84, "docs.anthropic.com": 0.9,
    "platform.openai.com": 0.9, "openai.com": 0.82, "anthropic.com": 0.82, "docs.python.org": 0.92, "w3.org": 0.92,
    "developer.mozilla.org": 0.92, "ietf.org": 0.92, "rfc-editor.org": 0.92, "github.com": 0.68,
    # reference
    "wikipedia.org": 0.7, "britannica.com": 0.82, "stackoverflow.com": 0.64, "who.int": 0.92, "un.org": 0.9,
    "oecd.org": 0.9, "worldbank.org": 0.9, "imf.org": 0.9, "europa.eu": 0.9,
    # user-generated platforms (signals, not authorities)
    "medium.com": 0.45, "substack.com": 0.48, "linkedin.com": 0.45, "youtube.com": 0.45, "reddit.com": 0.4,
    "quora.com": 0.32, "x.com": 0.35, "twitter.com": 0.35, "facebook.com": 0.32, "instagram.com": 0.32, "tiktok.com": 0.3,
    "pinterest.com": 0.3, "threads.net": 0.32, "tumblr.com": 0.3, "blogspot.com": 0.3, "wordpress.com": 0.35,
    "wix.com": 0.35, "weebly.com": 0.3,
    # content farms / low-quality aggregators
    "ehow.com": 0.2, "answers.com": 0.18, "ezinearticles.com": 0.1, "hubpages.com": 0.15, "articlesbase.com": 0.1,
    "buzzle.com": 0.15, "wikihow.com": 0.38, "buzzfeed.com": 0.38, "examiner.com": 0.15, "infobarrel.com": 0.1,
    "squidoo.com": 0.1, "livestrong.com": 0.35, "brainly.com": 0.2, "coursehero.com": 0.25, "scribd.com": 0.3,
}

HIGH_TRUST_SUFFIXES: dict[str, float] = {
    ".gov": 0.92, ".mil": 0.88, ".edu": 0.85, ".int": 0.9, ".gov.uk": 0.92, ".ac.uk": 0.85, ".gc.ca": 0.92,
    ".gov.au": 0.92, ".edu.au": 0.85, ".europa.eu": 0.9, ".gouv.fr": 0.9, ".bund.de": 0.9, ".go.jp": 0.9, ".gov.in": 0.88,
    ".govt.nz": 0.9, ".gov.sg": 0.9, ".ac.jp": 0.84, ".ac.in": 0.82, ".edu.cn": 0.8, ".gov.br": 0.86,
}
LOW_TRUST_SUFFIXES: dict[str, float] = {
    ".xyz": 0.35, ".top": 0.3, ".click": 0.25, ".buzz": 0.3, ".loan": 0.15, ".work": 0.35, ".info": 0.42, ".biz": 0.38,
}


def domain_prior(url_or_domain: str, overrides: Mapping[str, float] | None = None) -> float:
    """Most specific match wins: workspace override → seeded host/parent domain → TLD rule → default 0.5."""
    host = domain_of(url_or_domain) if ("/" in url_or_domain or ":" in url_or_domain) else url_or_domain.lower().removeprefix("www.")
    labels = host.split(".")
    candidates = [".".join(labels[i:]) for i in range(len(labels) - 1)]  # host, parent, …, eTLD+1-ish
    if overrides:
        for c in candidates:
            if c in overrides:
                return max(0.0, min(1.0, float(overrides[c])))
    for c in candidates:
        if c in SEEDED:
            return SEEDED[c]
    for suffix, v in sorted(HIGH_TRUST_SUFFIXES.items(), key=lambda kv: -len(kv[0])):
        if host.endswith(suffix):
            return v
    for suffix, v in LOW_TRUST_SUFFIXES.items():
        if host.endswith(suffix):
            return v
    return DEFAULT_PRIOR
