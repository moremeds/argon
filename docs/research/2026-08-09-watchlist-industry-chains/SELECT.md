# Watchlist extension — 五层蛋糕 industry-chain candidates

Generated, do not hand-edit the tables — edit `TAXONOMY` in
`scripts/research/watchlist_chain_candidates.py` and re-run:

```
UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python \
  scripts/research/watchlist_chain_candidates.py \
  --have  docs/research/2026-08-09-watchlist-industry-chains/current_watchlist.csv \
  --out   docs/research/2026-08-09-watchlist-industry-chains/candidates.csv \
  --doc   docs/research/2026-08-09-watchlist-industry-chains/SELECT.md \
  --final docs/research/2026-08-09-watchlist-industry-chains/FINAL.md \
  --hot   docs/research/2026-08-09-watchlist-industry-chains/hot.csv
```

Tick `[x]` to add. **Only NEW tickers appear here** — the 114 already on the
watchlist are shown per chain as `have:` context and are never re-categorised.

- **Tier A** — option OI ≥ 200k. Real chain, argon can compute GEX/skew/VRP.
- **Tier B** — OI 50k–200k. Usable, thinner surface.
- **Tier C** — OI < 50k. Listed for completeness; not recommended.

Budget: measured ~240 UW calls/day per watchlist ticker.
Weekday burn 2026-08-03..07 was 63–65k against the 120k account cap, splitting
**live 33.6k / 80k ceiling** but **research 22.6k / 30k ceiling** — the research
pool is the binding constraint (only ~7.4k headroom), not the account cap. A new
watchlist ticker bills BOTH pools (full_scan is live; surface/GEX capture and the
gap healer are research), so research runs out first.

Rejected by the UW screener (delisted / acquired / uncovered): CFLT, CYBR, JNPR, PSTG.

### L1 芯片与系统层 · Computer/GPU

`have (3):` AMD ARM NVDA

*Tier A*
- [ ] **SMCI** · 19B mcap · OI 2,420k · Super Micro Computer Inc
- [ ] **DELL** · 147B mcap · OI 684k · Dell Technologies Inc
- [ ] **HPE** · 70B mcap · OI 589k · Hewlett Packard Enterprise Co
- [ ] **HPQ** · 27B mcap · OI 470k · Hp Inc

### L1 芯片与系统层 · Semi-Logic/ASIC

`have (5):` ARM AVGO MRVL QCOM TXN

*Tier A*
- [ ] **MCHP** · 46B mcap · OI 501k · Microchip Technology Inc

*Tier B*
- [ ] **NXPI** · 60B mcap · OI 129k · Nxp Semiconductors Nv
- [ ] **SWKS** · 11B mcap · OI 126k · Skyworks Solutions Inc
- [ ] **RMBS** · 11B mcap · OI 57k · Rambus Inc

*Tier C*
- [ ] **LSCC** · 18B mcap · OI 32k · Lattice Semiconductor Corp
- [ ] **QRVO** · 9B mcap · OI 30k · Qorvo Inc
- [ ] **SLAB** · 7B mcap · OI 26k · Silicon Laboratories Inc
- [ ] **ALGM** · 8B mcap · OI 25k · Allegro Microsystems Inc

### L1 芯片与系统层 · Foundry

`have (3):` INTC TSEM TSM

*Tier A*
- [ ] **UMC** · 47B mcap · OI 219k · United Microelectronics Corp

*Tier B*
- [ ] **ASX** · 83B mcap · OI 134k · Ase Technology Holding Co Ltd
- [ ] **GFS** · 30B mcap · OI 119k · Globalfoundries Inc

### L1 芯片与系统层 · Semi-Cap/EDA

`have (8):` AMAT ARM ASML CDNS KLAC LRCX SNPS TER

*Tier B*
- [ ] **AMKR** · 14B mcap · OI 157k · Amkor Technology Inc

*Tier C*
- [ ] **UCTT** · 4B mcap · OI 27k · Ultra Clean Holdings Inc
- [ ] **FORM** · 9B mcap · OI 22k · Formfactor Inc
- [ ] **CAMT** · 7B mcap · OI 21k · Camtek Ltd
- [ ] **ONTO** · 15B mcap · OI 20k · Onto Innovation Inc
- [ ] **COHU** · 3B mcap · OI 19k · Cohu Inc
- [ ] **AEIS** · 13B mcap · OI 15k · Advanced Energy Industries Inc
- [ ] **NVMI** · 12B mcap · OI 14k · Nova Ltd
- [ ] **ICHR** · 3B mcap · OI 14k · Ichor Holdings Ltd
- [ ] **ACLS** · 4B mcap · OI 11k · Axcelis Technologies Inc
- [ ] **VECO** · 3B mcap · OI 11k · Veeco Instruments Inc

