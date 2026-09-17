# =============================================================================
# 09 - PREDICTING THE SEASON
# =============================================================================
# The operational questions:
#   1. When does the season START and END?
#   2. When is the PEAK, and when is the TROUGH?
#   3. How far does traffic FALL from the peak?
#   4. How far does it RISE from the trough?
#   ... and with what uncertainty on each.
#
# METHOD: harmonic (Fourier) regression.
#
# A season is a wave, so fit waves to it. sin/cos pairs at 1, 2, 3 and 4 cycles
# per year describe a smooth repeating shape without us telling it where the
# peak should be. Day-of-week terms soak up the Sunday/Tuesday rhythm so it
# doesn't leak into the seasonal estimate.
#
# We model log(index) rather than index, so effects are multiplicative: a
# coefficient means "+12%" rather than "+0.12 cars", which is what you want
# for something that scales with the size of the road.
#
# UNCERTAINTY: a moving-block bootstrap. Ordinary bootstrapping assumes each
# day is independent, which is nonsense for traffic - a busy Tuesday implies a
# busy Wednesday. Resampling CONTIGUOUS BLOCKS of days preserves that
# stickiness, so the confidence intervals aren't fantasy.
#
# ONE COUNTY AT A TIME, AND WHY THAT MATTERS
#
# This script used to average Collier and Lee stations into a single index and
# call the result "Naples". That is a mistake, and an expensive one: pooling
# the two counties moved "season starts" from 17 Nov to 4 Nov and cut the
# peak-to-trough decline from 24.0% to 18.9%. A fortnight and a fifth of the
# amplitude, from a scope decision rather than from any new data.
#
# The two counties genuinely differ. Collier troughs in September, the dead
# month between the tourists and the snowbirds. Lee troughs in JUNE and has a
# far shallower season. Averaging them describes no road that exists.
#
# So each county is fitted on its own. PRIMARY_COUNTY is what the headline
# numbers and output/season_forecast.csv describe - Collier, because this is
# the Naples project. Every county, plus the pooled figure kept purely as a
# cautionary comparison, goes to output/season_forecast_by_county.csv.
#
# THE LIMITATION, STATED PLAINLY: this is fitted to ONE season (2024). It can
# tell you the shape of that year precisely. It CANNOT tell you how much the
# shape varies BETWEEN years, because we have no second year to compare. The
# intervals below are "how well do we know 2024", not "how well do we know next
# year". Treat them as a floor on the true uncertainty.
#
# AND THE ONE NOBODY WROTE DOWN: 2024 was a hurricane year. R/11 excludes the
# 2024 season from its airport trend as too contaminated to measure timing
# with. This script fits to that same season and removes only the storm DAYS.
# Removing the days does not remove the aftermath - anyone whose return was
# deferred by Milton is still in the autumn ramp, which is exactly the part
# "season starts" is estimated from. A second year of FTI data is the fix.
# =============================================================================

library(tidyverse)
library(lubridate)
library(scales)

theme_set(theme_minimal(base_size = 12))
set.seed(42)          # bootstraps are random; fix the seed so results repeat

# The county the headline numbers describe. Everything downstream that reads
# output/season_forecast.csv (R/10, R/12, R/18, the dashboard) gets this one.
PRIMARY_COUNTY <- "Collier"

K     <- 4      # number of harmonics
BLOCK <- 14     # days per block - long enough to hold the weekly cycle
B     <- 600    # bootstrap replicates
MIN_DAYS <- 330 # a station needs this many clean days to be worth fitting

traffic <- read_csv("data/collier_daily_traffic.csv", show_col_types = FALSE)

# Hurricanes Debby, Helene and Milton - see R/05.
STORM_DAYS <- c(
  seq(as.Date("2024-08-03"), as.Date("2024-08-06"), by = "day"),
  seq(as.Date("2024-09-24"), as.Date("2024-09-29"), by = "day"),
  seq(as.Date("2024-10-06"), as.Date("2024-10-14"), by = "day")
)

tr <- traffic %>% filter(!date %in% STORM_DAYS)

