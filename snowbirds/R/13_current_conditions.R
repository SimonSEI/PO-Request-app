# =============================================================================
# 13 - CURRENT CONDITIONS
# =============================================================================
# The dashboard's headline dates come from a model fitted to 2024. On their own
# they are a climatology - "this is what a normal year does". That is not the
# same as "this is what THIS year will do".
#
# This script gathers the things that would make this year differ from normal,
# so the dashboard can explain each date in terms of what is actually happening
# rather than reciting fixed prose:
#
#   1. EL NINO / LA NINA   NOAA's Oceanic Nino Index. El Nino suppresses
#                          Atlantic hurricanes; La Nina encourages them. This
#                          is the single best advance signal for whether the
#                          autumn will be disrupted.
#   2. ACTIVE STORMS       National Hurricane Center live feed.
#   3. TEMPERATURE ANOMALY How warm the origin states and Naples are running
#                          against their own 26-year normals for these dates.
#                          A warm north means a weak pull south.
#   4. ARRIVALS SO FAR     RSW passengers year to date against recent years.
#
# Everything here is measured, not assumed. Where a source is unavailable the
# script says so rather than guessing, because a confident explanation built on
# a failed download is worse than no explanation.
# =============================================================================

local({
  lib <- file.path(getwd(), ".Rlib")
  if (dir.exists(lib)) .libPaths(c(lib, .libPaths()))
})

suppressPackageStartupMessages({
  library(tidyverse)
  library(lubridate)
  library(jsonlite)
})

TODAY <- Sys.Date()
out <- list()

note <- function(...) cat("  ", ..., "\n", sep = "")

# -----------------------------------------------------------------------------
# 1. El Nino / La Nina
# -----------------------------------------------------------------------------
cat("El Nino / La Nina (NOAA ONI)...\n")

oni <- try({
  raw <- readLines("https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt", warn = FALSE)
  df <- read.table(text = paste(raw, collapse = "\n"), header = TRUE,
                   stringsAsFactors = FALSE)
  tail(df, 1)
}, silent = TRUE)

if (!inherits(oni, "try-error") && nrow(oni) == 1) {
  v <- as.numeric(oni$ANOM)
  # NOAA's own thresholds.
  state <- case_when(
    v >=  1.5 ~ "strong El Nino",
    v >=  1.0 ~ "moderate El Nino",
    v >=  0.5 ~ "weak El Nino",
    v <= -1.5 ~ "strong La Nina",
    v <= -1.0 ~ "moderate La Nina",
    v <= -0.5 ~ "weak La Nina",
    TRUE      ~ "neutral"
  )
  out$oni_value  <- v
  out$oni_season <- as.character(oni$SEAS)
  out$oni_state  <- state
  # El Nino shears the Atlantic and suppresses storms; La Nina does the reverse.
  out$hurricane_outlook <- case_when(
    v >=  0.5 ~ "suppressed",
    v <= -0.5 ~ "enhanced",
    TRUE      ~ "near normal"
  )
  note("ONI ", out$oni_season, " = ", v, "  (", state, ")")
  note("Atlantic hurricane activity: ", out$hurricane_outlook)
} else {
  out$oni_state <- NA_character_
  note("ONI unavailable")
}

# -----------------------------------------------------------------------------
# 2. Active storms right now
# -----------------------------------------------------------------------------
cat("Active storms (NHC)...\n")

storms <- try(fromJSON("https://www.nhc.noaa.gov/CurrentStorms.json"), silent = TRUE)

if (!inherits(storms, "try-error") && !is.null(storms$activeStorms)) {
  a <- storms$activeStorms
  atl <- if (length(a) && nrow(a) > 0) a[str_detect(a$id, "^al"), , drop = FALSE] else a[0, ]
  out$storms_atlantic <- if (is.null(nrow(atl))) 0L else nrow(atl)
  out$storm_names <- if (out$storms_atlantic > 0) paste(atl$name, collapse = ", ") else ""
  note("Atlantic storms active: ", out$storms_atlantic,
       if (nzchar(out$storm_names)) paste0(" (", out$storm_names, ")") else "")
} else {
  out$storms_atlantic <- NA_integer_
  note("NHC feed unavailable")
}

# -----------------------------------------------------------------------------
# 3. Temperature anomaly: how is this year running against normal?
# -----------------------------------------------------------------------------
cat("Temperature anomalies...\n")

states <- read_csv("data/origin_states.csv", show_col_types = FALSE) %>%
  slice_head(n = 6)

