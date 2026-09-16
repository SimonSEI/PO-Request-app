# =============================================================================
# 05 - DO PEOPLE ACTUALLY MOVE WHEN THE THERMOMETER SAYS?
# =============================================================================
# Everything up to now measured TEMPERATURE and called it migration. This is
# the first script that measures PEOPLE.
#
# We have every day of 2024 from Collier County's continuous count stations -
# machines in the road counting cars 24/7. Overlay that on the temperature gap
# and you can finally see whether the two move together.
#
# The hypothesis worth killing: people don't respond to weather at all. They
# book flights around Thanksgiving, Christmas and Easter. If traffic turns on
# holidays rather than on temperature, the whole thermal story is decoration.
# =============================================================================

library(tidyverse)
library(lubridate)
library(scales)

theme_set(theme_minimal(base_size = 12))

traffic <- read_csv("data/collier_daily_traffic.csv", show_col_types = FALSE)
weather <- read_csv("data/weather_daily.csv",         show_col_types = FALSE)

# -----------------------------------------------------------------------------
# 0. HURRICANES - find them before they find you
# -----------------------------------------------------------------------------
# 2024 was a bad storm year for southwest Florida, and it is written all over
# this data. The first run of this script reported the quietest stretch of the
# year as "29 Sep", which sounded like a plausible late-summer lull. It wasn't.
# It was Hurricane Helene.
#
# The giveaway is the shape: traffic SPIKES as people evacuate, then collapses
# on landfall day.
#     7 Oct  1.239  |  8 Oct  1.528   <- everyone leaving at once
#     9 Oct  0.302                    <- Milton landfall, roads empty
#
# A hurricane looks like a seasonal signal to any code that isn't told
# otherwise. Leaving these in would have put a storm in a chart about weather
# preference and called it migration.
STORMS <- tribble(
  ~name,     ~from,          ~to,
  "Debby",   "2024-08-03",   "2024-08-06",
  "Helene",  "2024-09-24",   "2024-09-29",
  "Milton",  "2024-10-06",   "2024-10-14"
) %>%
  mutate(from = as.Date(from), to = as.Date(to))

# map2() walks two vectors in step, calling the function on each pair -
# here expanding every (from, to) into the run of days between them.
# list_c() then flattens the list of runs into one vector of dates.
# (summarise() cannot do this: it must return exactly one row per group.)
storm_days <- map2(STORMS$from, STORMS$to, ~ seq(.x, .y, by = "day")) %>%
  list_c()

cat("Excluding", length(storm_days), "hurricane-affected days\n")

traffic <- traffic %>% filter(!date %in% storm_days)

# -----------------------------------------------------------------------------
# 1. Keep only stations that ran (nearly) all year
# -----------------------------------------------------------------------------
# Several stations have big gaps - a broken sensor in July would fake a summer
# collapse, which is exactly the signal we're testing for. Ruthless filtering
# matters more than sample size here.
coverage <- traffic %>%
  count(site, name = "days") %>%
  arrange(desc(days))

print(coverage)

# 330, not 350: we just deleted 19 hurricane days, so a station that ran all
# year now tops out at 347. A threshold of 350 would silently select NOTHING
# and every downstream number would come back empty rather than wrong - which
# is the good case. Watch for filters that interact like this.
good_sites <- coverage %>% filter(days >= 330) %>% pull(site)
message("Using ", length(good_sites), " stations with >=330 days: ",
        paste(good_sites, collapse = ", "))

# -----------------------------------------------------------------------------
# 2. Turn volumes into an INDEX so stations are comparable
# -----------------------------------------------------------------------------
# A rural station on 3,600 cars/day and I-75 on 109,000 can't be averaged
# directly. Divide each by its own annual mean: 1.0 = a typical day at that
# station, 1.3 = 30% busier than normal. Now they're on one scale.
idx <- traffic %>%
  filter(site %in% good_sites) %>%
  group_by(site) %>%
  mutate(index = volume / mean(volume)) %>%
  ungroup()

