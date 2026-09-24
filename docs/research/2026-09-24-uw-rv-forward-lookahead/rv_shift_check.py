import numpy as np, pandas as pd, psycopg
import sys
c = psycopg.connect(sys.argv[1] if len(sys.argv) > 1 else "host=127.0.0.1 dbname=option_wizard_local user=chenxi")
for t in ["AAPL","KO","NVDA","SPY"]:
    rows = c.execute("select market_date, price::float, realized_volatility::float from uw_scan.realized_volatility_history where ticker=%s order by market_date", (t,)).fetchall()
    df = pd.DataFrame(rows, columns=["d","p","rv"])
    if df.empty: print(t,"empty"); continue
    base = np.log(df.p).diff().rolling(21).std()*np.sqrt(252)
    res = {k: round((base.shift(-k)-df.rv).abs().mean(),4) for k in [0,1,19,20,21]}
    print(t, len(df), df.d.min(), "last non-null rv", df.loc[df.rv.notna(),'d'].max(), "max d", df.d.max(), res)