# -----------------------------------------------------------------------------
# 1. The pieces, each written once so every county gets the same treatment
# -----------------------------------------------------------------------------
# Build sin/cos columns. k = 1 is one cycle per year, k = 2 is two, and so on.
# More harmonics = a wigglier curve. Four is enough to capture a shoulder
# season without chasing individual weeks.
harmonics <- function(doy, K) {
  map_dfc(1:K, function(k) {
    tibble(!!paste0("sin", k) := sin(2 * pi * k * doy / 365.25),
           !!paste0("cos", k) := cos(2 * pi * k * doy / 365.25))
  })
}

# Everything needed to describe one scope: which stations, the daily index,
# the model frame and the fit. Each station is divided by its OWN annual mean
# first, so a big road and a small one contribute equally to the shape.
fit_scope <- function(rows) {
  good <- rows %>% count(site) %>% filter(n >= MIN_DAYS) %>% pull(site)
  if (length(good) == 0) return(NULL)

  idx <- rows %>%
    filter(site %in% good) %>%
    group_by(site) %>%
    mutate(index = volume / mean(volume)) %>%
    ungroup()

  daily <- idx %>%
    group_by(date) %>%
    summarise(index = mean(index), .groups = "drop") %>%
    arrange(date) %>%
    mutate(
      doy = yday(date),
      dow = wday(date, label = TRUE),
      y   = log(index)
    )

  md <- bind_cols(daily, harmonics(daily$doy, K))
  hn <- setdiff(names(md), names(daily))
  fm <- as.formula(paste("y ~ dow +", paste(hn, collapse = " + ")))

  list(sites = good, idx = idx, daily = daily,
       model_df = md, form = fm, fit = lm(fm, data = md))
}

# Predict across a full year holding day-of-week at its average, so what's left
# is purely seasonal.
seasonal_curve <- function(model, dows) {
  grid <- tibble(doy = 1:365) %>% bind_cols(harmonics(1:365, K))

  # average the weekday effect rather than picking an arbitrary day
  preds <- map_dfc(dows, function(d) {
    g <- grid %>% mutate(dow = factor(d, levels = dows))
    tibble(!!d := predict(model, newdata = g))
  })

  tibble(doy = 1:365, logidx = rowMeans(as.matrix(preds))) %>%
    mutate(index = exp(logidx))
}

# Pull the numbers we care about out of a curve. Written as a function so the
# bootstrap can call it hundreds of times.
describe <- function(cv) {
  peak_doy   <- cv$doy[which.max(cv$index)]
  trough_doy <- cv$doy[which.min(cv$index)]
  peak_val   <- max(cv$index)
  trough_val <- min(cv$index)

  # Season boundaries: where the curve crosses an average day (index = 1).
  # Falling crossing = season ending (spring). Rising = season starting (autumn).
  above <- cv$index >= 1
  cross_down <- which(above[-length(above)] & !above[-1])   # TRUE -> FALSE
  cross_up   <- which(!above[-length(above)] & above[-1])   # FALSE -> TRUE

  # Take the crossing in the sensible half of the year; the curve is high in
  # winter, so the fall happens in spring and the rise in autumn.
  end_doy   <- if (length(cross_down)) cross_down[cross_down > 60  & cross_down < 240][1] else NA
  start_doy <- if (length(cross_up))   cross_up[  cross_up   > 240][1] else NA

  tibble(
    peak_doy, trough_doy, start_doy, end_doy,
    peak_val, trough_val,
    # Fall from the peak down to the trough
    decline_pct = 100 * (1 - trough_val / peak_val),
    # Rise from the trough back up to the peak
    increase_pct = 100 * (peak_val / trough_val - 1),
    season_days = if (!is.na(start_doy) && !is.na(end_doy)) (365 - start_doy) + end_doy else NA
  )
}

