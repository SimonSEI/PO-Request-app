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
| 4 | `R/04_fetch_fti.R` | Reads FDOT's Access database (needs manual download) |
| 5 | `R/05_traffic_vs_temperature.R` | Real traffic vs the thermometer, 2024 |
| 6 | `R/06_origin_states.R` | IRS migration data → where people really come from |
| 7 | `R/07_origin_charts.R` | The threshold sweep — the robustness check |

Steps 4–7 need two manual downloads (both free, no signup):

- **FDOT FTI database** — <https://www.fdot.gov/statistics/trafficinfo/> → "FTI Database"
  (97 MB zip → 1.55 GB `.mdb`). Needs the 64-bit Microsoft Access ODBC driver.
- **IRS migration** — `countyinflow2223.csv` from
  <https://www.irs.gov/statistics/soi-tax-stats-migration-data-2022-2023>
- **Census county centroids** — `2023_Gaz_counties_national.zip` from
  <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/>

Set the paths at the top of `R/04` and `R/06`.

Charts land in `output/`. Downloads are cached in `data/raw/`, so re-running
step 1 is instant and doesn't re-hammer a free API.

Scripts 08–18 extend the analysis. One more matters for this file:

| Step | File | What it does |
|---|---|---|
| — | `R/20_report_numbers.R` | Rewrites every number table in this README from `output/*.csv` |

Run it after `R/09` and `R/10`. The forecast tables below sit between
`<!-- BEGIN GENERATED: ... -->` markers and are overwritten wholesale, so the
documentation cannot drift from the code again. Prose outside the markers is
yours to edit.

### The interactive dashboard

Run scripts 1–7 first, then launch the app:

- **In RStudio:** open `app.R` and click **Run App** (top-right of the editor)
- **Or:** open `run_app.R` and press Ctrl+Shift+Enter
- **Or from a terminal:** `Rscript run_app.R`

It opens at <http://127.0.0.1:7788>. Stop it with Escape (RStudio) or Ctrl+C.
Everything runs on your machine — no server, no account, no internet needed
once the data is downloaded.

**Seven tabs:**

| Tab | What it shows |
|---|---|
| Window shift | Open/close dates per season, with trend |
| Shape of a year | The average temperature gap through the year |
| **Robustness** | **The most important one** — refits the trend at every threshold |
| Traffic vs temperature | Real 2024 traffic against the thermometer |
| Origin states | Where people actually come from (IRS data) |
| 50 years | Naples traffic growth, 1970–2025 |
| The numbers | The underlying table |

**Three controls**, each one an assumption you can attack:

- **Threshold slider** — the number the whole finding hangs on
- **Weighting** — migrants-sent vs all states equal
- **Origin states** — untick any state and watch everything recompute

---

## Are snowbirds arriving earlier? (`R/11`)

**The road data cannot answer this** — FDOT's daily counts cover 2024 only, and
no newer FTI edition exists. One year cannot show change over time.

So this uses **RSW airport monthly passengers, 1983–2025** (43 seasons) from
Lee County Port Authority. Two scale-free timing measures, because raw autumn
numbers rise whenever the airport grows — and it has, hugely:

- **Autumn share** — of the Oct–Apr season, what fraction arrives Oct–Dec
- **Arrival centroid** — the passenger-weighted average month of the season

### The long-run answer: yes, clearly

| Measure | Change per decade | p |
|---|---|---|
| Autumn share | **+0.91 percentage points** | **< 0.001** |
| Arrival centroid | **−0.039 months earlier** | **< 0.001** |

Over 35 clean seasons, arrivals really have shifted earlier. This is the
strongest, most robust result in the whole project — far better evidenced than
anything the temperature data produced.

### The 2025-26 season: complete, and it leans earlier

The big statistics PDF is only rebuilt each January, so it stops at Dec 2025.
But LCPA publish a **news release every month**, each stating that month's
count. `R/11` pulls those in, which completes the 2025-26 season now rather
than waiting a year:

| Month | Passengers |
|---|---|
| Jan 2026 | 1,063,645 |
| Feb 2026 | 1,190,070 |
| Mar 2026 | 1,521,149 |
| Apr 2026 | 1,152,669 |

**Result for 2025-26:**

| Measure | Value | vs typical | z |
|---|---|---|---|
| Autumn share | **36.4%** | 34.6% | **+1.14** |
| Arrival centroid | **4.31** | — | **−1.16** (earlier) |
| October share | **27.5%** | 25.9% | **+1.55** |

