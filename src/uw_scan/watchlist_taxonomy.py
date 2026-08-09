"""Watchlist industry-chain taxonomy — the single source of truth.

Lived in `scripts/research/watchlist_chain_candidates.py` until the chain join
table needed it; app code must not import from `scripts/`, so it moved here and
the research script now imports it back. One definition, three consumers: the
candidate screener, the membership seeder, and the API.

Shape: focus area -> layer -> chain -> tickers. The five-layer model (L1..L5)
describes the AI industrial chain and ONLY that; Index & Macro, Thematic and
Defensive are equally deliberate coverage with their own chains, not leftovers.

Membership is deliberately many-to-many. NVDA is in Computer/GPU, M7 and
Foundation-Model-Proxy; ARM is in three chains. UW bills per distinct ticker, so
extra memberships cost no budget — they cost schema, which is what
`uw_scan.watchlist_chain` exists to pay. A single `watchlist.sector` column
cannot express this, which is why Foundation-Model-Proxy looks empty on the
dashboard while all five of its members sit on the page tagged `M7`.

Names are English-only: these strings are rendered in the filter rail.
"""

from __future__ import annotations

from dataclasses import dataclass

AI = "AI"
INDEX = "Index & Macro"
THEMATIC = "Thematic"
DEFENSIVE = "Defensive"


@dataclass(frozen=True)
class Layer:
    key: str
    name: str
    focus: str
    chains: dict[str, tuple[str, ...]]


# Chains whose members are enumerated here. Tickers NOT listed in any chain
# still get one membership seeded from their existing `watchlist.sector` value,
# so nothing on the watchlist becomes unreachable by the filter.
LAYERS: tuple[Layer, ...] = (
    Layer(
        key="L1",
        name="Chip & System",
        focus=AI,
        chains={
            # ARM sits here, in Semi-Logic/ASIC and in Semi-Cap/EDA: its driver
            # is AI compute architecture, it licenses design IP like SNPS/CDNS,
            # and it still trades with the merchant-chip cohort.
            "Computer/GPU": ("NVDA", "AMD", "ARM", "SMCI", "DELL", "HPE", "HPQ"),
            "Semi-Logic/ASIC": (
                "AVGO",
                "MRVL",
                "ARM",
                "QCOM",
                "TXN",
                "NXPI",
                "MCHP",
                "SWKS",
                "QRVO",
                "LSCC",
                "RMBS",
                "ALGM",
                "SLAB",
            ),
            "Foundry": ("TSM", "INTC", "TSEM", "GFS", "UMC", "ASX"),
            "Semi-Cap/EDA": (
                "ARM",
                "ASML",
                "AMAT",
                "LRCX",
                "KLAC",
                "TER",
                "SNPS",
                "CDNS",
                "ONTO",
                "ACLS",
                "AEIS",
                "ICHR",
                "UCTT",
                "COHU",
                "FORM",
                "NVMI",
                "CAMT",
                "VECO",
                "AMKR",
            ),
            "Memory/Storage": ("MU", "SNDK", "WDC", "STX", "NTAP", "PSTG"),
            # NVTS added from the option-hot sweep: 564k OI, 44.6k contracts/day.
            "Analog/Power-Semi": ("ADI", "MPWR", "ON", "VSH", "DIOD", "POWI", "NVTS"),
        },
    ),
    Layer(
        key="L2",
        name="Cloud & Data Platform",
        focus=AI,
        chains={
            "Cloud/Hyperscaler": ("MSFT", "AMZN", "GOOGL", "ORCL", "IBM", "BABA"),
            "AI-Cloud/NeoCloud": (
                "CRWV",
                "NBIS",
                "IREN",
                "HUT",
                "CIFR",
                "APLD",
                "WULF",
                "CORZ",
                "GLXY",
                "BTDR",
                "CLSK",
            ),
            "Data-Platform": (
                "SNOW",
                "PLTR",
                "MDB",
                "CFLT",
                "ESTC",
                "DDOG",
                "TDC",
                "DOCN",
            ),
            "Cybersecurity": (
                "CRWD",
                "PANW",
                "NET",
                "ZS",
                "S",
                "FTNT",
                "OKTA",
                "CYBR",
                "TENB",
                "QLYS",
                "RPD",
                "VRNS",
                "CHKP",
            ),
        },
    ),
    Layer(
        key="L3",
        name="Datacenter Infrastructure",
        focus=AI,
        chains={
            # POET added from the option-hot sweep: 1,146k OI, 58.9k/day — it
            # clears both liquidity bars despite a $1.2B cap, which is exactly
            # the case the cap floor was kept low for.
            "Networking/Optical": (
                "ANET",
                "CRDO",
                "ALAB",
                "COHR",
                "LITE",
                "FN",
                "AAOI",
                "GLW",
                "NOK",
                "CIEN",
                "CSCO",
                "JNPR",
                "EXTR",
                "APH",
                "TEL",
                "POET",
            ),
            "Power/Electrical": (
                "VRT",
                "ETN",
                "PWR",
                "GEV",
                "POWL",
                "HUBB",
                "NVT",
                "ATKR",
                "AYI",
            ),
            "Generation/Nuclear": (
                "OKLO",
                "BE",
                "CEG",
                "VST",
                "TLN",
                "NRG",
                "SMR",
                "LEU",
                "NNE",
                "CCJ",
                "UEC",
                "PEG",
                "SO",
                "D",
            ),
            "Cooling/Thermal": ("MOD", "SPXC", "AAON", "CARR", "JCI", "TT", "LII"),
            # FRMI and KEEL rescue this chain: hand-authored it was EQIX/DLR/IRM/AMT
            # and none cleared the bar. The market-wide sweep found both (968k and
            # 1,076k OI) — the chain was never illiquid, my ticker list was wrong.
            "DC-REIT/Colo": ("EQIX", "DLR", "IRM", "AMT", "FRMI", "KEEL"),
            "EPC/Construction": ("MTZ", "DY", "EME", "FIX", "IESC", "STRL", "ACM", "J"),
        },
    ),
    Layer(
        key="L4",
        name="Application & Endpoint",
        focus=AI,
        chains={
            "Software/SaaS": (
                "CRM",
                "NOW",
                "ADBE",
                "INTU",
                "WDAY",
                "TEAM",
                "HUBS",
                "VEEV",
                "ZM",
                "DOCU",
                "TWLO",
                "SHOP",
                "FIG",
            ),
            "AI-App/Consumer-Net": (
                "APP",
                "TTD",
                "RDDT",
                "SPOT",
                "DASH",
                "ABNB",
                "U",
                "RBLX",
                "PINS",
                "SNAP",
                "NFLX",
                "UBER",
            ),
            "Robotics/Automation": ("SYM", "ROK", "EMR", "HON", "ISRG", "OSIS", "ZBRA"),
            "Healthcare-AI/LS-Tools": ("TEM", "RXRX", "DNA", "ILMN", "TMO", "A", "DHR"),
            "Devices/Endpoint": ("AAPL", "TSLA", "SONY", "GRMN", "LOGI"),
        },
    ),
    Layer(
        key="L5",
        name="Model & Tooling",
        focus=AI,
        chains={
            # 5/5 already on the watchlist and tagged M7. This chain is the whole
            # argument for the join table: without it the layer reads as empty
            # while every member is on screen under another tag.
            "Foundation-Model-Proxy": ("MSFT", "GOOGL", "META", "AMZN", "NVDA"),
            "AI-Native-Software": ("AI", "SOUN", "BBAI", "INOD", "PATH", "CXAI"),
            "DevTools/Observability": ("GTLB", "DDOG", "FROG", "PD", "DT"),
            "IT-Services/Integration": (
                "ACN",
                "EPAM",
                "GLOB",
                "CTSH",
                "INFY",
                "WIT",
                "DXC",
            ),
        },
    ),
    Layer(
        key="X",
        name="Cross-cutting",
        focus=AI,
        chains={"M7": ("AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA")},
    ),
    # Non-AI focus areas. Their chains match the legacy `watchlist.sector` tags
    # one-for-one, so membership seeds from the existing column rather than a
    # ticker list here — except Quantum, which is new and therefore enumerated.
    Layer(
        key="IDX",
        name="Index & Macro",
        focus=INDEX,
        chains={"Beta": (), "Sector-ETF": (), "Credit": (), "Macro": ()},
    ),
    Layer(
        key="THM",
        name="Thematic",
        focus=THEMATIC,
        chains={
            "Crypto": ("BMNR",),
            "Fintech": ("PYPL",),
            "Space": (),
            # IBM is here AND in L2 Cloud/Hyperscaler — the exact many-to-many
            # case that motivated the join table.
            "Quantum": ("IONQ", "RGTI", "IBM"),
        },
    ),
    Layer(
        key="DEF",
        name="Defensive",
        focus=DEFENSIVE,
        chains={"Healthcare": (), "Energy": (), "Banks": (), "Consumer": ()},
    ),
)

