# The Naples Snowbird Project

**Question:** Over the last 25 years, have snowbirds been arriving in Naples later
and leaving earlier — and does that track the temperature?

Naples, Florida roughly doubles in population each winter. That surge is one of the
strongest seasonal signals in US traffic data. This project measures it.

---

## The core idea

Nobody moves south because Naples got warm. They move because **Cleveland got cold**.

So the driver isn't Naples temperature — it's the **gap** between Naples and the
places snowbirds actually come from (Ohio, Michigan, Illinois, New York,
Massachusetts, Ontario). We define:

```
gap = Naples temp  -  average temp in the six northern origin cities
```

When the gap is wide, the trip is worth making. When it closes, people go home.
Each year has a **migration window** with an opening date and a closing date.

The interesting part: if northern winters are warming *faster* than Florida
summers, that window should be **narrowing** — and the snowbird season with it.
Then we check whether real traffic agrees, or whether people just move on the
calendar (Thanksgiving, Easter) regardless of the thermometer.

---

## Running it

**Order matters.** Each script writes files the next one reads.

| Step | File | What it does |
|---|---|---|
| 0 | `setup_run_me_first.R` | Installs the R packages. Run once. |
| 1 | `R/01_fetch_weather.R` | Downloads daily temps, 7 cities, 2000–2026 |
| 2 | `R/02_fetch_traffic.R` | Downloads Collier County traffic counts from FDOT |
| 3 | `R/03_migration_window.R` | The analysis + three charts |

Charts land in `output/`. Downloads are cached in `data/raw/`, so re-running
step 1 is instant and doesn't re-hammer a free API.

---

## Data sources (all free, no API keys)

**Temperature — [Open-Meteo Historical API](https://open-meteo.com/en/docs/historical-weather-api)**
Daily temps back to 1940, anywhere on earth. No signup. Verified working.

**Traffic — [FDOT Florida Traffic Online](https://gis.fdot.gov/arcgis/rest/services/FTO/fto_PROD/MapServer)**
The ArcGIS REST service behind FDOT's public traffic map. We query it directly.
Verified working. Two useful layers:

- **Layer 1** — the 7 continuous count stations in Collier County. These are
  machines embedded in the road counting cars 24/7/365. The big one (AADT
  116,388) is I-75 at Naples.
- **Layer 7** — AADT for every road segment, **2021–2025**.

> **Gotcha that cost me twenty minutes:** FDOT county names are Title Case.
> `COUNTY='Collier'` returns 7 stations. `COUNTY='COLLIER'` returns **zero rows
> and no error message**. Silent empty results are the worst kind of bug.

---

## The honest limitation

**AADT is an *annual average*.** It deliberately flattens the seasonal swing —
the exact thing we're trying to measure. It tells us how Naples traffic is
*growing* year over year. It cannot tell us *when* in the year people arrive.

For the within-year timing we need **monthly or weekly counts**. Status of each
route I checked:

| Source | Verdict |
|---|---|
| FDOT AADT (ArcGIS) | ✅ Works. 2021–2025, annual only |
| FDOT Peak Season Factor reports | ⚠️ Weekly curves, but only **2024 and 2025** published |
| Collier County traffic count PDFs (2015–2025) | ❌ Server blocks automated download (Akamai) |
| FDOT **FTI database** (`fti_2025.zip`, 97 MB Access `.mdb`) | 🔑 **The real prize** — needs one manual browser download. This machine already has the 64-bit Access ODBC driver, so R can read it directly. |

The FTI database is the unlock for deep monthly history. That's phase 2.

---

## Project layout

```
Coding in R/
├── setup_run_me_first.R
├── R/
│   ├── 01_fetch_weather.R
│   ├── 02_fetch_traffic.R
│   └── 03_migration_window.R
├── data/
│   ├── raw/              cached API downloads
│   └── *.csv             cleaned, combined data
└── output/               charts and results
```

---

## Troubleshooting

**`'lib = "C:/Program Files/R/R-4.6.1/library"' is not writable`**

Windows blocks writes to `Program Files` without admin rights. Don't run R as
administrator to get around it — use a personal library in your own user folder
instead. `setup_run_me_first.R` already does this:

```r
user_lib <- Sys.getenv("R_LIBS_USER")
dir.create(user_lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(user_lib)
```

Once that folder exists, R finds it automatically in every future session.

---

## Things to argue with

Good analysis invites attack. Some deliberate weak points to go after:

- **`THRESHOLD <- 25`** in script 03 is a judgement call, not a fact. Change it
  to 20 or 30 and re-run. If the conclusion flips, the conclusion was never real.
- **The six origin cities** are my guess at where Naples snowbirds come from.
  Naples skews wealthier and more Midwestern than Florida generally. Swap the
  city list and see what moves.
- **2020–2021 is contaminated.** COVID scrambled travel completely. Any trend
  line through those years is partly measuring a pandemic, not a climate.