**All three measures point the same way.** 36.4% is the highest autumn share of
any clean season on record. Each is individually short of the conventional
2-SD bar, but they are not independent restatements of luck — they agree, and
they agree with the decades-long trend.

**Verdict: your instinct was right.** The 2025-26 season did run earlier than
normal, by roughly 1 to 1.5 standard deviations depending on the measure.
Suggestive and consistent rather than conclusive.

### Autumn 2025 in isolation

Two measures that need only the autumn months, so they work before a season
completes:

| Autumn | Oct share | Lift vs summer | |
|---|---|---|---|
| 2021 | 27.1% | 1.412 | |
| 2022 | 20.5% | 1.166 | hurricane Ian |
| 2023 | 26.5% | 1.520 | |
| 2024 | 24.4% | 1.487 | Helene + Milton |
| **2025** | **27.5%** | 1.468 | |

**October 2025 was the most front-loaded autumn in the clean record** — 27.5%
of autumn arrivals landed in October, against a typical 25.9%. That is
**z = +1.55**: leaning earlier, but still inside normal year-to-year variation.

Meanwhile the *autumn lift* (1.468 vs typical 1.536, z = −0.86) was slightly
**below** normal. So the autumn wasn't unusually busy overall — but the
arrivals within it came sooner. That is a timing shift, not a volume one,
which is exactly what "people came back sooner" describes.

**Verdict: the theory is supported directionally and strongly over decades,
and weakly for 2025 specifically.** Not proof for one year — z = 1.55 is the
kind of number that turns out to be nothing about a third of the time.

### The trap this nearly fell into

The first run reported the 2019-20 season at **z = +15.9** — apparently the
most dramatic early arrival ever recorded. It was COVID. Autumn 2019 was
perfectly normal; then **April 2020 collapsed from ~1.1m passengers to
53,379**. The autumn *share* exploded because the denominator vanished.

A z-score of +15.9 is not a discovery, it is a broken denominator. It was also
sitting inside the trend fit, inflating it. COVID seasons are now excluded
alongside hurricanes, and both are drawn in their own colour so the exclusions
stay visible rather than quietly dropped.

---

## Next season — actual dates

<!-- BEGIN GENERATED: next-season-dates -->

From `R/10_next_season_dates.R`, run 17 Sep 2026:

| Event | Date | Days away |
|---|---|---|
| **Trough** | **Tue 22 Sep 2026** | 5 |
| **Season starts** | **Tue 17 Nov 2026** | 61 |
| **Peak** | **Tue 09 Mar 2027** | 173 |
| **Season ends** | **Fri 07 May 2027** | 232 |

- **Peak window: 20 Feb – 26 Mar 2027**
- **Trough window: 12 Sep – 1 Oct 2026** (we are inside it now)
- Peak runs **1.12×** an average day, trough **0.85×** — a **24% fall** from
  peak to trough, or a **32% rise** from trough to peak.

<!-- END GENERATED: next-season-dates -->

The 22 Sep 2026 trough is a week away, which makes it the first genuinely
falsifiable claim this project has produced. Worth checking.

---

## Can weather models predict the peak?

Short answer: **no, and it isn't a software problem.**

Deterministic weather forecasting — Google DeepMind's GraphCast/GenCast,
ECMWF, GFS — has a hard skill horizon of roughly **10–15 days**. That is chaos,
not compute. No model beats it, and March is 175 days away.

What *does* run months ahead is a **seasonal** forecast (NOAA CFSv2, ECMWF
SEAS5), predicting slow things like ocean state and El Niño. So rather than
assume, `R/10` measures it: pull the 50-member CFSv2 ensemble for Naples and
compare its spread against 26 years of plain climatology.

**spread ratio = ensemble SD ÷ climatology SD.** Below 1 means the forecast
knows something climatology doesn't.

| Month | Ensemble SD | Climatology SD | Ratio |
|---|---|---|---|
| Sep 2026 | 2.56 | 2.65 | 1.01 |
| Oct 2026 | 3.27 | 3.55 | 0.97 |
| Nov 2026 | 5.34 | 4.32 | **1.28** |
| Dec 2026 | 6.30 | 5.67 | 1.15 |
| Jan 2027 | 6.26 | 6.34 | 1.02 |
| Feb 2027 | 5.92 | 5.83 | 1.04 |
| Mar 2027 | 5.72 | 5.38 | 1.10 |

Beyond 60 days the mean ratio is **1.12** — the ensemble is *wider* than simply
knowing what month it is. It carries no usable information at this range.

