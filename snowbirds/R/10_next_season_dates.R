# =============================================================================
# 10 - ACTUAL CALENDAR DATES FOR THE NEXT PEAK AND TROUGH
# =============================================================================
# Plus an honest test of whether weather forecasting helps at all here.
#
# THE SHORT ANSWER ON WEATHER MODELS
#
# Google DeepMind's GraphCast/GenCast, ECMWF, GFS - all of them are excellent,
# and none of them can tell you about March from September. Deterministic
# weather forecasting has a hard skill horizon of roughly 10-15 days. That is
# physics (chaos), not a software limitation, and no model beats it.
#
# What DOES run months ahead is a SEASONAL forecast: NOAA's CFSv2 ensemble,
# ECMWF SEAS5. They predict slow things - ocean temperature, El Nino - and give
# an ensemble of possible atmospheres rather than one answer.
#
# So instead of assuming they help, this script MEASURES it: compare the
# seasonal ensemble's spread against plain climatology over the same dates. If
# the ensemble is no tighter than "what usually happens", it carries no
# information and we should use climatology, which is free and simpler.
#
# AND THE DEEPER POINT: script 05 already showed traffic LAGS temperature by
# ~25 days at both ends, with r-squared 0.44. Even a perfect thermometer
# forecast would be a mediocre traffic forecast. People move on the calendar.
# =============================================================================

library(tidyverse)
library(lubridate)
library(jsonlite)
library(scales)

theme_set(theme_minimal(base_size = 12))

NAPLES <- c(lat = 26.142, lon = -81.795)
TODAY  <- Sys.Date()

# -----------------------------------------------------------------------------
# 1. The seasonal shape, from the harmonic model (script 09)
# -----------------------------------------------------------------------------
curve <- read_csv("output/seasonal_curve.csv", show_col_types = FALSE)
fc    <- read_csv("output/season_forecast.csv", show_col_types = FALSE)

# Turn a day-of-year into the NEXT time that day comes round.
next_occurrence <- function(doy, from = TODAY) {
  this_year <- as.Date(paste0(year(from), "-01-01")) + (doy - 1)
  if_else(this_year >= from, this_year,
          as.Date(paste0(year(from) + 1, "-01-01")) + (doy - 1))
}

# A range is more honest than a day: report where the curve sits within 1% of
# its extreme, because the top of this curve is flat.
peak_band   <- curve %>% filter(index >= max(index) * 0.99)
trough_band <- curve %>% filter(index <= min(index) * 1.01)

dates <- tibble(
  event = c("Trough", "Season starts", "Peak", "Season ends"),
  doy   = c(fc$trough_doy, fc$start_doy, fc$peak_doy, fc$end_doy)
) %>%
  mutate(
    date      = next_occurrence(doy),
    days_away = as.numeric(date - TODAY)
  ) %>%
  arrange(date)

cat("=====================================================================\n")
cat("  NEXT SEASON - Collier + Lee County (Naples & Fort Myers).  Today is ", format(TODAY, "%d %b %Y"), "\n", sep = "")
cat("=====================================================================\n\n")

