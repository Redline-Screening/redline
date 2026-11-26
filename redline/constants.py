"""Fixed lists used across the app."""

CONTROVERSY_LIMITS = {"medium": "Medium or worse", "high": "High or worse", "severe": "Severe only"}

TYPES = {"revenue": "Revenue-based", "conduct": "Conduct-based", "both": "Both"}

# Breach level fixed by type. Conduct-based criteria have their own level.
FIXED_LIMITS = {"revenue": "severe", "both": "high"}

# Stricter level for single standard exclusions, while their type is Both.
LIMIT_EXCEPTIONS = {"controversial-weapons": "medium"}


def fixed_limit(kind, key=None):
    """Incident breach level set by the rules, or None for conduct-based criteria."""
    if kind == "both" and key in LIMIT_EXCEPTIONS:
        return LIMIT_EXCEPTIONS[key]
    return FIXED_LIMITS.get(kind)


# Common exclusions with standard limits.
TEMPLATES = [
    {
        "key": "military", "type": "both", "label": "Military & defence revenue",
        "description": "Revenue from military customers, defence contracts, or products and services for military end use, including cloud and AI for armed forces.",
        "threshold": 0, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["military", "defence", "defense", "army", "weapon", "pentagon", "armed forces", "warfare"],
    },
    {
        "key": "military-finance", "type": "both", "label": "Defence investment & financing",
        "description": "Financing, venture investment or strategic stakes in defence companies.",
        "threshold": 0, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["defence fund", "stake", "investment", "financing", "venture"],
    },
    {
        "key": "controversial-weapons", "type": "both", "label": "Controversial weapons",
        "description": "Cluster munitions, anti-personnel mines, nuclear, chemical and biological weapons, including key components.",
        "threshold": 0, "watch_at": 30, "controversy_limit": "medium",
        "keywords": ["cluster", "landmine", "nuclear weapon", "chemical weapon", "biological", "controversial weapon"],
    },
    {
        "key": "surveillance", "type": "both", "label": "State surveillance & dual-use AI",
        "description": "Revenue from mass-surveillance, predictive policing or targeting tools sold to state security agencies.",
        "threshold": 5, "watch_at": 55, "controversy_limit": "high",
        "keywords": ["surveillance", "facial recognition", "intelligence", "spyware", "policing"],
    },
    {
        "key": "thermal-coal", "type": "revenue", "label": "Thermal coal",
        "description": "Mining of thermal coal or coal-fired power generation.",
        "threshold": 5, "watch_at": 50, "controversy_limit": "severe",
        "keywords": ["coal"],
    },
    {
        "key": "oil-gas-expansion", "type": "revenue", "label": "Oil & gas expansion",
        "description": "Exploration and development of new oil and gas fields, including Arctic and oil sands.",
        "threshold": 5, "watch_at": 50, "controversy_limit": "severe",
        "keywords": ["oil", "gas", "arctic", "oil sands", "fracking"],
    },
    {
        "key": "tobacco", "type": "revenue", "label": "Tobacco",
        "description": "Production of tobacco products; distribution above the limit.",
        "threshold": 0, "watch_at": 50, "controversy_limit": "severe",
        "keywords": ["tobacco", "cigarette", "nicotine"],
    },
    {
        "key": "gambling", "type": "revenue", "label": "Gambling",
        "description": "Operation of gambling services or supply of gambling equipment.",
        "threshold": 5, "watch_at": 50, "controversy_limit": "severe",
        "keywords": ["gambling", "casino", "betting"],
    },
    {
        "key": "adult", "type": "revenue", "label": "Adult entertainment",
        "description": "Production or distribution of adult entertainment.",
        "threshold": 0, "watch_at": 50, "controversy_limit": "severe",
        "keywords": ["adult", "pornography", "pornographic"],
    },
    {
        "key": "child-labour", "type": "conduct", "label": "Child labour",
        "description": "Child labour in own operations or the supply chain.",
        "threshold": None, "watch_at": 40, "controversy_limit": "high",
        "keywords": ["child labour", "child labor", "underage worker", "minors"],
    },
    {
        "key": "forced-labour", "type": "conduct", "label": "Forced labour",
        "description": "Forced, bonded or trafficked labour in own operations or the supply chain.",
        "threshold": None, "watch_at": 40, "controversy_limit": "high",
        "keywords": ["forced labour", "forced labor", "modern slavery", "human trafficking", "uyghur"],
    },
    {
        "key": "corruption", "type": "conduct", "label": "Corruption and bribery",
        "description": "Bribery, corruption, kickbacks or money laundering involving the company or its management.",
        "threshold": None, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["corruption", "bribery", "bribe", "kickback", "money laundering"],
    },
    {
        "key": "environmental-damage", "type": "conduct", "label": "Severe environmental damage",
        "description": "Severe pollution, deforestation, spills or other serious environmental harm.",
        "threshold": None, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["pollution", "deforestation", "oil spill", "toxic waste", "contamination"],
    },
    {
        "key": "human-rights", "type": "conduct", "label": "Human rights abuses",
        "description": "Involvement in serious human rights abuses, including violence, displacement or repression.",
        "threshold": None, "watch_at": 40, "controversy_limit": "high",
        "keywords": ["human rights", "abuse", "repression", "forced displacement", "indigenous rights"],
    },
    {
        "key": "ungc", "type": "conduct", "label": "UN Global Compact violations",
        "description": "Severe, verified breaches of UNGC principles on human rights, labour, environment or corruption.",
        "threshold": None, "watch_at": 40, "controversy_limit": "high",
        "keywords": ["human rights", "corruption", "bribery", "violation", "global compact"],
    },
]

MODES = {
    "provider": ("Data provider", "Revenue shares from provider files. Web search remains available for controversies."),
    "ai": ("AI screening", "AI estimates of revenue exposure and web search for controversies. No data licence required."),
    "both": ("Data provider and AI", "Provider figures take priority. AI covers controversies and missing figures."),
}

PROVIDERS = {
    "iss": "ISS STOXX",
    "msci": "MSCI ESG Research",
    "sustainalytics": "Morningstar Sustainalytics",
    "other": "Other provider",
}

FINDING_CATEGORIES = {
    "scandal": "Scandal", "court": "Court case", "ngo": "NGO report", "supply_chain": "Supply chain",
    "contract": "Contract", "investment": "Investment", "subsidiary": "Subsidiary", "financing": "Financing",
    "other": "Other",
}

MODEL_MANUAL = "claude-sonnet-5-5"
MODEL_MONITOR = "claude-haiku-5-5"
SEARCHES_MANUAL = 4
SEARCHES_MONITOR = 2

AI_NOTE = ("AI checks are funded privately for this school project and limited per day. "
           "Contact victoria.gueissaz@student.unisg.ch for a higher limit.")
