"""Fixed lists used across the app."""

CONTROVERSY_LIMITS = {"medium": "Medium or worse", "high": "High or worse", "severe": "Severe only"}

# Common exclusions with standard limits.
TEMPLATES = [
    {
        "key": "military", "label": "Military & defence revenue",
        "description": "Revenue from military customers, defence contracts, or products and services for military end use, including cloud and AI for armed forces.",
        "threshold": 0, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["military", "defence", "defense", "army", "weapon", "pentagon", "armed forces", "warfare"],
    },
    {
        "key": "military-finance", "label": "Defence investment & financing",
        "description": "Financing, venture investment or strategic stakes in defence companies.",
        "threshold": 0, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["defence fund", "stake", "investment", "financing", "venture"],
    },
    {
        "key": "controversial-weapons", "label": "Controversial weapons",
        "description": "Cluster munitions, anti-personnel mines, nuclear, chemical and biological weapons, including key components.",
        "threshold": 0, "watch_at": 30, "controversy_limit": "medium",
        "keywords": ["cluster", "landmine", "nuclear weapon", "chemical weapon", "biological", "controversial weapon"],
    },
    {
        "key": "surveillance", "label": "State surveillance & dual-use AI",
        "description": "Revenue from mass-surveillance, predictive policing or targeting tools sold to state security agencies.",
        "threshold": 5, "watch_at": 55, "controversy_limit": "high",
        "keywords": ["surveillance", "facial recognition", "intelligence", "spyware", "policing"],
    },
    {
        "key": "thermal-coal", "label": "Thermal coal",
        "description": "Mining of thermal coal or coal-fired power generation.",
        "threshold": 5, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["coal"],
    },
    {
        "key": "oil-gas-expansion", "label": "Oil & gas expansion",
        "description": "Exploration and development of new oil and gas fields, including Arctic and oil sands.",
        "threshold": 5, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["oil", "gas", "arctic", "oil sands", "fracking"],
    },
    {
        "key": "tobacco", "label": "Tobacco",
        "description": "Production of tobacco products; distribution above the limit.",
        "threshold": 0, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["tobacco", "cigarette", "nicotine"],
    },
    {
        "key": "gambling", "label": "Gambling",
        "description": "Operation of gambling services or supply of gambling equipment.",
        "threshold": 5, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["gambling", "casino", "betting"],
    },
    {
        "key": "adult", "label": "Adult entertainment",
        "description": "Production or distribution of adult entertainment.",
        "threshold": 0, "watch_at": 50, "controversy_limit": "high",
        "keywords": ["adult", "pornograph"],
    },
    {
        "key": "forced-labour", "label": "Forced labour in supply chain",
        "description": "Credible evidence of forced or child labour in own operations or tier-1 suppliers.",
        "threshold": 0, "watch_at": 40, "controversy_limit": "medium",
        "keywords": ["forced labour", "forced labor", "child labour", "uyghur", "modern slavery"],
    },
    {
        "key": "ungc", "label": "UN Global Compact violations",
        "description": "Severe, verified breaches of UNGC principles on human rights, labour, environment or corruption.",
        "threshold": 0, "watch_at": 40, "controversy_limit": "high",
        "keywords": ["human rights", "corruption", "bribery", "violation", "global compact"],
    },
]