# Average across stations, then smooth. Weekly rhythm (quiet Sundays) would
# otherwise drown the seasonal signal we care about.
county <- idx %>%
  group_by(date) %>%
  summarise(index = mean(index), .groups = "drop") %>%
  arrange(date) %>%
  mutate(index_smooth = as.numeric(stats::filter(index, rep(1/7, 7), sides = 2)))

# -----------------------------------------------------------------------------
# 3. The temperature gap for the same days
# -----------------------------------------------------------------------------
gap <- weather %>%
  group_by(date, role) %>%
  summarise(temp = mean(temp_mean, na.rm = TRUE), .groups = "drop") %>%
  pivot_wider(names_from = role, values_from = temp) %>%
  mutate(gap = south - north) %>%
  arrange(date) %>%
  mutate(gap_smooth = as.numeric(stats::filter(gap, rep(1/7, 7), sides = 2))) %>%
  filter(year(date) == 2024)

both <- county %>%
  inner_join(select(gap, date, gap_smooth), by = "date") %>%
  filter(!is.na(index_smooth), !is.na(gap_smooth))

# -----------------------------------------------------------------------------
# 4. How big is the snowbird surge?
# -----------------------------------------------------------------------------
# Report MONTHLY MEDIANS, not the single best and worst day. One extreme day
# is exactly what a storm (or a sensor fault, or a road closure) produces, and
# min/max hunt for precisely those. Medians over a month can't be moved by one
# bad day.
monthly <- county %>%
  mutate(month = month(date, label = TRUE)) %>%
  group_by(month) %>%
  summarise(index = median(index), .groups = "drop")

peak_month <- monthly %>% slice_max(index, n = 1)
low_month  <- monthly %>% slice_min(index, n = 1)

cat("\n=== THE SNOWBIRD SURGE, 2024 (storms removed) ===\n")
print(as.data.frame(monthly %>% mutate(index = round(index, 3))), row.names = FALSE)
cat("\nBusiest month: ", as.character(peak_month$month), " at ",
    round(peak_month$index, 3), "x normal\n", sep = "")
cat("Quietest month:", as.character(low_month$month),  " at ",
    round(low_month$index, 3), "x normal\n", sep = "")
cat("Peak month is ", round(100 * (peak_month$index / low_month$index - 1)),
    "% above the quietest\n", sep = "")