### L1 芯片与系统层 · Memory/Storage

`have (3):` MU SNDK WDC

*Tier A*
- [ ] **STX** · 184B mcap · OI 284k · Seagate Technology Holdings Plc

*Tier B*
- [ ] **NTAP** · 37B mcap · OI 51k · Netapp Inc

### L1 芯片与系统层 · Analog/Power-Semi

`have (0):` — none —

*Tier A*
- [ ] **ON** · 32B mcap · OI 338k · On Semiconductor Corp

*Tier B*
- [ ] **VSH** · 5B mcap · OI 119k · Vishay Intertechnology Inc
- [ ] **ADI** · 190B mcap · OI 105k · Analog Devices Inc

*Tier C*
- [ ] **MPWR** · 69B mcap · OI 17k · Monolithic Power Systems Inc
- [ ] **POWI** · 4B mcap · OI 9k · Power Integrations Inc
- [ ] **DIOD** · 5B mcap · OI 3k · Diodes Inc

### L2 云与数据平台层 · Cloud/Hyperscaler

`have (5):` AMZN GOOGL IBM MSFT ORCL

*Tier A*
- [ ] **BABA** · 30B mcap · OI 2,070k · Alibaba Group Holding Ltd

### L2 云与数据平台层 · AI-Cloud/NeoCloud

`have (4):` CRWV HUT IREN NBIS

*Tier A*
- [ ] **WULF** · 9B mcap · OI 2,636k · Terawulf Inc
- [ ] **CORZ** · 7B mcap · OI 1,616k · Core Scientific Inc
- [ ] **CIFR** · 7B mcap · OI 1,501k · Cipher Mining Inc
- [ ] **CLSK** · 3B mcap · OI 837k · Cleanspark Inc
- [ ] **APLD** · 9B mcap · OI 753k · Applied Digital Corp
- [ ] **BTDR** · 3B mcap · OI 530k · Bitdeer Technologies Group
- [ ] **GLXY** · 4B mcap · OI 446k · Galaxy Digital Inc.

### L2 云与数据平台层 · Data-Platform

`have (2):` PLTR SNOW

*Tier A*
- [ ] **DDOG** · 78B mcap · OI 307k · Datadog Inc
- [ ] **MDB** · 32B mcap · OI 219k · Mongodb Inc

*Tier B*
- [ ] **DOCN** · 15B mcap · OI 173k · Digitalocean Holdings Inc
- [ ] **ESTC** · 8B mcap · OI 60k · Elastic Nv

*Tier C*
- [ ] **TDC** · 3B mcap · OI 19k · Teradata Corp

### L2 云与数据平台层 · Cybersecurity

`have (3):` CRWD NET PANW

*Tier A*
- [ ] **S** · 7B mcap · OI 283k · Sentinelone Inc
- [ ] **ZS** · 27B mcap · OI 237k · Zscaler Inc

*Tier B*
- [ ] **OKTA** · 25B mcap · OI 198k · Okta Inc
- [ ] **FTNT** · 117B mcap · OI 184k · Fortinet Inc
- [ ] **CHKP** · 13B mcap · OI 72k · Check Point Software Technologies 

*Tier C*
- [ ] **RPD** · 1B mcap · OI 45k · Rapid7 Inc
- [ ] **VRNS** · 5B mcap · OI 41k · Varonis Systems Inc
- [ ] **TENB** · 4B mcap · OI 31k · Tenable Holdings Inc
- [ ] **QLYS** · 6B mcap · OI 12k · Qualys Inc

### L3 数据中心基础设施层 · Networking/Optical

`have (9):` AAOI ALAB ANET COHR CRDO FN GLW LITE NOK

*Tier A*
- [ ] **CSCO** · 479B mcap · OI 919k · Cisco Systems Inc

*Tier B*
- [ ] **APH** · 209B mcap · OI 143k · Amphenol Corp
- [ ] **CIEN** · 58B mcap · OI 94k · Ciena Corp

*Tier C*
- [ ] **TEL** · 63B mcap · OI 35k · Te Connectivity Ltd
- [ ] **EXTR** · 3B mcap · OI 10k · Extreme Networks Inc

### L3 数据中心基础设施层 · Power/Electrical

`have (0):` — none —

*Tier A*
- [ ] **VRT** · 105B mcap · OI 495k · Vertiv Holdings Co
- [ ] **GEV** · 264B mcap · OI 233k · Ge Vernova

*Tier B*
- [ ] **ETN** · 174B mcap · OI 105k · Eaton Corp Plc

