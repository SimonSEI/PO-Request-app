# =============================================================================
# 03 - THE MIGRATION WINDOW
# =============================================================================
# The central idea:
#
#   Snowbirds are pulled south by a TEMPERATURE GAP, not by absolute warmth.
#   Define  gap = (Naples temp) - (average temp back home).
#   When that gap is big, Naples is worth the trip. When it closes, go home.
#
# So for every year we find two dates:
#   OPENS  - when the gap first gets big in the autumn  ("worth going")
#   CLOSES - when the gap shrinks again in the spring   ("time to leave")
#
# Then we ask the real question: over 26 years, have those dates MOVED?
# If northern winters are warming faster than Florida, the window should be
# getting shorter - and the snowbird season with it.
# =============================================================================

library(tidyverse)
library(lubridate)
library(scales)

theme_set(theme_minimal(base_size = 12))

weather <- read_csv("data/weather_daily.csv", show_col_types = FALSE)

# -----------------------------------------------------------------------------
# 1. Build the temperature gap, one row per day
# -----------------------------------------------------------------------------
# Reshape: we want Naples in one column and the northern average in another.
daily_gap <- weather %>%
  group_by(date, role) %>%
  summarise(temp = mean(temp_mean, na.rm = TRUE), .groups = "drop") %>%
  pivot_wider(names_from = role, values_from = temp) %>%   # long -> wide
  mutate(gap = south - north) %>%
  arrange(date)

# Smooth with a 7-day rolling average. Single days are noisy; one cold Tuesday
# in Chicago should not count as "the season starting".
# We write stats::filter() in full because dplyr also has a filter() and R
# would otherwise reach for the wrong one.
daily_gap <- daily_gap %>%
  mutate(gap_smooth = as.numeric(stats::filter(gap, rep(1/7, 7), sides = 2)))

# -----------------------------------------------------------------------------
# 2. Define a "season year" running July -> June
# -----------------------------------------------------------------------------
# A snowbird season straddles New Year, so calendar years would cut it in half.
# Season 2015 = July 2015 through June 2016.
daily_gap <- daily_gap %>%
  mutate(
    season_year = if_else(month(date) >= 7, year(date), year(date) - 1L),
    month_num   = month(date)
  )

# -----------------------------------------------------------------------------
# 3. Find when the window opens and closes each year
# -----------------------------------------------------------------------------
# THRESHOLD is a judgement call, not a fact. 25 means "Naples is 25 degrees F
# warmer than home". Change this number and re-run: watching how much the
# answer moves is the honest way to check whether a finding is real.
THRESHOLD <- 25

# Helper: first date in a set of months where the gap is above/below the line.
first_crossing <- function(dates, gap, months_in, want_above) {
  hit <- if (want_above) gap >= THRESHOLD else gap < THRESHOLD
  ok  <- hit & (month(dates) %in% months_in)
  if (!any(ok, na.rm = TRUE)) return(as.Date(NA))
  min(dates[which(ok)])
}

window_dates <- daily_gap %>%
  filter(!is.na(gap_smooth)) %>%
  group_by(season_year) %>%
  summarise(
    opens    = first_crossing(date, gap_smooth, 9:12, want_above = TRUE),
    closes   = first_crossing(date, gap_smooth, 3:6,  want_above = FALSE),
    peak_gap = max(gap_smooth),
    mean_gap = mean(gap_smooth),
    .groups  = "drop"
  ) %>%
  mutate(window_days = as.numeric(closes - opens)) %>%
  # Drop the part-seasons at the very start and end of our data
  filter(!is.na(opens), !is.na(closes))

print(window_dates, n = 30)
write_csv(window_dates, "output/migration_window_by_year.csv")

# -----------------------------------------------------------------------------
# 4. Is the window shifting? Fit a straight line through each date.
# -----------------------------------------------------------------------------
# lm() = "linear model", the workhorse for fitting a trend in R.
# We convert dates to "days since 1 July" so they become plain numbers.
trend_data <- window_dates %>%
  mutate(
    opens_doy  = as.numeric(opens  - make_date(season_year, 7, 1)),
    closes_doy = as.numeric(closes - make_date(season_year, 7, 1))
  )

