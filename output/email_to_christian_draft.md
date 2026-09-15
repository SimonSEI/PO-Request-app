# Draft email — Christian

Adjust the greeting, the ask at the end, and anything that assumes context he
may not have. Two versions: a short one most people will actually read, and a
longer one if he wants the substance.

---

## Short version

**Subject:** Naples season forecast — trough this week, peak 8 March

Christian,

I've built a model that predicts when the snowbird season in Collier and Lee
County starts, peaks and ends. Sharing it because the dates are specific enough
to plan against.

**The forecast for 2026–27:**

- Traffic bottoms out **19 September** (this week)
- Season opens **4 November**
- Peak **8 March 2027** — though the top is flat from 20 Feb to 26 Mar, so treat
  it as a five-week window rather than a day
- Peak runs about **23% above** the September trough

It's built from FDOT's road-counter data — actual machines in the road counting
vehicles — going back to 1970, with hour-by-hour counts for 2024. The seasonal
shape comes from a harmonic model; the confidence intervals from a bootstrap
that accounts for traffic being sticky day to day.

Two things worth knowing before you lean on it:

1. The seasonal shape is fitted to **one year** of daily counts, because FDOT
   overwrite the detailed tables each year rather than accumulating them. So the
   intervals tell you how well we know 2024, not how much the season moves
   between years. Getting prior-year editions from FDOT is the single biggest
   improvement available.
2. The most interesting finding is that **people move on the calendar, not the
   weather**. Traffic lags temperature by about 25 days at both ends of the
   season — they arrive after Thanksgiving and leave after Easter, regardless of
   what the thermometer is doing. Which means forecasting this from a weather
   forecast doesn't work, and I tested that rather than assuming it.

Full write-up here: [LINK]

Happy to walk through it if useful.

Simon

---

## Longer version

**Subject:** Snowbird season forecast — what it predicts and how far I'd trust it

Christian,

I've spent some time building a forecast of the seasonal population swing in
Collier and Lee County — when snowbirds arrive, when the region peaks, and when
it empties again. Short summary below; full report linked at the bottom.

### What it predicts

| | |
|---|---|
| Trough | **19 Sep 2026** (90% CI 15–23 Sep) |
| Season opens | **4 Nov 2026** |
| Peak | **8 Mar 2027** (flat window 20 Feb – 26 Mar) |
| Season ends | 6 May 2027 |
| Amplitude | **+23%** trough to peak |

### Where the data comes from

- **Road counts** — FDOT's traffic database: annual averages back to 1970, plus
  every day of 2024 hour-by-hour, from 14 continuous counting stations across
  both counties.
- **Temperature** — daily records 2000–2026 for Naples and for the twelve
  northern states people actually come from.
- **Arrivals** — RSW monthly passenger counts back to 1983, which is the only
  indicator current to within about six weeks.
- **Who comes from where** — IRS migration records and Florida property tax
  rolls. The property data is the better instrument: a home here whose owner
  gets mail out of state and claims no homestead exemption is a second home by
  definition. There are 62,572 of them — 28% of every home in Collier.

### The finding I didn't expect

People don't follow the weather. Traffic turns up about **25 days after** the
temperature says it should, and leaves about 25 days after the weather stops
justifying it. A lag at both ends is what a calendar looks like, not a
thermometer — after Thanksgiving, after Easter.

That has a practical consequence: you cannot forecast this season from a weather
forecast. I checked whether seasonal weather models help and they don't —
NOAA's ensemble is no more certain than simply knowing what month it is once
you're more than two months out.

### What I'd caveat

- The seasonal shape rests on **one year** of daily counts. The intervals say
  how precisely we know 2024, not how much the season varies year to year.
- The roads disagree with each other. Peak timing spans two months across
  stations and amplitude varies twofold — 17% at one, 34% in the rural
  Everglades. For a specific location the county average will mislead you.
- Traffic counts vehicles, not people. Someone who drives twice a day counts
  twice.

I'd also flag that several things I initially thought I'd found did not survive
being checked — a trend in the migration window, a rise in permanent
relocations. Both are in the report with the tests that killed them, which I
think matters more than the results that held.

Full report: [LINK]

Worth a conversation if any of this is useful to you.

Simon
