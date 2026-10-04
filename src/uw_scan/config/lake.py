"""Local parquet lake roots and the retired R2 keys (D6 concern group: lake)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, SecretStr

from uw_scan.config._env import EnvVar


class LakeSettings(BaseModel):
    # Parquet lake root for CBOE vol indices and SPX daily OHLC.
    # Maintained by the peer ``market-data-warehouse`` project. Symbol subdirs
    # are named ``symbol=<TICKER>`` with a ``1d.parquet`` payload inside.

    # Parquet-lake roots are env-overridable so deployments without
    # the user's home-dir layout (containers, CI) can point at their
    # own mount. Blank/unset → fall back to the field-level defaults.
    lake_vol_index_root: Annotated[
        Path, EnvVar("LAKE_VOL_INDEX_ROOT", strip=True, blank_is_default=True)
    ] = Field(
        default=Path.home()
        / "market-warehouse/data-lake/bronze/asset_class=volatility",
        description=(
            "Local parquet lake root for CBOE vol indices and SPX daily OHLC. "
            "Symbol subdirs are named symbol=<TICKER>."
        ),
    )
    # Parquet lake root for equity-asset credit-proxy ETFs (HYG, JNK, LQD),
    # used by the VCG scanner. Same layout as the vol-index lake.
    lake_credit_etf_root: Annotated[
        Path, EnvVar("LAKE_CREDIT_ETF_ROOT", strip=True, blank_is_default=True)
    ] = Field(
        default=Path.home() / "market-warehouse/data-lake/bronze/asset_class=equity",
        description=(
            "Local parquet lake root for credit-proxy ETF daily OHLC "
            "(HYG/JNK/LQD). Symbol subdirs are named symbol=<TICKER>."
        ),
    )
    # Parquet lake root for FX dailies. Same layout as the vol-index lake;
    # `USD<CCY>` holds <CCY> per one USD. Used to translate foreign filers'
    # statements before any valuation anchor is computed — see
    # `fundamentals/fx.py` for why an unconverted band is worse than no band.
    lake_fx_root: Annotated[
        Path, EnvVar("LAKE_FX_ROOT", strip=True, blank_is_default=True)
    ] = Field(
        default=Path.home() / "market-warehouse/data-lake/bronze/asset_class=fx",
        description=(
            "Local parquet lake root for FX daily rates. Symbol subdirs are "
            "named symbol=USD<CCY> and hold <CCY> per one USD."
        ),
    )
    # Root of the whole market-warehouse lake (parent of bronze/silver/gold).
    # Distinct from the two asset-class roots above, which point at specific
    # bronze partitions. Read by reports/vrp_macro_drawdown.py.
    market_warehouse_lake_root: Annotated[
        Path, EnvVar("MARKET_WAREHOUSE_LAKE", strip=True, blank_is_default=True)
    ] = Field(
        default=Path.home() / "market-warehouse" / "data-lake",
        description=(
            "Root of the market-warehouse parquet lake (contains bronze/). "
            "Set MARKET_WAREHOUSE_LAKE=/lake in containers."
        ),
    )
    # Cloudflare R2 parquet lake — primary source for EOD/backfill reads per
    # the 2026-05-25 standing rule (see docs/research/regime/closure-2026-05-24.md
    # §4 and the [[feedback-r2-primary-for-eod-backfill]] memory). All four core
    # fields must be set for R2 reads to engage; if any is None, the resolver
    # falls back to the local mirror at lake_vol_index_root / lake_credit_etf_root.
    # R2_ENDPOINT_OVERRIDE is optional — defaults to
    # https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com.
    r2_account_id: Annotated[
        str | None, EnvVar("R2_ACCOUNT_ID", strip=True, blank_is_default=True)
    ] = None
    r2_access_key_id: Annotated[
        SecretStr | None, EnvVar("R2_ACCESS_KEY_ID", strip=True, blank_is_default=True)
    ] = None
    r2_secret_access_key: Annotated[
        SecretStr | None,
        EnvVar("R2_SECRET_ACCESS_KEY", strip=True, blank_is_default=True),
    ] = None
    r2_bucket: Annotated[
        str | None, EnvVar("R2_BUCKET", strip=True, blank_is_default=True)
    ] = None
    r2_endpoint_override: Annotated[
        str | None, EnvVar("R2_ENDPOINT_OVERRIDE", strip=True, blank_is_default=True)
    ] = None


#: Lake roots with no env var of their own: ``from_env`` puts them UNDER the warehouse
#: root (``market_warehouse_lake_root``), never under $HOME. In a container $HOME is
#: /root and no lake lives there, so a root with no env var of its own silently resolves
#: to a path that does not exist. That is exactly what happened to `lake_fx_root`: it was
#: added after the container migration, never got a `LAKE_FX_ROOT` case, and resolved to
#: /root/market-warehouse/... in production -- so 12 foreign filers were refused for want
#: of an FX series the lake was carrying the whole time. Deriving the fallback means the
#: next root added is correct by default. Bare ``Settings()`` uses the class defaults.
LAKE_ROOT_FALLBACK: dict[str, str] = {
    "lake_vol_index_root": "bronze/asset_class=volatility",
    "lake_credit_etf_root": "bronze/asset_class=equity",
    "lake_fx_root": "bronze/asset_class=fx",
}