# Moving-block bootstrap: rebuild a residual series by stitching together
# random contiguous blocks, refit, and re-describe.
boot_scope <- function(sc, reps) {
  rv <- residuals(sc$fit)
  fv <- fitted(sc$fit)
  nn <- length(rv)
  dows <- levels(sc$daily$dow)

  map_dfr(seq_len(reps), function(b) {
    starts <- sample(seq_len(nn - BLOCK + 1), ceiling(nn / BLOCK), replace = TRUE)
    r <- unlist(map(starts, ~ rv[.x:(.x + BLOCK - 1)]))[1:nn]

    d <- sc$model_df
    d$y <- fv + r

    f <- try(lm(sc$form, data = d), silent = TRUE)
    if (inherits(f, "try-error")) return(NULL)

    describe(seasonal_curve(f, dows))
  })
}

ci <- function(x, p = c(0.05, 0.95)) quantile(x, p, na.rm = TRUE)

doy_to_date <- function(d) format(as.Date(d - 1, origin = "2025-01-01"), "%d %b")

METRICS <- c("peak_doy", "trough_doy", "start_doy", "end_doy",
             "peak_val", "trough_val", "decline_pct", "increase_pct", "season_days")

# One tidy row per scope: point estimate plus a 90% interval for each metric.
summarise_scope <- function(label, sc, bt) {
  pt <- describe(seasonal_curve(sc$fit, levels(sc$daily$dow)))

  out <- tibble(
    scope      = label,
    n_stations = length(sc$sites),
    stations   = paste(sc$sites, collapse = " "),
    model_r2   = summary(sc$fit)$r.squared
  )

  for (m in METRICS) {
    q <- ci(bt[[m]])
    out[[m]]                  <- pt[[m]]
    out[[paste0(m, "_lo")]]   <- unname(q[1])
    out[[paste0(m, "_hi")]]   <- unname(q[2])
  }
  out
}

# -----------------------------------------------------------------------------
# 2. Fit every scope
# -----------------------------------------------------------------------------
# Pooled is kept deliberately, and last, so the comparison table can show what
# averaging two different counties does to the answer.
counties <- sort(unique(tr$county_name))
scopes   <- set_names(map(counties, ~ tr %>% filter(county_name == .x)), counties)
scopes[["Pooled"]] <- tr

fits  <- compact(map(scopes, fit_scope))
boots <- map(fits, ~ boot_scope(.x, B))

county_tbl <- imap_dfr(fits, function(sc, label) summarise_scope(label, sc, boots[[label]]))

if (!PRIMARY_COUNTY %in% names(fits)) {
  stop("PRIMARY_COUNTY '", PRIMARY_COUNTY, "' has no station with ", MIN_DAYS,
       "+ clean days. Available: ", paste(names(fits), collapse = ", "), call. = FALSE)
}

# The primary scope, under the names the rest of the script expects.
sc         <- fits[[PRIMARY_COUNTY]]
good_sites <- sc$sites
idx        <- sc$idx
county     <- sc$daily
model_df   <- sc$model_df
form       <- sc$form
fit        <- sc$fit
curve      <- seasonal_curve(fit, levels(county$dow))
point      <- describe(curve)
boot       <- boots[[PRIMARY_COUNTY]]

resid_vec  <- residuals(fit)
fitted_vec <- fitted(fit)
n          <- length(resid_vec)

message(nrow(county), " days, ", length(good_sites), " stations in ", PRIMARY_COUNTY)
cat("\nModel R-squared:", round(summary(fit)$r.squared, 3), "\n")

# -----------------------------------------------------------------------------
# 3. Report
# -----------------------------------------------------------------------------
cat("\n")
cat("=====================================================================\n")
cat("  SEASON FORECAST - ", PRIMARY_COUNTY, " County\n", sep = "")
cat("  Harmonic model on 2024 daily counts, ", B, " block-bootstrap runs\n", sep = "")
cat("  Stations: ", paste(good_sites, collapse = ", "), "\n", sep = "")
cat("=====================================================================\n\n")

report_date <- function(label, point_val, boot_col) {
  b <- ci(boot[[boot_col]])
  cat(sprintf("%-22s %-9s  (90%% CI: %s to %s)\n",
              label, doy_to_date(point_val),
              doy_to_date(round(b[1])), doy_to_date(round(b[2]))))
}