# Per-station, because these roads are not the same kind of road.
cat("\n--- Seasonal swing by station ---\n")
idx %>%
  mutate(month = month(date)) %>%
  group_by(site, month) %>%
  summarise(m = median(index), .groups = "drop") %>%
  group_by(site) %>%
  summarise(
    peak  = round(max(m), 2),
    low   = round(min(m), 2),
    swing = paste0(round(100 * (max(m) / min(m) - 1)), "%"),
    .groups = "drop"
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

# -----------------------------------------------------------------------------
# 5. When does traffic turn, vs when does the weather turn?
# -----------------------------------------------------------------------------
# Define the traffic season as "busier than an average day" (index >= 1).
cross_up <- both %>%
  filter(month(date) %in% 9:12, index_smooth >= 1) %>%
  slice_min(date, n = 1) %>% pull(date)

cross_dn <- both %>%
  filter(month(date) %in% 3:7, index_smooth < 1) %>%
  slice_min(date, n = 1) %>% pull(date)

# Same question of the thermometer, using script 03's 25 deg F threshold.
THRESHOLD <- 25
temp_up <- both %>%
  filter(month(date) %in% 9:12, gap_smooth >= THRESHOLD) %>%
  slice_min(date, n = 1) %>% pull(date)

temp_dn <- both %>%
  filter(month(date) %in% 3:7, gap_smooth < THRESHOLD) %>%
  slice_min(date, n = 1) %>% pull(date)

cat("\n=== TRAFFIC vs THERMOMETER (2024) ===\n")
cat("Traffic picks up:     ", format(cross_up, "%d %b"), "\n")
cat("Thermal window opens: ", format(temp_up,  "%d %b"), "\n")
cat("  -> traffic lags by ", as.numeric(cross_up - temp_up), " days\n", sep = "")
cat("Traffic drops off:    ", format(cross_dn, "%d %b"), "\n")
cat("Thermal window closes:", format(temp_dn,  "%d %b"), "\n")
cat("  -> traffic lags by ", as.numeric(cross_dn - temp_dn), " days\n", sep = "")

# -----------------------------------------------------------------------------
# 6. Are they actually correlated day to day?
# -----------------------------------------------------------------------------
r <- cor(both$index_smooth, both$gap_smooth)
cat("\nCorrelation (traffic index vs temperature gap): r = ", round(r, 3),
    "  (r^2 = ", round(r^2, 3), ")\n", sep = "")

# =============================================================================
# CHARTS
# =============================================================================

# --- The money chart: both curves, one year --------------------------------
# Two different units on one plot needs a second axis. Rescale the gap onto
# the index's range, then label the right axis in the original units.
rng_i <- range(both$index_smooth)
rng_g <- range(both$gap_smooth)
to_idx <- function(g) (g - rng_g[1]) / diff(rng_g) * diff(rng_i) + rng_i[1]
to_gap <- function(i) (i - rng_i[1]) / diff(rng_i) * diff(rng_g) + rng_g[1]

p1 <- ggplot(both, aes(date)) +
  geom_line(aes(y = to_idx(gap_smooth), colour = "Temperature gap"), linewidth = 1) +
  geom_line(aes(y = index_smooth,       colour = "Traffic"),         linewidth = 1.1) +
  geom_hline(yintercept = 1, linetype = "dotted", colour = "grey40") +
  scale_y_continuous(
    name = "Traffic (1.0 = an average day)",
    sec.axis = sec_axis(~ to_gap(.), name = "Temperature gap (deg F)")
  ) +
  scale_x_date(date_labels = "%b", date_breaks = "1 month") +
  scale_colour_manual(values = c("Traffic" = "#c1121f",
                                 "Temperature gap" = "#2a6f97")) +
  labs(
    title    = "Do snowbirds follow the thermometer?",
    subtitle = paste0("Collier County daily traffic vs the Naples-minus-north ",
                      "temperature gap, 2024 (7-day smoothed)"),
    x = NULL, colour = NULL
  ) +
  theme(legend.position = "top")

ggsave("output/04_traffic_vs_temperature.png", p1, width = 10, height = 5.5, dpi = 150)

# --- Each station separately ------------------------------------------------
p2 <- idx %>%
  group_by(site) %>%
  arrange(date) %>%
  mutate(smooth = as.numeric(stats::filter(index, rep(1/7, 7), sides = 2))) %>%
  ungroup() %>%
  filter(!is.na(smooth)) %>%
  ggplot(aes(date, smooth, colour = site)) +
  geom_line(linewidth = 0.9) +
  geom_hline(yintercept = 1, linetype = "dotted", colour = "grey40") +
  scale_x_date(date_labels = "%b", date_breaks = "1 month") +
  labs(
    title    = "Seasonal swing, station by station",
    subtitle = "1.0 = that station's own average day. Not every road is a snowbird road.",
    x = NULL, y = "Index", colour = "Station"
  )

ggsave("output/05_stations.png", p2, width = 10, height = 5.5, dpi = 150)

# --- Fifty years of growth --------------------------------------------------
if (file.exists("data/collier_hist_aadt.csv")) {
  hist_aadt <- read_csv("data/collier_hist_aadt.csv", show_col_types = FALSE)

  p3 <- hist_aadt %>%
    group_by(year) %>%
    summarise(median_aadt = median(aadt), sites = n(), .groups = "drop") %>%
    filter(sites >= 20) %>%     # ignore years with only a handful of stations
    ggplot(aes(year, median_aadt)) +
    geom_line(colour = "#3d5a80", linewidth = 1.1) +
    geom_point(size = 1.6, colour = "#3d5a80") +
    scale_y_continuous(labels = comma) +
    labs(
      title    = "Fifty years of Naples traffic",
      subtitle = "Median AADT across Collier County counting sites",
      x = NULL, y = "Median AADT"
    )

  ggsave("output/06_fifty_years.png", p3, width = 10, height = 5, dpi = 150)
}

message("\nCharts written to output/")