# past_days pulls recent observations the historical archive has not caught up
# with yet; forecast_days looks a fortnight ahead. Together they describe "now".
fetch_recent <- function(lat, lon) {
  url <- paste0("https://api.open-meteo.com/v1/forecast",
                "?latitude=", round(lat, 4), "&longitude=", round(lon, 4),
                "&daily=temperature_2m_mean&past_days=30&forecast_days=14",
                "&temperature_unit=fahrenheit&timezone=auto")
  r <- try(fromJSON(url), silent = TRUE)
  if (inherits(r, "try-error")) return(NULL)
  tibble(date = as.Date(r$daily$time), temp = r$daily$temperature_2m_mean)
}

naples_recent <- fetch_recent(26.142, -81.795)
Sys.sleep(2)

north_recent <- map_dfr(seq_len(nrow(states)), function(i) {
  x <- fetch_recent(states$lat[i], states$lon[i])
  Sys.sleep(2)
  if (is.null(x)) NULL else mutate(x, state = states$state[i], people = states$people[i])
})

# Climatology from the archive we already hold.
wx <- read_csv("data/weather_daily.csv", show_col_types = FALSE)

clim_naples <- wx %>%
  filter(city == "Naples FL") %>%
  mutate(doy = yday(date)) %>%
  group_by(doy) %>% summarise(norm = mean(temp_mean, na.rm = TRUE), .groups = "drop")

state_hist <- read_csv("data/origin_state_temps.csv", show_col_types = FALSE)
clim_north <- state_hist %>%
  filter(state %in% states$state) %>%
  mutate(doy = yday(date)) %>%
  group_by(doy) %>%
  summarise(norm = weighted.mean(temp, people, na.rm = TRUE), .groups = "drop")

# Compare the last 30 days only - "how is it running right now".
window <- seq(TODAY - 30, TODAY, by = "day")

anom <- function(recent, clim) {
  if (is.null(recent) || nrow(recent) == 0) return(NA_real_)
  recent %>%
    filter(date %in% window) %>%
    mutate(doy = yday(date)) %>%
    left_join(clim, by = "doy") %>%
    summarise(a = mean(temp - norm, na.rm = TRUE)) %>% pull(a)
}

north_avg <- north_recent %>%
  group_by(date) %>%
  summarise(temp = weighted.mean(temp, people, na.rm = TRUE), .groups = "drop")

out$naples_anom <- anom(naples_recent, clim_naples)
out$north_anom  <- anom(north_avg, clim_north)

# The gap is what actually drives migration, so track its anomaly directly.
if (!is.na(out$naples_anom) && !is.na(out$north_anom)) {
  out$gap_anom <- out$naples_anom - out$north_anom
  note("Naples running ", sprintf("%+.1f", out$naples_anom), " F vs normal")
  note("Origin states running ", sprintf("%+.1f", out$north_anom), " F vs normal")
  note("Temperature GAP running ", sprintf("%+.1f", out$gap_anom), " F vs normal")
} else {
  out$gap_anom <- NA_real_
  note("temperature anomalies unavailable")
}

# -----------------------------------------------------------------------------
# 4. Arrivals so far this year
# -----------------------------------------------------------------------------
cat("Arrivals year to date...\n")

rsw <- read_csv("data/rsw_monthly_passengers.csv", show_col_types = FALSE)
yr  <- max(rsw$year)
mth <- rsw %>% filter(year == yr) %>% pull(month)

ytd <- rsw %>%
  filter(month %in% mth) %>%
  group_by(year) %>% filter(n() == length(mth)) %>%
  summarise(total = sum(passengers), .groups = "drop")

now  <- ytd$total[ytd$year == yr]
prev <- ytd$total[ytd$year == yr - 1]

out$rsw_year       <- yr
out$rsw_months     <- max(mth)
out$rsw_ytd_change <- if (length(now) && length(prev)) 100 * (now / prev - 1) else NA_real_

if (!is.na(out$rsw_ytd_change)) {
  note("RSW ", yr, " through month ", max(mth), ": ",
       sprintf("%+.2f%%", out$rsw_ytd_change), " vs ", yr - 1)
}

# -----------------------------------------------------------------------------
# 5. Save
# -----------------------------------------------------------------------------
out$updated <- format(Sys.time(), "%Y-%m-%d %H:%M")

conditions <- tibble(key = names(out), value = map_chr(out, ~ as.character(.x[1])))
write_csv(conditions, "data/current_conditions.csv")

cat("\nSaved data/current_conditions.csv\n")
print(as.data.frame(conditions), row.names = FALSE)