# How to read these tables: the `Estimate` on the season_year row is the
# change per year, in days. `Pr(>|t|)` is the p-value - under 0.05 is the
# usual crude bar for "probably not just noise".
message("\n--- Is the season OPENING later? (days/year) ---")
print(summary(lm(opens_doy ~ season_year, data = trend_data))$coefficients)

message("\n--- Is the season CLOSING earlier? (days/year) ---")
print(summary(lm(closes_doy ~ season_year, data = trend_data))$coefficients)

message("\n--- Is the window getting SHORTER? (days/year) ---")
print(summary(lm(window_days ~ season_year, data = trend_data))$coefficients)

# =============================================================================
# CHARTS
# =============================================================================

# --- Chart 1: the average shape of a year -----------------------------------
climatology <- daily_gap %>%
  filter(!is.na(gap_smooth)) %>%
  mutate(doy = yday(date)) %>%
  group_by(doy) %>%
  summarise(gap = mean(gap_smooth), .groups = "drop")

p1 <- ggplot(climatology, aes(doy, gap)) +
  geom_area(fill = "#2a6f97", alpha = 0.15) +
  geom_line(colour = "#2a6f97", linewidth = 1) +
  geom_hline(yintercept = THRESHOLD, linetype = "dashed", colour = "#c1121f") +
  annotate("text", x = 185, y = THRESHOLD + 2.5,
           label = paste0("migration threshold (", THRESHOLD, " deg F)"),
           colour = "#c1121f", size = 3.5, hjust = 0) +
  scale_x_continuous(
    breaks = c(1, 60, 121, 182, 244, 305),
    labels = c("Jan", "Mar", "May", "Jul", "Sep", "Nov")
  ) +
  labs(
    title    = "How much warmer is Naples than back home?",
    subtitle = "Average daily gap, Naples FL minus six northern origin cities, 2000-2026",
    x = NULL, y = "Temperature gap (deg F)"
  )

ggsave("output/01_temperature_gap_year.png", p1, width = 9, height = 5, dpi = 150)

# --- Chart 2: has the window moved? -----------------------------------------
p2 <- window_dates %>%
  select(season_year, opens, closes) %>%
  pivot_longer(c(opens, closes), names_to = "edge", values_to = "date") %>%
  mutate(
    # Put every year on a common axis: days since 1 July of that season
    days_from_july = as.numeric(date - make_date(season_year, 7, 1)),
    edge = factor(edge, levels = c("opens", "closes"),
                  labels = c("Window opens (autumn)", "Window closes (spring)"))
  ) %>%
  ggplot(aes(season_year, days_from_july, colour = edge)) +
  geom_point(size = 2.2, alpha = 0.8) +
  geom_smooth(method = "lm", se = TRUE, linewidth = 0.9) +
  scale_colour_manual(values = c("#e07a5f", "#3d5a80")) +
  scale_y_continuous(
    breaks = c(92, 153, 214, 275, 336),
    labels = c("1 Oct", "1 Dec", "1 Feb", "1 Apr", "1 Jun")
  ) +
  labs(
    title    = "Is the snowbird window shifting?",
    subtitle = paste0("Dates the Naples-vs-north temperature gap crosses ",
                      THRESHOLD, " deg F. Shaded band = uncertainty in the trend."),
    x = "Season (year it began)", y = NULL, colour = NULL
  ) +
  theme(legend.position = "top")

ggsave("output/02_window_shift.png", p2, width = 9, height = 5.5, dpi = 150)

# --- Chart 3: how long is the season? ---------------------------------------
p3 <- ggplot(window_dates, aes(season_year, window_days)) +
  geom_col(fill = "#3d5a80", alpha = 0.85) +
  geom_smooth(method = "lm", se = FALSE, colour = "#e07a5f", linewidth = 1) +
  labs(
    title    = "Length of the thermal snowbird season",
    subtitle = "Days per year that Naples is meaningfully warmer than the north",
    x = "Season (year it began)", y = "Days"
  )

ggsave("output/03_window_length.png", p3, width = 9, height = 5, dpi = 150)

message("\nCharts written to output/")