**And even a perfect forecast wouldn't help much.** Script 05 showed traffic
lags temperature by ~25 days with r² = 0.44. Temperature explains under half
the daily variation, and with a lag. People move on the **calendar** —
Thanksgiving, Easter, school terms — not the thermometer.

So the harmonic model, which uses no weather forecast at all, is the better
instrument. Adding a weather API here would have looked sophisticated and made
the forecast worse.

---

## The season forecast

`R/09_predict_season.R` fits a **harmonic (Fourier) regression** to 2024 daily
counts — sin/cos pairs at 1–4 cycles per year, plus day-of-week terms, on
log(index) so effects are multiplicative. Intervals come from a
**moving-block bootstrap** (14-day blocks, 600 runs), which preserves the fact
that a busy Tuesday implies a busy Wednesday. Model R² = 0.76.

### Key dates

<!-- BEGIN GENERATED: forecast-key-dates -->

| | Estimate | 90% CI |
|---|---|---|
| **Season starts** | 17 Nov | 10 Nov – 7 Dec |
| **Peak** | 9 Mar | 25 Feb – 21 Mar |
| **Season ends** | 7 May | 1 May – 12 May |
| **Trough** | 22 Sep | 17 Sep – 26 Sep |
| Season length | 171 days | 149 – 180 |

**Practical ranges** (within 1% of the extreme — more honest than a single day,
since the curve is flat at the top):

- **Peak period: 20 Feb – 26 Mar** (35 days)
- **Trough period: 12 Sep – 1 Oct** (20 days)

<!-- END GENERATED: forecast-key-dates -->

### Magnitude

<!-- BEGIN GENERATED: forecast-magnitude -->

| | Estimate | 90% CI |
|---|---|---|
| Peak level | 1.120× average day | 1.103 – 1.143 |
| Trough level | 0.850× average day | 0.830 – 0.866 |
| **Decline from peak** | **24.0%** | 22.2 – 26.3% |
| **Increase from trough** | **31.7%** | 28.6 – 35.6% |

<!-- END GENERATED: forecast-magnitude -->

(The two differ because they use different bases: falling 24% from the peak and
rising 32% from the trough describe the same gap.)

### One county at a time

The forecast above is **Collier only**. It used to average Collier and Lee
stations into a single index and call the result Naples, which is how a
fortnight went missing: pooling moved "season starts" from 17 Nov to 4 Nov and
cut the decline from 24.0% to 18.9%. No new data, just a scope decision.

<!-- BEGIN GENERATED: forecast-by-county -->

| Scope | Stations | Starts | Peak | Ends | Trough | Decline | R² |
|---|---|---|---|---|---|---|---|
| **Collier** (what the forecast reports) | 3 | 17 Nov | 9 Mar | 7 May | 22 Sep | 24.0% | 0.762 |
| Lee | 2 | 17 Oct | 7 Mar | 28 Apr | 23 Jun | 14.3% | 0.777 |
| Pooled (kept only as a warning) | 5 | 4 Nov | 8 Mar | 6 May | 19 Sep | 18.9% | 0.763 |

<!-- END GENERATED: forecast-by-county -->

The two counties are not variations on one season. Collier troughs in
September — the dead month after the tourists and before the snowbirds. Lee
troughs in **June**, and its swing is half as deep. The pooled row is kept in
the table only as a warning; it describes no road in either county.

### By station — the roads are not alike

<!-- BEGIN GENERATED: forecast-by-station -->

| Station | County | Peak | Trough | Starts | Ends | Decline |
|---|---|---|---|---|---|---|
| 0094 (Naples urban) | Collier | 19 Feb | 27 Jun | 28 Oct | 7 May | 27.7% |
| 0270 (Everglades, rural) | Collier | 7 Mar | 30 Sep | 19 Dec | 3 May | 34.1% |
| 0351 | Collier | 22 Mar | 18 Sep | 10 Nov | 28 Apr | 17.1% |
| 0184 (Lee) | Lee | 9 Mar | 9 Sep | 26 Oct | 4 May | 17.3% |
| 0273 (Lee) | Lee | 11 Nov | 22 Jun | 9 Oct | 8 Apr | 16.2% |

<!-- END GENERATED: forecast-by-station -->

Spread of two months in peak timing and a 2× spread in amplitude — wider
than the confidence interval quoted for the county as a whole. A county-wide
number hides a lot; forecast the road you care about.

### The double dip

