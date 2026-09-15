# =============================================================================
# 07 - DOES PROPER WEIGHTING RESCUE THE FINDING?
# =============================================================================
# Script 03 found the migration window opening later, then the dashboard showed
# it only held at one hand-picked threshold. Two things could have caused that:
#
#   (a) the effect is real, but my six guessed cities were too noisy to see it
#   (b) there is no effect
#
# Now we have measured origin states weighted by actual migrant numbers. If (a)
# is right, the trend should firm up. If it stays fragile, that is the answer.
#
# The honest way to test this is not to pick a threshold and report it. It is
# to sweep EVERY plausible threshold and show the whole picture.
# =============================================================================

library(tidyverse)
library(lubridate)
library(scales)

theme_set(theme_minimal(base_size = 12))

states <- read_csv("data/origin_states.csv",     show_col_types = FALSE)
wgap   <- read_csv("data/weighted_gap.csv",      show_col_types = FALSE)

# -----------------------------------------------------------------------------
# 1. Where people come from
# -----------------------------------------------------------------------------
p1 <- states %>%
  slice_head(n = 15) %>%
  mutate(state = fct_reorder(state, people)) %>%
  ggplot(aes(people, state)) +
  geom_col(fill = "#3d5a80", alpha = 0.9) +
  geom_text(aes(label = paste0(round(100 * share, 1), "%")),
            hjust = -0.15, size = 3.5) +
  scale_x_continuous(labels = comma, expand = expansion(c(0, 0.13))) +
  labs(
    title    = "Where Naples newcomers come from",
    subtitle = "People moving into Collier County FL from out of state, IRS tax records 2022-23",
    x = "People", y = NULL
  )

ggsave("output/07_origin_states.png", p1, width = 9, height = 5.5, dpi = 150)

# -----------------------------------------------------------------------------
# 2. The window calculation, reusable
# -----------------------------------------------------------------------------
# Same logic as script 03, but as a function so we can run it hundreds of times
# across different thresholds. Anything you want to test over a range of
# settings has to become a function first.
window_trend <- function(gap_col, threshold) {

  d <- wgap %>%
    transmute(
      date,
      g = .data[[gap_col]]
    ) %>%
    arrange(date) %>%
    mutate(
      g_smooth    = as.numeric(stats::filter(g, rep(1/7, 7), sides = 2)),
      season_year = if_else(month(date) >= 7, year(date), year(date) - 1L)
    ) %>%
    filter(!is.na(g_smooth))

  first_cross <- function(dates, g, months_in, above) {
    hit <- if (above) g >= threshold else g < threshold
    ok  <- hit & (month(dates) %in% months_in)
    if (!any(ok, na.rm = TRUE)) return(as.Date(NA))
    min(dates[which(ok)])
  }

  w <- d %>%
    group_by(season_year) %>%
    summarise(
      opens  = first_cross(date, g_smooth, 9:12, TRUE),
      closes = first_cross(date, g_smooth, 3:6,  FALSE),
      .groups = "drop"
    ) %>%
    filter(!is.na(opens), !is.na(closes)) %>%
    mutate(
      opens_d  = as.numeric(opens  - make_date(season_year, 7, 1)),
      closes_d = as.numeric(closes - make_date(season_year, 7, 1)),
      length   = as.numeric(closes - opens)
    )

  if (nrow(w) < 8) return(NULL)

  grab <- function(col) {
    fit <- lm(reformulate("season_year", col), data = w)
    co  <- summary(fit)$coefficients
    tibble(slope_decade = co["season_year", "Estimate"] * 10,
           p            = co["season_year", "Pr(>|t|)"])
  }

  bind_rows(
    grab("opens_d")  %>% mutate(measure = "Opens"),
    grab("closes_d") %>% mutate(measure = "Closes"),
    grab("length")   %>% mutate(measure = "Length")
  ) %>%
    mutate(threshold = threshold, weighting = gap_col, seasons = nrow(w))
}

# -----------------------------------------------------------------------------
# 3. Sweep every threshold, both weightings
# -----------------------------------------------------------------------------
sweep <- expand_grid(
  gap_col   = c("gap_plain", "gap_weighted"),
  threshold = seq(12, 36, by = 1)
) %>%
  pmap_dfr(function(gap_col, threshold) window_trend(gap_col, threshold))

write_csv(sweep, "output/threshold_sweep.csv")

cat("\n=== How often is the 'opens later' trend significant? ===\n")
sweep %>%
  filter(measure == "Opens") %>%
  group_by(weighting) %>%
  summarise(
    thresholds_tested = n(),
    significant_p05   = sum(p < 0.05),
    positive_slope    = sum(slope_decade > 0),
    median_slope      = round(median(slope_decade), 2),
    .groups = "drop"
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

# -----------------------------------------------------------------------------
# 4. Chart it - the whole sensitivity surface, not one cherry-picked number
# -----------------------------------------------------------------------------
p2 <- sweep %>%
  mutate(
    weighting = recode(weighting,
                       gap_plain    = "States weighted equally",
                       gap_weighted = "Weighted by migrants sent"),
    sig = if_else(p < 0.05, "p < 0.05", "not significant")
  ) %>%
  ggplot(aes(threshold, slope_decade)) +
  geom_hline(yintercept = 0, colour = "grey30") +
  geom_line(aes(group = measure), colour = "grey75") +
  geom_point(aes(colour = sig), size = 2) +
  facet_grid(measure ~ weighting) +
  scale_colour_manual(values = c("p < 0.05" = "#c1121f",
                                 "not significant" = "grey55")) +
  labs(
    title    = "The finding depends entirely on where you draw the line",
    subtitle = paste0("Trend in window dates (days per decade) at every plausible ",
                      "threshold.\nAbove zero = later, below zero = earlier."),
    x = "Migration threshold (deg F)", y = "Days per decade", colour = NULL
  ) +
  theme(legend.position = "top")

ggsave("output/08_threshold_sweep.png", p2, width = 10, height = 7, dpi = 150)

# -----------------------------------------------------------------------------
# 5. Weighted vs unweighted, through the year
# -----------------------------------------------------------------------------
p3 <- wgap %>%
  mutate(doy = yday(date)) %>%
  group_by(doy) %>%
  summarise(
    Equal    = mean(gap_plain,    na.rm = TRUE),
    Weighted = mean(gap_weighted, na.rm = TRUE),
    .groups  = "drop"
  ) %>%
  pivot_longer(c(Equal, Weighted), names_to = "method", values_to = "gap") %>%
  ggplot(aes(doy, gap, colour = method)) +
  geom_line(linewidth = 1) +
  scale_x_continuous(breaks = c(1, 60, 121, 182, 244, 305),
                     labels = c("Jan", "Mar", "May", "Jul", "Sep", "Nov")) +
  scale_colour_manual(values = c("Equal" = "grey55", "Weighted" = "#2a6f97")) +
  labs(
    title    = "Weighting states by migrants barely moves the curve",
    subtitle = "Naples minus origin-state temperature, averaged 2000-2026",
    x = NULL, y = "Temperature gap (deg F)", colour = NULL
  ) +
  theme(legend.position = "top")

ggsave("output/09_weighted_vs_plain.png", p3, width = 9, height = 5, dpi = 150)

message("\nCharts written to output/")
