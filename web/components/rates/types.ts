import type { components } from "@/lib/types";

export type Snapshot = components["schemas"]["RatesSnapshotResponse"];
export type SummaryTile = components["schemas"]["RatesSummaryTile"];
export type SlopeMetric = components["schemas"]["RatesSlopeMetric"];
export type Scorecard = components["schemas"]["RatesScorecard"];
export type Decomposition = NonNullable<Snapshot["decomposition"]>;
export type DecompositionAttribution =
  components["schemas"]["RatesDecompositionAttribution"];
export type Policy = NonNullable<Snapshot["policy"]>;
export type PolicyPathPoint = components["schemas"]["RatesPolicyPathPoint"];
export type Supply = NonNullable<Snapshot["supply"]> & {
  recent_auctions?: SupplyAuction[];
  fiscal?: SummaryTile[];
  supply_read?: string | null;
};
export type SupplyAuction = {
  cusip: string;
  security_type: string;
  security_term: string;
  auction_date: string;
  issue_date?: string | null;
  offering_amount?: number | null;
  high_rate?: number | null;
  bid_to_cover?: number | null;
  direct_bidder_pct?: number | null;
  indirect_bidder_pct?: number | null;
  primary_dealer_pct?: number | null;
  tail_indicator?: string | null;
  source_url?: string | null;
  status?: string;
};
export type Positioning = NonNullable<Snapshot["positioning"]> & {
  details?: PositioningDetail[];
  positioning_read?: string | null;
};
export type PositioningDetail = {
  contract_code: string;
  contract_name: string;
  tenor_bucket: string;
  obs_date?: string | null;
  release_date?: string | null;
  open_interest?: number | null;
  dealer_net?: number | null;
  dealer_net_pct_oi?: number | null;
  asset_mgr_net?: number | null;
  asset_mgr_net_pct_oi?: number | null;
  lev_money_net?: number | null;
  lev_money_net_pct_oi?: number | null;
  source_url?: string | null;
  status?: string;
};