The fitted curve isn't a simple wave. It falls to a **June low (~0.92)**, rises
again through **July–August (~0.96)**, then drops to the true **September
trough (0.85)**. That mid-summer bump is family holiday traffic; September is
the genuine dead month — after the tourists, before the snowbirds, in the thick
of hurricane season. Station 0094 troughs in June rather than September because
its mix tilts the other way.

### A third researcher degree of freedom

The dashboard exposes the harmonic count as a slider, and it matters:

| Harmonics | R² | "Season starts" |
|---|---|---|
| 1 | 0.708 | **2 Dec** |
| 4 | 0.762 | **17 Nov** |

A 15-day swing from a modelling choice, not from the data. Same lesson as the
temperature threshold: report the number *and* how much it moves when you
choose differently. Four harmonics is defensible — it captures the summer
double dip that one harmonic smooths away — but it is still a choice.

### What these intervals do and do not mean

The model is fitted to **one season**. The confidence intervals say *"how
precisely do we know the shape of 2024"* — **not** *"how much does the season
move from year to year"*, which is unmeasurable here because there is no second
year of daily data.

Treat them as a **floor** on the true forecasting uncertainty. Getting prior-year
FTI editions from FDOT would be the single highest-value next step.

**And the one that was never written down: 2024 was a hurricane year.** `R/11`
lists the 2024 season in `HURRICANE_SEASONS` and excludes it from the airport
trend as too contaminated to measure timing with. `R/09` fits the entire
forecast to that same season and removes only the storm *days*. Removing the
days does not remove the aftermath — anyone whose return was deferred by Milton
in October is still sitting in the autumn ramp, which is exactly the stretch
"season starts" is estimated from. The same season cannot be unusable in one
script and the sole foundation of another. A second year of FTI data is the
only real fix; until then, treat the November date as the softest number here.

For scale, the airport record does bound how much the season moves year to
year: across 36 clean seasons the passenger-weighted centre of the season has
a standard deviation of about **2.3 days** (1.9 after removing the long-run
trend). Seasons are stable. That is reassuring for the peak, and says nothing
about the start date, which monthly airport data cannot resolve.

---

## Where snowbirds actually come from

The original six "northern origin cities" were a guess. `R/06` replaces them
with IRS county-to-county migration records — every household that moved into
Collier County, and where from. 112 origin counties, 9,662 people.

| State | Share | | State | Share |
|---|---|---|---|---|
| Illinois | 13.8% | | Ohio | 4.8% |
| New York | 13.0% | | Michigan | 4.6% |
| Massachusetts | 11.0% | | Connecticut | 4.5% |
| **New Jersey** | **10.8%** | | Minnesota | 3.9% |
| Pennsylvania | 4.9% | | California | 3.5% |

The top 12 states cover 80% of out-of-state arrivals.

**What my guesses got wrong:**

- **New Jersey (10.8%)** — a top-four source, and I had omitted it entirely
- **Cleveland** — Ohio sends only 4.8%, and its migration-weighted centre sits
  in mid-Ohio, nowhere near Cleveland
- **Toronto** — invisible to IRS data (no US tax return), despite Ontario being
  a genuine source of Naples snowbirds

Each state is placed at the **migration-weighted centre of its origin
counties**, so Illinois sits on Chicago, where the migrants are, rather than on
a cornfield in the geometric middle.

Weighting by migrants raises the mean temperature gap from 20.9 °F to 22.1 °F —
a real change, but a small one.

> **The caveat that matters most:** IRS data tracks people who *change their tax
> address*. Classic snowbirds specifically don't — they keep the northern house
> and often the northern domicile, deliberately. So this measures **permanent
> relocation** and we are using it as a proxy for **seasonal movement**. They
> are related but not the same, and that gap is the single biggest weakness in
> this project.

---

## The verdict: the temperature finding does not hold up

`R/07` refits the trend at **every** threshold from 12 °F to 36 °F, under both
weightings, instead of picking one and reporting it.

| Weighting | Thresholds tested | Significant at p<0.05 |
|---|---|---|
| States equal | 25 | **2** |
| Weighted by migrants | 25 | **2** |

Two hits in 25 tests is precisely what chance delivers (25 × 0.05 ≈ 1.25). The
red points in `output/08_threshold_sweep.png` cluster in a narrow band around
21–25 °F and appear nowhere else — and 25 is the number originally chosen by
hand.

Proper migration weighting did **not** rescue the effect. There is a weak lean
toward "later" (19 of 25 thresholds have a positive slope, median ≈ +1.4 to
+1.9 days/decade), but those 25 fits share the same data and are not
independent, so that tally is not a test either.

