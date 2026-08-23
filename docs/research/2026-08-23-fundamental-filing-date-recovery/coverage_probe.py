import json, psycopg
from uw_scan.config import Settings
seen = set(["A", "AAOI", "AAON", "AAP", "AAPL", "AAT", "ABBV", "ABCB", "ABEO", "ABG", "ABM", "ABNB", "ABR", "ABT", "ACAD", "ACCO", "ACGL", "ACH", "ACIW", "ACLS", "ACM", "ACN", "ACNT", "ACRE", "ACTG", "ADBE", "ADI", "ADM", "ADP", "ADSK", "AEE", "AEHR", "AEIS", "AEO", "AEP", "AES", "AFL", "AI", "AIG", "AIZ", "AJG", "AKAM", "ALAB", "ALB", "ALGM", "ALGN", "ALL", "ALNY", "AMAT", "AMD", "AME", "AMGN", "AMKR", "AMP", "AMT", "AMZN", "ANET", "ANGO", "AON", "AOS", "APA", "APD", "APH", "APLD", "APP", "APTV", "ARE", "ARM", "ASML", "ASTS", "ASX", "ATKR", "ATO", "AVB", "AVGO", "AVY", "AWK", "AXON", "AXP", "AYI", "AZO", "BA", "BABA", "BAC", "BALL", "BAX", "BBAI", "BBY", "BCRX", "BDX", "BE", "BELFB", "BEN", "BIIB", "BKNG", "BKSY", "BLK", "BMY", "BR", "BRO", "BSX", "BTDR", "BXP", "CAH", "CAMT", "CARR", "CB", "CBRE", "CBZ", "CCEP", "CCJ", "CCOI", "CDE", "CDNS", "CEG", "CHD", "CHKP", "CHRW", "CHTR", "CI", "CIEN", "CIFR", "CINF", "CL", "CLSK", "CLX", "CMCSA", "CMI", "CMS", "CNC", "COF", "COHR", "COHU", "COIN", "CORZ", "COST", "CPRT", "CRCL", "CRDO", "CRL", "CRM", "CRS", "CRWD", "CRWV", "CSCO", "CSGP", "CSR", "CTAS", "CTSH", "CVS", "CVX", "CWST", "CXAI", "CXW", "D", "DAL", "DASH", "DDOG", "DE", "DECK", "DELL", "DG", "DGX", "DHI", "DHR", "DHT", "DIOD", "DIS", "DLR", "DLTR", "DMRC", "DNA", "DOCN", "DOCU", "DOV", "DRI", "DT", "DTE", "DUK", "DVA", "DXC", "DXCM", "DY", "EA", "EBAY", "ECL", "ED", "EFX", "EIX", "ELV", "EME", "EMR", "EOG", "EPAM", "EQIX", "EQR", "ERIE", "ES", "ESE", "ESTC", "ETN", "ETR", "EW", "EXC", "EXPD", "EXR", "EXTR", "FANG", "FAST", "FC", "FDS", "FDX", "FE", "FEIM", "FIG", "FIS", "FISV", "FIX", "FLG", "FLY", "FN", "FORM", "FRMI", "FROG", "FRT", "FSLR", "FTNT", "GD", "GE", "GEV", "GFS", "GILD", "GLOB", "GLW", "GLXY", "GOOGL", "GRMN", "GS", "GTLB", "HD", "HIMS", "HON", "HOOD", "HPE", "HPQ", "HUBB", "HUBS", "HUT", "IBM", "ICHR", "IDXX", "IESC", "ILMN", "INFY", "INOD", "INSM", "INTC", "INTU", "IONQ", "IREN", "IRM", "J", "JCI", "JNJ", "JPM", "KDP", "KEEL", "KLAC", "KO", "LEU", "LII", "LITE", "LLY", "LMT", "LOGI", "LRCX", "LSCC", "MARA", "MCD", "MCHP", "MDB", "MDLZ", "MELI", "META", "MOD", "MPWR", "MRK", "MRVL", "MS", "MSFT", "MSTR", "MTZ", "MU", "NBIS", "NET", "NFLX", "NKE", "NNE", "NOK", "NOV", "NOW", "NRG", "NTAP", "NVDA", "NVMI", "NVO", "NVT", "NVTS", "NXPI", "OKLO", "OKTA", "ON", "ONTO", "ORCL", "ORLY", "OSIS", "OXY", "PANW", "PATH", "PAYX", "PCAR", "PD", "PEG", "PFE", "PINS", "PL", "PLTR", "POWI", "POWL", "PWR", "PYPL", "QCOM", "QLYS", "QRVO", "RBLX", "RDDT", "REGN", "RGTI", "RIOT", "RKLB", "RMBS", "ROK", "ROP", "ROST", "RPD", "RTX", "RXRX", "S", "SBUX", "SHOP", "SMCI", "SMR", "SNAP", "SNDK", "SNOW", "SNPS", "SO", "SOFI", "SOUN", "SPCX", "SPOT", "SPXC", "STRL", "STX", "SWKS", "SYM", "T", "TDC", "TEAM", "TEL", "TEM", "TENB", "TER", "TGT", "TLN", "TMO", "TMUS", "TRI", "TSEM", "TSLA", "TSM", "TT", "TTD", "TTWO", "TWLO", "TXN", "U", "UBER", "UCTT", "UEC", "UMC", "UNH", "VECO", "VEEV", "VRNS", "VRSK", "VRT", "VRTX", "VSH", "VST", "VZ", "WBD", "WDAY", "WDC", "WFC", "WIT", "WMT", "WULF", "XOM", "ZBRA", "ZM", "ZS"]
)
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
    cur.execute(f"SELECT ticker FROM {s.db_schema}.fundamental_universe WHERE tier='ranked'")
    uni = {r[0] for r in cur.fetchall()}
    missing = sorted(uni - seen)
    print(f"UNIVERSE={len(uni)} ON_CALENDAR={len(uni & seen)} MISSING={len(missing)}")
    cur.execute(f"""
        SELECT ticker, max(period_end), count(*)
          FROM {s.db_schema}.fundamental_statement_obs
         WHERE ticker = ANY(%s) AND period_type='quarterly'
      GROUP BY ticker ORDER BY 2 DESC NULLS LAST
    """, (missing,))
    rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    for t in missing:
        pe, n = rows.get(t, (None, 0))
        print(f"  {t:<7} newest_period={pe} rows={n}")