dates %>%
  transmute(
    Event = event,
    Date  = format(date, "%a %d %b %Y"),
    `Days away` = days_away
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

# Anchoring a window needs care. Applying next_occurrence() to each end
# separately printed the trough window as "12 Sep 2027 to 01 Oct 2026" - the
# ends landed in different years, because today (15 Sep) sits INSIDE the band,
# so its start had already passed and its end had not. Anchor both ends to the
# year of the central estimate instead, then nudge any end that ended up more
# than half a year away.
anchor_window <- function(band_doys, centre) {
  cand <- as.Date(paste0(year(centre), "-01-01")) + (range(band_doys) - 1)
  off  <- as.numeric(cand - centre)
  cand[off >  183] <- cand[off >  183] - 365
  cand[off < -183] <- cand[off < -183] + 365
  sort(cand)
}

peak_win   <- anchor_window(peak_band$doy,   dates$date[dates$event == "Peak"])
trough_win <- anchor_window(trough_band$doy, dates$date[dates$event == "Trough"])

cat("\nPeak window:   ", format(peak_win[1], "%d %b %Y"), " to ",
    format(peak_win[2], "%d %b %Y"), "\n", sep = "")
cat("Trough window: ", format(trough_win[1], "%d %b %Y"), " to ",
    format(trough_win[2], "%d %b %Y"), sep = "")
if (TODAY >= trough_win[1] && TODAY <= trough_win[2]) {
  cat("   <- we are inside this window today")
}
cat("\n")

cat("\nExpected levels (1.0 = an average day):\n")
cat("  Peak   ", round(fc$peak_val, 3),   "x   (", round(fc$increase_pct, 1),
    "% above the trough)\n", sep = "")
cat("  Trough ", round(fc$trough_val, 3), "x   (", round(fc$decline_pct, 1),
    "% below the peak)\n", sep = "")

# -----------------------------------------------------------------------------
# 2. Does the seasonal weather forecast actually know anything?
# -----------------------------------------------------------------------------
fetch <- function(url, tries = 5) {
  for (i in seq_len(tries)) {
    r <- try(fromJSON(url), silent = TRUE)
    if (!inherits(r, "try-error")) return(r)
    Sys.sleep(5 * 2^(i - 1))
  }
  NULL
}

cat("\n\n=====================================================================\n")
cat("  DO SEASONAL WEATHER MODELS HELP?\n")
cat("=====================================================================\n\n")

seas_file <- "data/seasonal_forecast_naples.csv"

if (file.exists(seas_file)) {
  seas <- read_csv(seas_file, show_col_types = FALSE)
  message("using cached seasonal forecast")
} else {
  message("fetching NOAA CFSv2 seasonal ensemble...")
  raw <- fetch(paste0(
    "https://seasonal-api.open-meteo.com/v1/seasonal",
    "?latitude=", NAPLES["lat"], "&longitude=", NAPLES["lon"],
    "&daily=temperature_2m_max&forecast_days=180&temperature_unit=fahrenheit"
  ))

  if (is.null(raw)) stop("seasonal API unavailable")

  members <- names(raw$daily)[str_detect(names(raw$daily), "member")]
  seas <- map_dfr(members, function(m) {
    tibble(date = as.Date(raw$daily$time), member = m, tmax = raw$daily[[m]])
  }) %>% filter(!is.na(tmax))

  write_csv(seas, seas_file)
}

# Ensemble spread per day = the model's own uncertainty.
ens <- seas %>%
  group_by(date) %>%
  summarise(
    ens_mean = mean(tmax),
    ens_sd   = sd(tmax),
    .groups  = "drop"
  ) %>%
  mutate(horizon = as.numeric(date - min(date)),
         doy = yday(date))

# Climatology spread per calendar day = "what usually happens", from 26 years.
clim <- read_csv("data/weather_daily.csv", show_col_types = FALSE) %>%
  filter(city == "Naples FL") %>%
  mutate(doy = yday(date)) %>%
  group_by(doy) %>%
  summarise(clim_mean = mean(temp_max, na.rm = TRUE),
            clim_sd   = sd(temp_max,  na.rm = TRUE), .groups = "drop")

skill <- ens %>%
  inner_join(clim, by = "doy") %>%
  mutate(
    # Below 1 means the forecast is tighter than climatology, i.e. it knows
    # something. At or above 1 it knows nothing useful.
    spread_ratio = ens_sd / clim_sd,
    month = floor_date(date, "month")
  )

cat("Comparing the 50-member ensemble against 26 years of climatology.\n")
cat("spread ratio = ensemble SD / climatology SD\n")
cat("  well under 1.0 = the forecast is genuinely more certain than 'usual'\n")
cat("  around 1.0     = it is telling you nothing climatology did not\n\n")

skill %>%
  group_by(month) %>%
  summarise(
    days = n(),
    `ens SD` = round(mean(ens_sd), 2),
    `clim SD` = round(mean(clim_sd), 2),
    ratio = round(mean(spread_ratio), 2),
    .groups = "drop"
  ) %>%
  mutate(month = format(month, "%b %Y")) %>%
  as.data.frame() %>% print(row.names = FALSE)

first_week <- skill %>% filter(horizon <= 7) %>% summarise(r = mean(spread_ratio)) %>% pull(r)
beyond_60  <- skill %>% filter(horizon > 60) %>% summarise(r = mean(spread_ratio)) %>% pull(r)

cat("\nMean spread ratio, first 7 days: ", round(first_week, 2), "\n", sep = "")
cat("Mean spread ratio, beyond 60 days:", round(beyond_60, 2), "\n", sep = "")

cat("\nVERDICT: ")
if (beyond_60 >= 0.9) {
  cat("beyond about two months the seasonal ensemble is no tighter\n")
  cat("than climatology. For predicting the March peak it adds nothing, and\n")
  cat("the harmonic model above - which uses no weather forecast at all - is\n")
  cat("the better instrument.\n")
} else {
  cat("the seasonal ensemble is meaningfully tighter than climatology;\n")
  cat("worth folding into the temperature model.\n")
}

# -----------------------------------------------------------------------------
# 3. Chart: forecast uncertainty against climatology
# -----------------------------------------------------------------------------
p <- skill %>%
  ggplot(aes(date)) +
  geom_ribbon(aes(ymin = clim_mean - 2 * clim_sd, ymax = clim_mean + 2 * clim_sd,
                  fill = "Climatology (26 years)"), alpha = 0.3) +
  geom_ribbon(aes(ymin = ens_mean - 2 * ens_sd, ymax = ens_mean + 2 * ens_sd,
                  fill = "CFSv2 seasonal ensemble"), alpha = 0.45) +
  geom_line(aes(y = ens_mean), colour = "#c1121f", linewidth = 0.9) +
  scale_fill_manual(values = c("Climatology (26 years)" = "grey55",
                               "CFSv2 seasonal ensemble" = "#2a6f97")) +
  scale_x_date(date_labels = "%b %Y", date_breaks = "1 month") +
  labs(
    title = "A seasonal forecast is barely narrower than just knowing the season",
    subtitle = paste0("Naples daily max temperature, +/- 2 SD. Red line = ensemble mean.\n",
                      "Beyond ~2 months the blue band is as wide as the grey one."),
    x = NULL, y = "Daily max (deg F)", fill = NULL
  ) +
  theme(legend.position = "top")

ggsave("output/11_forecast_vs_climatology.png", p, width = 10, height = 5.5, dpi = 150)

write_csv(dates, "output/next_season_dates.csv")
write_csv(skill, "output/forecast_skill.csv")

message("\nWritten: output/11_forecast_vs_climatology.png")
