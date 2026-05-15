export const SECTOR_ROWS: { label: string; items: string[] }[] = [
  { label: "Index", items: ["All", "ETF"] },
  {
    label: "AI/Tech",
    items: [
      "M7",
      "Semiconductor",
      "Memory",
      "Optical",
      "NeoCloud",
      "Power",
      "SaaS",
      "Networking",
    ],
  },
  { label: "Thematic", items: ["Crypto", "Fintech", "Space", "Defense"] },
  {
    label: "Defensive",
    items: [
      "Healthcare",
      "Energy",
      "Banks",
      "Consumer",
      "Telecom-Media",
      "Airlines",
    ],
  },
];

export const WATCHLIST_SECTORS = SECTOR_ROWS.flatMap((row) =>
  row.items.filter((item) => item !== "All"),
);