**Conclusion: the temperature data does not show the migration window shifting.**
The real signal in this project is the ~25-day traffic lag below.

---

## What it found (and why you shouldn't trust it yet)

The headline looked good: the migration window **opens 4.7 days later per
decade** (p = 0.037), while the closing date hasn't moved. Autumn is arriving
later; spring isn't leaving later.

Then the dashboard killed it. Dragging the threshold slider:

| Threshold | Season opens | Evidence |
|---|---|---|
| 15 °F | **−2.2** days/decade | none |
| 25 °F | **+4.7** days/decade | some (p < 0.05) |
| 36 °F | **+1.6** days/decade | none |

The trend is only significant at 25 °F — the value that was picked by hand —
and the **sign flips** across the plausible range. That is not a finding. It is
a coincidence that would have shipped with a confident chart attached.

Two further reasons for caution:

- Three trends were tested and the one that passed is being quoted. Correct for
  that (Bonferroni: 0.05 ÷ 3 = 0.0167) and p = 0.037 doesn't survive either.
- This measures **thermometers, not people**. It shows the thermal *case* for
  migrating has shifted. Whether anyone changed their travel plans is what the
  traffic data is for — which makes the monthly counts essential, not optional.

---

## What the real traffic says (2024)

Script 05 finally measures **people** rather than weather, using FDOT's
hour-by-hour counts from Collier County's continuous stations.

**The season is real.** March is the busiest month at 1.12× a normal day;
September the quietest at 0.83×. Peak is **35% above the trough**. Per station:

| Station | Peak | Low | Swing |
|---|---|---|---|
| 0094 (Naples urban) | 1.23 | 0.92 | 34% |
| 0270 (Everglades, rural) | 1.15 | 0.74 | **55%** |
| 0351 | 1.12 | 0.85 | 32% |

**But people lag the thermometer by about 25 days — at both ends.**

| | Thermometer | Traffic | Lag |
|---|---|---|---|
| Season starts | 16 Oct | 10 Nov | **+25 days** |
| Season ends | 8 Apr | 2 May | **+24 days** |

Correlation is moderate (r = 0.66, r² = 0.44) — temperature explains under half
the day-to-day variation.

A symmetric ~25-day lag at both ends is not what you'd see if people were
responding to weather; they'd arrive as soon as it paid to and leave as soon as
it stopped. It is exactly what you'd see from a **calendar**: come after
Thanksgiving, leave after Easter. The thermometer sets the backdrop; the
diary picks the date.

### The hurricanes nearly ruined this

2024 hit southwest Florida with three storms, and the first run of script 05
reported the quietest stretch of the year as "29 Sep" — a plausible-sounding
late-summer lull. It was **Hurricane Helene**.

The signature is unmistakable once you look at daily values:

| Date | Index | |
|---|---|---|
| 7 Oct | 1.24 | evacuation begins |
| 8 Oct | **1.53** | everyone leaving at once |
| 9 Oct | **0.30** | Milton landfall, roads empty |
| 26 Sep | 0.39 | Helene |
| 4 Aug | 0.54 | Debby |

Removing the storm windows **flipped the autumn result**: traffic went from
appearing to *lead* the thermometer by 11 days to *lagging* it by 25. A storm
looks like a seasonal signal to any code that hasn't been told otherwise.

Two lessons baked into the script: exclude known events explicitly, and report
**monthly medians rather than min/max** — extremes are precisely what a storm,
a sensor fault, or a road closure produce.

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

## Jobber: which clients are snowbirds, and when to resend their quotes

**Part of the Office App.** Admin and office users open the **Snowbirds** card on the Office App dashboard. The Office App's own login and roles decide who gets in; `/snowbirds/clients` hands the clients service a signed 2-minute ticket (HMAC with `SNOWBIRDS_SSO_SECRET`), which becomes a 12-hour session cookie. Technicians and property managers never see the card and are refused if they try the link.

The clients service (`clients/`) connects to Jobber, works out which clients have a home up north, predicts when each one comes back, and schedules each outstanding quote for a resend with 10% off. Automatic sending sits behind an on-page **kill switch** that starts OFF, and only *awaiting response* quotes are ever eligible.

**How it runs.** In Railway (project *po request app*), two services build from this repo with root directory `snowbirds`: the forecast (Dockerfile path `Dockerfile`) and the clients tool (`clients/Dockerfile`). Root directory, Dockerfile path and watch paths are set on each service in Railway. A volume at `/data` on the clients service holds the Jobber tokens, pulled quotes, the property roll, the kill switch and the send history, so they survive redeploys. Every day at 7:00 am Eastern (and on **Refresh now**) it pulls quotes, re-downloads the Collier roll if it is over a month old, and rebuilds the plan. Only the 7am run can send.