*Tier C*
- [ ] **PWR** · 101B mcap · OI 48k · Quanta Services Inc
- [ ] **POWL** · 8B mcap · OI 34k · Powell Industries Inc
- [ ] **NVT** · 27B mcap · OI 30k · Nvent Electric Plc
- [ ] **HUBB** · 27B mcap · OI 18k · Hubbell Inc
- [ ] **ATKR** · 3B mcap · OI 10k · Atkore Inc
- [ ] **AYI** · 11B mcap · OI 2k · Acuity Brands Inc

### L3 数据中心基础设施层 · Generation/Nuclear

`have (2):` BE OKLO

*Tier A*
- [ ] **SMR** · 4B mcap · OI 568k · Nuscale Power Corp
- [ ] **VST** · 47B mcap · OI 566k · Vistra Corp
- [ ] **CCJ** · 42B mcap · OI 428k · Cameco Corp
- [ ] **CEG** · 96B mcap · OI 229k · Constellation Energy Corp
- [ ] **UEC** · 6B mcap · OI 228k · Uranium Energy Corp

*Tier B*
- [ ] **NRG** · 25B mcap · OI 175k · Nrg Energy Inc
- [ ] **SO** · 104B mcap · OI 115k · Southern Co
- [ ] **TLN** · 17B mcap · OI 105k · Talen Energy
- [ ] **NNE** · 1B mcap · OI 93k · Nano Nuclear Energy Inc
- [ ] **D** · 59B mcap · OI 86k · Dominion Energy Inc

*Tier C*
- [ ] **LEU** · 4B mcap · OI 45k · Centrus Energy Corp
- [ ] **PEG** · 38B mcap · OI 20k · Public Service Enterprise Group In

### L3 数据中心基础设施层 · Cooling/Thermal

`have (0):` — none —

*Tier B*
- [ ] **CARR** · 53B mcap · OI 128k · Carrier Global Corp
- [ ] **JCI** · 92B mcap · OI 96k · Johnson Controls International Plc

*Tier C*
- [ ] **MOD** · 10B mcap · OI 34k · Modine Manufacturing Co
- [ ] **TT** · 106B mcap · OI 16k · Trane Technologies Plc
- [ ] **AAON** · 8B mcap · OI 6k · Aaon Inc
- [ ] **SPXC** · 11B mcap · OI 3k · Spx Technologies Inc
- [ ] **LII** · 15B mcap · OI 1k · Lennox International Inc

### L3 数据中心基础设施层 · DC-REIT/Colo

`have (0):` — none —

*Tier B*
- [ ] **IRM** · 36B mcap · OI 64k · Iron Mountain Inc

*Tier C*
- [ ] **AMT** · 80B mcap · OI 50k · American Tower Corp
- [ ] **DLR** · 72B mcap · OI 41k · Digital Realty Trust Inc
- [ ] **EQIX** · 103B mcap · OI 24k · Equinix Inc

### L3 数据中心基础设施层 · EPC/Construction

`have (0):` — none —

*Tier C*
- [ ] **MTZ** · 22B mcap · OI 38k · Mastec Inc
- [ ] **FIX** · 60B mcap · OI 17k · Comfort Systems Usa Inc
- [ ] **STRL** · 17B mcap · OI 16k · Sterling Infrastructure Inc
- [ ] **DY** · 12B mcap · OI 10k · Dycom Industries Inc
- [ ] **ACM** · 10B mcap · OI 10k · Aecom
- [ ] **EME** · 36B mcap · OI 6k · Emcor Group Inc
- [ ] **IESC** · 15B mcap · OI 5k · Ies Holdings Inc
- [ ] **J** · 17B mcap · OI 5k · Jacobs Solutions Inc

### L4 应用与终端层 · Software/SaaS

`have (1):` CRM

*Tier A*
- [ ] **NOW** · 129B mcap · OI 1,431k · Servicenow Inc
- [ ] **SHOP** · 183B mcap · OI 875k · Shopify Inc
- [ ] **ADBE** · 105B mcap · OI 697k · Adobe Inc
- [ ] **ZM** · 28B mcap · OI 325k · Zoom Video Communications Inc

*Tier B*
- [ ] **TEAM** · 24B mcap · OI 190k · Atlassian Corp
- [ ] **INTU** · 89B mcap · OI 179k · Intuit Inc
- [ ] **WDAY** · 36B mcap · OI 169k · Workday Inc
- [ ] **DOCU** · 12B mcap · OI 152k · Docusign Inc
- [ ] **TWLO** · 37B mcap · OI 97k · Twilio Inc
- [ ] **HUBS** · 10B mcap · OI 63k · Hubspot Inc

*Tier C*
- [ ] **VEEV** · 37B mcap · OI 42k · Veeva Systems Inc

### L4 应用与终端层 · AI-App/Consumer-Net

`have (1):` APP

