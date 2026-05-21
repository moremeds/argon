# 01 — Paper metadata

## Citation (published)

> Goyal, A., & Saretto, A. (2025). Can Equity Option Returns Be Explained by a Factor Model? IPCA Says Yes. *The Review of Financial Studies*, **38**(6), 1783–1821. <https://doi.org/10.1093/rfs/hhae087>

- **Editor:** Ralph Koijen
- **Received:** December 12, 2022
- **Editorial decision:** July 17, 2024
- **Advance access:** December 6, 2024
- **Print issue:** June 2025
- **License:** CC BY-NC-ND 4.0 (open access, attribution, no derivatives, non-commercial)
- **Internet Appendix:** Available on the OUP supplementary-data page; contains tables IA1–IA5 and figures IA1–IA4 (robustness for delta-hedged puts, straddles, monthly returns, OOS time-series detail, restricted-set figures).

## SSRN working-paper record

- **SSRN id:** [4194384](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4194384)
- **First posted:** ~2022 (paired with the December 2022 RFS submission)
- **Most recent revision** (per PDF metadata): May 6, 2025 (post-acceptance camera-ready), pdfTeX 1.40.26 + iTextSharp 4.1.6
- **Local copy:** [`_references/goyal-saretto-2024.pdf`](_references/goyal-saretto-2024.pdf) — RFS-version, 39 pages, 1.4 MB

## Authors and affiliations

- **Amit Goyal** — Swiss Finance Institute at the University of Lausanne, Switzerland (corresponding: amit.goyal@unil.ch). Personal page: <https://sites.google.com/view/agoyal145>
- **Alessio Saretto** — Federal Reserve Bank of Dallas, United States

> "The views expressed in this paper do not necessarily reflect those of the Federal Reserve System, the Federal Reserve Bank of Dallas or its staff."

## JEL codes

G11, G12, G13

## Abstract (verbatim, p.1783)

> A number of delta-hedged equity option strategies exhibit very large average returns. We show that much of the profitability of these strategies can be explained by an IPCA factor model. The economic magnitude of the return-adjustment produced by IPCA is impressive: even before transaction costs, the average IPCA alpha of 46 long-short trading strategies constructed on previously discovered signals, is close to zero and contrasts with average realized returns of over 80 basis points per month. Our IPCA model can be used as a benchmark for assessing the performance of other option portfolios.

## Acknowledgements (relevant)

> "We thank Kevin Aretz, Andreas Fuster, and Bryan Kelly, as well as participants at the 2022 Virtual Derivative Workshop, 2022 Frontiers of Factor Investing Conference at Lancaster University, and 2024 Liverpool Workshop on Options Markets for valuable comments and suggestions. We thank Seth Pruitt for providing his code." (p.1783)

> "We thank Seth Pruitt for providing code for IPCA estimation on his website." (p.1794, fn. 8)

So the IPCA estimation in this paper uses **Seth Pruitt's published IPCA code** (the same canonical implementation behind Kelly-Pruitt-Su 2019). This is important for any replication effort — we should fetch the same code rather than re-implement IPCA from the equations.

## Editorial-decision-to-publication timeline

- Dec 12, 2022: received
- Jul 17, 2024: editorial decision (accept)
- Dec 6, 2024: advance access online
- Jun 2025: RFS print issue 38(6)

**Sample period in the paper: January 1996 — December 2022.** The 2 years between data-end and publication mean nothing post-2022 has been re-evaluated; the IPCA factors and Γ matrix are all in-sample-up-to-2022. Any out-of-sample test on 2023–2026 data is novel research.

## Related-citation-network anchors

The paper sits inside a tight literature web — these are the cites a replicator most needs:

- **Kelly, Pruitt & Su (2019)**, "Characteristics are covariances: A unified model of risk and return," *JFE* 134:501–24 — the IPCA method paper.
- **Kelly, Palhares & Pruitt (2023)**, "Modeling corporate bond returns," *J. Finance* 78:1967–2008 — direct template for the option application.
- **Büchner & Kelly (2022)**, "A factor model for option returns," *JFE* 143:1140–61 — IPCA on *index* options; the prior work this paper distinguishes itself from.
- **Goyal & Saretto (2009)**, "Cross-section of option returns and volatility," *JFE* 94:310–26 — the original RV−IV-strategy paper by the same first author.
- **Muravyev & Pearson (2020)**, "Option trading costs are lower than you think," *RFS* 33:4973–5014 — basis for the 30% ESPR/QSPR transaction-cost rule.
- **Benjamini & Hochberg (1995)** — used for 5% FDR multiple-hypothesis correction (MHT threshold *t* = 2.25 for raw returns, 2.44 for net-of-cost; 2.60 in Table 3 for IPCA alphas).
- **Zhan, Han, Cao & Tong (2022)**, *RFS* 35:1394–1442 — provides the 10 stock-level characteristics used as the "ex-post-only" robustness check (§5.2.3, Table 6).
