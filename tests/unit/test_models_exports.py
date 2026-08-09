import importlib

PUBLIC_MODEL_EXPORTS = [
    "_UwBase",
    "MatrixDirection",
    "MatrixConsistencyTier",
    "VannaConditionalReading",
    "CharmRegime",
    "SkewRegime",
    "FlowFootprintLabel",
    "FlowAlert",
    "IvRankRow",
    "VolStatsRow",
    "RealizedVolRow",
    "TermStructureRow",
    "InterpolatedIvRow",
    "SkewRow",
    "GreekExposureRow",
    "SpotExposureRow",
    "GreeksRow",
    "OiPerStrikeRow",
    "OiChangeRow",
    "MaxPainRow",
    "OptionContractRow",
    "OptionsDailyRow",
    "OptionChainPerStrikeRow",
    "DarkPoolPrint",
    "ShortDataRow",
    "MarketStructure",
    "VolatilityProfile",
    "FlowSnapshot",
    "VRPAssessment",
    "SetupClassification",
    "MagnetCandle",
    "MagnetConeBand",
    "MagnetIvPoint",
    "MagnetLevels",
    "MagnetPivot",
    "MagnetsResponse",
    "MatrixState",
    "MatrixSourceFreshness",
    "CockpitStateResponse",
    "CockpitDealerPoint",
    "CockpitDealerMetrics",
    "VannaSignal",
    "CharmSignal",
    "CockpitDealerResponse",
    "CockpitSkewPoint",
    "CockpitTermPoint",
    "CockpitSurfaceResponse",
    "CockpitFlowAlert",
    "CockpitImPoint",
    "CockpitFlowImResponse",
    "CockpitVrpPoint",
    "CockpitVrpResponse",
    "BulkScreenerRow",
    "EtfInfo",
    "EtfInOutflowRow",
    "ScanTickerResult",
    "ScanReport",
    "MarketAggregates",
    "StrikeGexBucket",
    "GexLevel",
    "MarketStructureLevels",
    "StockHistoryRow",
    "StockHistoryResponse",
    "SingleStockReport",
    "VolHeaderBlock",
    "TermStructureExpiryRow",
    "SmilePoint",
    "SmileExpiryCurve",
    "IvHvPoint",
    "IvHistogramBin",
    "IvPercentileDistribution",
    "IvOfIvPoint",
    "RvCorrPoint",
    "RegimeQuadrantPoint",
    "RegimeQuadrantLatest",
    "RegimeQuadrantBlock",
    "DivergencePoint",
    "VrpDailyPoint",
    "VolatilitySeriesResponse",
    "InsightBadge",
    "TradeInsightsHeader",
    "SourceReconciliationRow",
    "SourceReconciliation",
    "InsightSignalRow",
    "ChainFlowReadRow",
    "TermMoveRow",
    "InsightLeg",
    "CandidateStructure",
    "InsightsSynthesis",
    "TradeInsightsResponse",
    "TradeInsightAiBase",
    "TradeInsightAiDominantRead",
    "TradeInsightAiSnapshotMeta",
    "TradeInsightAiHeadline",
    "TradeInsightAiMetricCard",
    "TradeInsightAiScenarioCard",
    "TradeInsightAiScoreBreakdown",
    "TradeInsightAiHighlight",
    "TradeInsightAiLevel",
    "TradeInsightAiSectionCard",
    "TradeInsightAiSectionCards",
    "TradeInsightAiVrpAssessment",
    "TradeInsightAiPreferredExpression",
    "TradeInsightAiBestExpression",
    "TradeInsightAiConflict",
    "TradeInsightAiRequiredCheck",
    "TradeInsightAiRejectedIdea",
    "TradeInsightAiRendering",
    "TradeInsightAiGuardrails",
    "TradeInsightAiOutcome",
    "TradeInsightAiAnalysisRequest",
    "TradeInsightAiAnalysisResponse",
    "TradeFramework",
    "TradeFrameworkHeader",
    "TradeFrameworkThreeAxis",
    "TradeFrameworkDirection",
    "TradeFrameworkVega",
    "TradeFrameworkAsymmetry",
    "TradeFrameworkGamma",
    "TradeFrameworkCatalyst",
    "TradeFrameworkConviction",
    "TradeFrameworkFactor",
    "TradeFrameworkConfluence",
    "TradeFrameworkSignal",
    "TradeFrameworkPitfall",
    "TradeFrameworkCandidate",
    "TradeFrameworkBestSetup",
    "TradeFrameworkWhatChanges",
    "PostureChipState",
    "GoldGaugeState",
    "GoldHistoryPoint",
    "GoldCbCountryHistory",
    "GoldSpotTile",
    "GoldStructuralPostureModel",
    "GoldTwoForceText",
    "GoldCyclicalPostureModel",
    "GoldValuationPostureModel",
    "GoldInputProvenance",
    "GoldDataFreshnessSource",
    "GoldDecompositionRow",
    "GoldCorrelationPoint",
    "GoldCorrelationBand",
    "GoldCorrelationHistory",
    "GoldStateResponse",
    "GoldGaugeTimeSeriesPoint",
    "GoldGaugeResponse",
    "GoldInputSeriesPoint",
    "GoldInputSeriesResponse",
    "GoldLensResponse",
]


def test_uw_scan_models_keeps_public_imports():
    models = importlib.import_module("uw_scan.models")

    missing = [name for name in PUBLIC_MODEL_EXPORTS if not hasattr(models, name)]

    assert missing == []

    if hasattr(models, "__all__"):
        assert set(PUBLIC_MODEL_EXPORTS) <= set(models.__all__)


def test_new_exposure_models_exported():
    from uw_scan import models

    assert "StrikeExposureRow" in models.__all__
    assert "ExposuresSummaryRow" in models.__all__
    # _preserve_public_module rewrites __module__ to "uw_scan.models" for
    # contract identity (see src/uw_scan/models/_base.py). Asserting the
    # public module is what protects the OpenAPI component name from
    # accidentally drifting back to the implementation module.
    assert models.StrikeExposureRow.__module__ == "uw_scan.models"
    assert models.ExposuresSummaryRow.__module__ == "uw_scan.models"


def test_new_skew_structure_models_exported():
    from uw_scan import models

    assert "SkewStructureLeg" in models.__all__
    assert "SkewStructureDetail" in models.__all__
    # _preserve_public_module rewrites __module__ so OpenAPI component names stay stable.
    assert models.SkewStructureLeg.__module__ == "uw_scan.models"
    assert models.SkewStructureDetail.__module__ == "uw_scan.models"
