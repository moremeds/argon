export const SECTOR_ROWS: { label: string; items: string[] }[] = [
  { label: "Index", items: ["All", "Beta", "Sector-ETF", "Credit", "Macro"] },
  {
    label: "AI/Tech",
    items: [
      "M7",
      "Foundry",
      "Semi-Logic",
      "Semi-Cap",
      "Memory",
      "DC-Connect",
      "NeoCloud",
      "Power",
      "SaaS",
    ],
  },
  { label: "Thematic", items: ["Crypto", "Fintech", "Space"] },
  {
    label: "Defensive",
    items: ["Healthcare", "Energy", "Banks", "Consumer"],
  },
];

export const WATCHLIST_SECTORS = SECTOR_ROWS.flatMap((row) =>
  row.items.filter((item) => item !== "All"),
);

export const PRIORITY_SECTORS = ["Beta", "M7", "Semi-Logic"] as const;