# The 59 tickers approved for addition. Everything else named above is either
# already on the watchlist or was screened out — being listed in a chain does
# NOT mean a ticker gets scanned, only that it is placed if present.
SELECTED_ADDS: frozenset[str] = frozenset(
    """
    ABNB ACN ADBE APLD BABA BTDR CCJ CEG CIFR CLSK CORZ CSCO DASH DDOG DELL
    GEV GLXY HPE HPQ INFY MCHP MDB NOW ON PATH PINS RBLX RDDT S SHOP SMCI SMR
    SNAP SOUN STX TEM TTD U UEC UMC VRT VST WULF ZM ZS
    BBAI BMNR FIG FRMI IONQ KEEL NFLX NVTS POET PYPL RGTI UBER
    CARR MTZ
    """.split()
)


def memberships() -> list[tuple[str, str, str]]:
    """Flatten to (ticker, layer_key, chain) triples for seeding."""
    return [
        (ticker, layer.key, chain)
        for layer in LAYERS
        for chain, tickers in layer.chains.items()
        for ticker in tickers
    ]


def chains_for(ticker: str) -> list[str]:
    """Every chain a ticker belongs to, in layer order."""
    t = ticker.upper()
    return [
        chain
        for layer in LAYERS
        for chain, tickers in layer.chains.items()
        if t in tickers
    ]


def all_chains() -> list[tuple[str, str, str]]:
    """(layer_key, layer_name, chain) for every chain, in declared order."""
    return [
        (layer.key, layer.name, chain) for layer in LAYERS for chain in layer.chains
    ]


def legacy_sector_chains() -> frozenset[str]:
    """Chains that are also legacy `watchlist.sector` values.

    These seed from the existing column instead of a ticker list, so an empty
    tuple above means "inherit", not "nobody".
    """
    return frozenset(
        chain
        for layer in LAYERS
        for chain, tickers in layer.chains.items()
        if not tickers or chain in {"M7", "Crypto", "Fintech"}
    )