*Tier A*
- [ ] **SNAP** · 8B mcap · OI 1,517k · Snap Inc
- [ ] **TTD** · 6B mcap · OI 940k · Trade Desk Inc
- [ ] **U** · 19B mcap · OI 610k · Unity Software Inc
- [ ] **RDDT** · 24B mcap · OI 555k · Reddit Inc
- [ ] **RBLX** · 25B mcap · OI 425k · Roblox Corp
- [ ] **PINS** · 12B mcap · OI 363k · Pinterest Inc
- [ ] **ABNB** · 75B mcap · OI 240k · Airbnb Inc
- [ ] **DASH** · 88B mcap · OI 218k · Doordash Inc

*Tier B*
- [ ] **SPOT** · 100B mcap · OI 171k · Spotify Technology Sa

### L4 应用与终端层 · Robotics/Automation

`have (1):` ISRG

*Tier B*
- [ ] **SYM** · 5B mcap · OI 82k · Symbotic Inc
- [ ] **EMR** · 88B mcap · OI 66k · Emerson Electric Co

*Tier C*
- [ ] **HON** · 78B mcap · OI 40k · Honeywell International Inc
- [ ] **ROK** · 49B mcap · OI 23k · Rockwell Automation Inc
- [ ] **ZBRA** · 18B mcap · OI 14k · Zebra Technologies Corp
- [ ] **OSIS** · 4B mcap · OI 6k · Osi Systems Inc

### L4 应用与终端层 · Healthcare-AI/LS-Tools

`have (0):` — none —

*Tier A*
- [ ] **RXRX** · 2B mcap · OI 347k · Recursion Pharmaceuticals Inc
- [ ] **TEM** · 9B mcap · OI 335k · Tempus Ai Inc

*Tier B*
- [ ] **DHR** · 144B mcap · OI 81k · Danaher Corp
- [ ] **TMO** · 220B mcap · OI 55k · Thermo Fisher Scientific Inc

*Tier C*
- [ ] **A** · 41B mcap · OI 24k · Agilent Technologies Inc
- [ ] **ILMN** · 28B mcap · OI 18k · Illumina Inc
- [ ] **DNA** · 0B mcap · OI 17k · Ginkgo Bioworks Holdings Inc

### L4 应用与终端层 · Devices/Endpoint

`have (2):` AAPL TSLA

*Tier B*
- [ ] **SONY** · 139B mcap · OI 136k · Sony Group Corp

*Tier C*
- [ ] **LOGI** · 15B mcap · OI 29k · Logitech International Sa
- [ ] **GRMN** · 60B mcap · OI 13k · Garmin Ltd

### X 跨层标签 · M7

`have (7):` AAPL AMZN GOOGL META MSFT NVDA TSLA

### L5 模型与工具层 · Foundation-Model-Proxy

`have (5):` AMZN GOOGL META MSFT NVDA

### L5 模型与工具层 · AI-Native-Software

`have (0):` — none —

*Tier A*
- [ ] **BBAI** · 2B mcap · OI 741k · Bigbearai Holdings Inc
- [ ] **SOUN** · 3B mcap · OI 739k · Soundhound Ai Inc
- [ ] **PATH** · 7B mcap · OI 725k · Uipath Inc
- [ ] **AI** · 2B mcap · OI 278k · C3Ai Inc

*Tier B*
- [ ] **INOD** · 2B mcap · OI 70k · Innodata Inc

*Tier C*
- [ ] **CXAI** · 0B mcap · OI 25k · Cxapp Inc

### L5 模型与工具层 · DevTools/Observability

`have (0):` — none —

*Tier A*
- [ ] **DDOG** · 78B mcap · OI 307k · Datadog Inc
- [ ] **GTLB** · 7B mcap · OI 219k · Gitlab Inc

*Tier C*
- [ ] **DT** · 14B mcap · OI 49k · Dynatrace Inc
- [ ] **FROG** · 11B mcap · OI 46k · Jfrog Ltd
- [ ] **PD** · 1B mcap · OI 21k · Pagerduty Inc

### L5 模型与工具层 · IT-Services/Integration

`have (0):` — none —

*Tier A*
- [ ] **INFY** · 51B mcap · OI 416k · Infosys Ltd
- [ ] **ACN** · 117B mcap · OI 250k · Accenture Plc

*Tier B*
- [ ] **CTSH** · 26B mcap · OI 100k · Cognizant Technology Solutions Cor

*Tier C*
- [ ] **DXC** · 2B mcap · OI 21k · Dxc Technology Co
- [ ] **GLOB** · 2B mcap · OI 20k · Globant Sa
- [ ] **EPAM** · 5B mcap · OI 18k · Epam Systems Inc
- [ ] **WIT** · 21B mcap · OI 11k · Wipro Ltd