cat("--- KEY DATES ---\n")
report_date("Season starts",  point$start_doy,  "start_doy")
report_date("PEAK",           point$peak_doy,   "peak_doy")
report_date("Season ends",    point$end_doy,    "end_doy")
report_date("TROUGH",         point$trough_doy, "trough_doy")

cat(sprintf("\nSeason length          %d days    (90%% CI: %d to %d)\n",
            round(point$season_days),
            round(ci(boot$season_days)[1]), round(ci(boot$season_days)[2])))

cat("\n--- MAGNITUDE ---\n")
cat(sprintf("Peak level             %.3fx an average day  (90%% CI: %.3f to %.3f)\n",
            point$peak_val, ci(boot$peak_val)[1], ci(boot$peak_val)[2]))
cat(sprintf("Trough level           %.3fx an average day  (90%% CI: %.3f to %.3f)\n",
            point$trough_val, ci(boot$trough_val)[1], ci(boot$trough_val)[2]))
cat(sprintf("\nDecline from peak      %.1f%%   (90%% CI: %.1f%% to %.1f%%)\n",
            point$decline_pct, ci(boot$decline_pct)[1], ci(boot$decline_pct)[2]))
cat(sprintf("Increase from trough   %.1f%%   (90%% CI: %.1f%% to %.1f%%)\n",
            point$increase_pct, ci(boot$increase_pct)[1], ci(boot$increase_pct)[2]))

# A date range is more honest than a single day for something this flat at the
# top. Report the window within 1% of the extreme.
peak_window   <- curve %>% filter(index >= max(index) * 0.99)
trough_window <- curve %>% filter(index <= min(index) * 1.01)

cat("\n--- PRACTICAL DATE RANGES (within 1% of the extreme) ---\n")
cat("Peak period:   ", doy_to_date(min(peak_window$doy)), " to ",
    doy_to_date(max(peak_window$doy)),
    "  (", nrow(peak_window), " days)\n", sep = "")
cat("Trough period: ", doy_to_date(min(trough_window$doy)), " to ",
    doy_to_date(max(trough_window$doy)),
    "  (", nrow(trough_window), " days)\n", sep = "")

# -----------------------------------------------------------------------------
# 4. By county - the scope check
# -----------------------------------------------------------------------------
cat("\n--- BY COUNTY ---\n")
cat("Pooling is shown only to demonstrate what it costs. It is not a forecast\n")
cat("for anywhere: it is the average of counties whose seasons differ.\n\n")

