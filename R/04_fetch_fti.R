# =============================================================================
# 04 - THE FTI DATABASE (the real traffic data)
# =============================================================================
# FDOT publish their whole traffic database once a year as a Microsoft Access
# file. It is not linkable directly - you have to download the zip:
#
#   https://www.fdot.gov/statistics/trafficinfo/   ->  "FTI Database"
#   (about 97 MB zipped, 1.55 GB unzipped)
#
# Set FTI_PATH below to wherever you unzipped it.
#
# WHY THIS MATTERS: the ArcGIS service in script 02 gives 5 years of annual
# averages. This file has FORTY-EIGHT years, plus a full year of hourly counts.
#
# WHAT IT DOESN'T HAVE: the weekly/seasonal tables (PEAKSEASON,
# DIRECTIONAL_VOLUME) hold only the current year. FDOT overwrite them each
# edition rather than accumulating. So multi-year SEASONAL timing is not in
# here - see the note at the bottom.
#
# Reading .mdb needs the 64-bit Microsoft Access ODBC driver. Check yours with:
#   odbc::odbcListDrivers()
# If it's missing, install "Microsoft Access Database Engine 2016 Redistributable".
# =============================================================================

library(tidyverse)
library(DBI)
library(odbc)

FTI_PATH <- "C:/Users/SWeardon/AppData/Local/Temp/claude/C--Users-SWeardon-Desktop-Coding-in-R/56267a43-4d94-42e8-8b39-eef1ca5d0ec4/scratchpad/fti/fti_2025.mdb"
COLLIER  <- "03"   # FDOT county code for Collier County (Naples)

stopifnot(file.exists(FTI_PATH))

con <- dbConnect(
  odbc::odbc(),
  .connection_string = paste0(
    "Driver={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=",
    normalizePath(FTI_PATH, winslash = "\\"), ";"
  )
)

# Two Access/Jet SQL quirks that will bite you:
#   1. COUNT(DISTINCT x) is NOT supported. Do the distinct in R instead.
#   2. YEAR is a reserved word (it's a built-in function), so it must be
#      written as [YEAR] or you get "Too few parameters. Expected 1." - an
#      error message that tells you nothing about the real problem.

# -----------------------------------------------------------------------------
# A) Historical AADT - every year FDOT has, for Collier County
# -----------------------------------------------------------------------------
message("Pulling historical AADT for Collier County...")

hist_aadt <- dbGetQuery(con, paste0("
  SELECT COUNTY, SITE, [YEAR] AS yr, PTADTADJ, ASCADTADJ, DSCADTADJ
  FROM [HISTAADT]
  WHERE COUNTY = '", COLLIER, "'
")) %>%
  as_tibble() %>%
  # PTADTADJ is the site's AADT; the two direction columns sum to it.
  transmute(
    county = COUNTY,
    site   = SITE,
    year   = as.integer(yr),
    aadt   = as.numeric(PTADTADJ)
  ) %>%
  filter(!is.na(aadt), aadt > 0) %>%
  arrange(site, year)

write_csv(hist_aadt, "data/collier_hist_aadt.csv")

message("  ", format(nrow(hist_aadt), big.mark = ","), " site-years, ",
        min(hist_aadt$year), "-", max(hist_aadt$year),
        ", ", n_distinct(hist_aadt$site), " sites")

# -----------------------------------------------------------------------------
# B) Daily traffic counts - every day of 2024, from the continuous stations
# -----------------------------------------------------------------------------
# This is the one that actually answers the question. TMSCNT holds hour-by-hour
# volumes (HR1..HR24) per site per direction per day. TOTVOL is the day's total.
# Summing the directions gives daily two-way traffic past that point.
message("Pulling daily counts for Collier County...")

daily <- dbGetQuery(con, paste0("
  SELECT COUNTY, SITE, BEGDATE, DIR, TOTVOL
  FROM [TMSCNT]
  WHERE COUNTY = '", COLLIER, "'
")) %>%
  as_tibble() %>%
  transmute(
    site   = SITE,
    date   = as.Date(BEGDATE),
    dir    = DIR,
    volume = as.numeric(TOTVOL)
  ) %>%
  filter(!is.na(volume), volume > 0)

daily_site <- daily %>%
  group_by(site, date) %>%
  summarise(volume = sum(volume), .groups = "drop") %>%
  arrange(site, date)

write_csv(daily_site, "data/collier_daily_traffic.csv")

message("  ", format(nrow(daily_site), big.mark = ","), " site-days, ",
        format(min(daily_site$date)), " to ", format(max(daily_site$date)),
        ", ", n_distinct(daily_site$site), " sites")

dbDisconnect(con)

# -----------------------------------------------------------------------------
# Quick look
# -----------------------------------------------------------------------------
cat("\n--- Collier AADT by decade ---\n")
hist_aadt %>%
  mutate(decade = (year %/% 10) * 10) %>%
  group_by(decade) %>%
  summarise(sites = n_distinct(site), median_aadt = median(aadt), .groups = "drop") %>%
  print()

cat("\n--- Busiest stations in 2024 ---\n")
daily_site %>%
  filter(year(date) == 2024) %>%
  group_by(site) %>%
  summarise(days = n(), mean_daily = round(mean(volume)), .groups = "drop") %>%
  arrange(desc(mean_daily)) %>%
  print()

# -----------------------------------------------------------------------------
# NOTE ON WHAT IS MISSING
# -----------------------------------------------------------------------------
# PEAKSEASON and DIRECTIONAL_VOLUME contain only the edition year. To get
# multi-year seasonal timing you would need older FTI editions (fti_2024.zip,
# fti_2023.zip ...), which FDOT do not publish at guessable URLs - each one
# sits behind a generated token. Asking FDOT's Transportation Data & Analytics
# office directly is the realistic route.