**Railway variables.**
- Shared (project level): `SNOWBIRDS_SSO_SECRET`, referenced by both the Office App and the clients service.
- Office App: `SNOWBIRDS_CLIENTS_URL`, `SNOWBIRDS_FORECAST_URL`.
- Clients service: `JOBBER_CLIENT_ID`, `JOBBER_CLIENT_SECRET`, `JOBBER_CALLBACK_URL` (its own address, with trailing slash), `OFFICE_APP_URL`.

**Setup, once:** set the Jobber app's callback URL to the clients service address, open Snowbirds from the Office App, click **Connect Jobber** (a Jobber admin approves), then **Refresh now**.

**How a client counts as a snowbird.** There are two independent checks:
- **Property roll.** The job address has no homestead exemption and the tax mail goes out of state. This is the same test R/08 uses.
- **Billing address.** Their Jobber billing address is outside Florida.

Both checks agree → *confirmed*. Only one → *likely*. A homestead exemption means *year-round resident*, whatever the billing address says. Collier uses `data/raw/collier_int_parcels.csv`. Lee needs the state's free NAL roll saved as `data/raw/lee_nal.csv`; until then, Lee clients are judged on billing address alone.

**When they're back.** If a client has two or more past seasons on file, we use their own habit: the date of their first autumn quote or job. With one season, we take the earlier of that date and the area forecast. With none, the season opening from **their own county's** forecast — Collier
and Lee differ by about a month, so a Fort Myers client is not judged against
Naples' curve. **Resend** 14 days before that. If the date has passed and the season is still on, the plan says send now.

**Who never gets one.** Three hard exclusions, applied when the plan is built
and re-checked by the sender immediately before anything goes out:

- **Businesses**, by Jobber's own `isCompany` flag or a company name on file.
- **HOAs, condo and community associations**, and **landscaping, lawn and
  irrigation firms** — trade contacts and, in several cases, competitors.
  Matched on name patterns as well as the company flag.
- **Management and property-management companies.** In this market a manager
  on the client line almost always means an HOA or a condo board: the manager
  is the community's billing contact, not a homeowner. Matched on the full
  words and the abbreviations (*Mgmt*, *Mgt*), plus *Properties*, *Realty*,
  *Real Estate* and *Residential*.
- **Quotes older than 13 months** (`SNOWBIRD_MAX_QUOTE_AGE_MONTHS`). Past that
  the price and the scope want re-quoting, not discounting. A quote with no
  readable creation date fails this check rather than skipping it.

Over-matching is the deliberate direction: a missed resend costs one discount,
a homeowner offer emailed to a competitor costs more. Nothing is dropped
silently — every held-back quote appears with its reason on the **Held back**
tab and in `excluded_from_plan.csv`.

Some HOAs cannot be spotted from their name at all: a community called
*Autumn Woods* reads exactly like a person's address. For those, add the
client name or id to `do_not_send.csv` beside the Jobber data on the volume.

**Privacy.** Client data lives only on the clients service's Railway volume, behind the Office App login. None of it is in GitHub or in either Docker image, and the public dashboard never sees it. Credentials are Railway variables, never code.

Outputs, on screen and as CSV downloads: the **resend plan** (outstanding snowbird quotes in the order to send them) and **all clients** (every client with the evidence).

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

**`Error: is.character(txt) is not TRUE` in the Shiny app**

A masked function. `jsonlite` also exports `validate()`, and whichever package
loads last wins — so `validate()` was calling `jsonlite::validate()`, which
wants a JSON string, not a Shiny condition. Write `shiny::validate()` in full.

Same root cause as `dplyr::filter()` masking `stats::filter()`. When an error
message makes no sense for the function you think you called, suspect a
collision first — R lists them at startup, in the noise everyone scrolls past.

**`Error in graphics::plot.new: figure margins too large`**

bslib's `fillable = TRUE` (the default) squeezes content to fit the window
height, overriding `plotOutput(height = "460px")`. On first load the height can
briefly be near zero, Shiny renders into that, and the error sticks because
nothing re-triggers the render. Resizing the window appears to "fix" it, which
makes the bug look intermittent.

Set `fillable = FALSE` on `page_sidebar()` to respect explicit heights and let
the page scroll instead.

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