county_tbl %>%
  transmute(
    Scope        = scope,
    Stations     = n_stations,
    Starts       = doy_to_date(start_doy),
    Peak         = doy_to_date(peak_doy),
    Ends         = doy_to_date(end_doy),
    Trough       = doy_to_date(trough_doy),
    `Decline %`  = round(decline_pct, 1),
    `R2`         = round(model_r2, 3)
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

# -----------------------------------------------------------------------------
# 5. Per-station, because roads differ even inside one county
# -----------------------------------------------------------------------------
cat("\n--- BY STATION ---\n")

all_sites <- tr %>% count(site) %>% filter(n >= MIN_DAYS) %>% pull(site)
idx_all <- tr %>%
  filter(site %in% all_sites) %>%
  group_by(site) %>%
  mutate(index = volume / mean(volume)) %>%
  ungroup()

station_tbl <- map_dfr(all_sites, function(s) {
  d <- idx_all %>% filter(site == s) %>%
    arrange(date) %>%
    mutate(doy = yday(date), dow = wday(date, label = TRUE), y = log(index))
  cty <- first(d$county_name)
  d <- bind_cols(d, harmonics(d$doy, K))
  f <- lm(form, data = d)

  describe(seasonal_curve(f, levels(d$dow))) %>%
    mutate(site = s, county_name = cty, .before = 1)
})

station_tbl %>%
  transmute(
    Station = site,
    County  = county_name,
    Peak    = doy_to_date(peak_doy),
    Trough  = doy_to_date(trough_doy),
    Starts  = doy_to_date(start_doy),
    Ends    = doy_to_date(end_doy),
    `Decline %`  = round(decline_pct, 1),
    `Increase %` = round(increase_pct, 1)
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

# -----------------------------------------------------------------------------
# 6. Write
# -----------------------------------------------------------------------------
# season_forecast.csv and seasonal_curve.csv describe PRIMARY_COUNTY alone.
# Everything downstream reads those two, so they are the ones that must not
# quietly change meaning again - hence the county column on both.
write_csv(station_tbl, "output/season_forecast_by_station.csv")
write_csv(county_tbl,  "output/season_forecast_by_county.csv")

write_csv(
  bind_cols(point, tibble(model_r2 = summary(fit)$r.squared,
                          county   = PRIMARY_COUNTY,
                          stations = paste(good_sites, collapse = " "))),
  "output/season_forecast.csv")

write_csv(curve %>% mutate(county = PRIMARY_COUNTY), "output/seasonal_curve.csv")

curves_by_county <- imap_dfr(fits, function(s, label) {
  seasonal_curve(s$fit, levels(s$daily$dow)) %>% mutate(scope = label, .before = 1)
})
write_csv(curves_by_county, "output/seasonal_curve_by_county.csv")

# -----------------------------------------------------------------------------
# 7. Chart
# -----------------------------------------------------------------------------
# Bootstrap ribbon: the spread of fitted curves, not just the point estimate.
boot_curves <- map_dfr(seq_len(200), function(b) {
  starts <- sample(seq_len(n - BLOCK + 1), ceiling(n / BLOCK), replace = TRUE)
  r <- unlist(map(starts, ~ resid_vec[.x:(.x + BLOCK - 1)]))[1:n]
  d <- model_df; d$y <- fitted_vec + r
  f <- try(lm(form, data = d), silent = TRUE)
  if (inherits(f, "try-error")) return(NULL)
  seasonal_curve(f, levels(county$dow)) %>% mutate(rep = b)
})

ribbon <- boot_curves %>%
  group_by(doy) %>%
  summarise(lo = quantile(index, 0.05), hi = quantile(index, 0.95), .groups = "drop")

p <- ggplot() +
  geom_point(data = county, aes(doy, index), colour = "grey70", size = 0.7, alpha = 0.6) +
  geom_ribbon(data = ribbon, aes(doy, ymin = lo, ymax = hi),
              fill = "#2a6f97", alpha = 0.25) +
  geom_line(data = curve, aes(doy, index), colour = "#2a6f97", linewidth = 1.2) +
  geom_hline(yintercept = 1, linetype = "dotted", colour = "grey35") +
  geom_vline(xintercept = point$peak_doy,   colour = "#c1121f", linetype = "dashed") +
  geom_vline(xintercept = point$trough_doy, colour = "#e07a5f", linetype = "dashed") +
  annotate("text", x = point$peak_doy + 4, y = max(curve$index),
           label = paste0("peak ", doy_to_date(point$peak_doy)),
           hjust = 0, colour = "#c1121f", size = 3.6) +
  annotate("text", x = point$trough_doy + 4, y = min(curve$index),
           label = paste0("trough ", doy_to_date(point$trough_doy)),
           hjust = 0, colour = "#e07a5f", size = 3.6) +
  scale_x_continuous(breaks = c(1, 60, 121, 182, 244, 305, 365),
                     labels = c("Jan", "Mar", "May", "Jul", "Sep", "Nov", "Dec")) +
  labs(
    title = paste0("Predicted ", PRIMARY_COUNTY, " County traffic season"),
    subtitle = paste0("Harmonic model, grey = actual 2024 days, band = 90% bootstrap interval.\n",
                      "Peak ", round(point$peak_val, 2), "x average, trough ",
                      round(point$trough_val, 2), "x - a ",
                      round(point$decline_pct), "% fall from peak to trough."),
    x = NULL, y = "Traffic (1.0 = average day)"
  )

ggsave("output/10_season_forecast.png", p, width = 10, height = 5.5, dpi = 150)

message("\nWritten: output/10_season_forecast.png and five CSVs")
