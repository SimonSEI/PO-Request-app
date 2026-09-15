# =============================================================================
# 14 - DO QUIET HURRICANE SEASONS BRING SNOWBIRDS BACK SOONER?
# =============================================================================
# A reasonable intuition: no storms means no disruption, so people arrive
# earlier. Worth testing rather than assuming, because there are arguments both
# ways and one of them is easy to miss.
#
# ARGUMENTS FOR (quiet season -> earlier arrivals)
#   - no evacuations, no closed airport, no damaged house to repair first
#   - no news coverage putting people off
#
# ARGUMENTS AGAINST
#   - hurricane risk is judged BEFORE the season, not after. You cannot know in
#     September that October will be quiet, and flights are booked months out.
#   - script 05 found arrivals track the CALENDAR, not conditions: traffic lags
#     temperature by ~25 days at both ends. Thanksgiving does not move.
#
# AND THE CONFOUND THAT MATTERS MOST
#   El Nino suppresses Atlantic hurricanes AND warms northern winters. Those
#   push arrival timing in OPPOSITE directions: fewer storms might pull people
#   earlier, but a mild winter up north removes the reason to leave at all.
#   Any raw correlation between quiet seasons and arrival timing is really
#   measuring both at once.
#
# METHOD: use the Oceanic Nino Index as the instrument. It runs back to 1950,
# it is exogenous (nobody's travel plans move the Pacific), and it is the main
# driver of Atlantic hurricane activity. Then check the northern-temperature
# pathway separately to see which effect dominates.
# =============================================================================

local({
  lib <- file.path(getwd(), ".Rlib")
  if (dir.exists(lib)) .libPaths(c(lib, .libPaths()))
})

suppressPackageStartupMessages({
  library(tidyverse)
  library(lubridate)
})

theme_set(theme_minimal(base_size = 12))

# -----------------------------------------------------------------------------
# 1. ONI history
# -----------------------------------------------------------------------------
oni_raw <- read.table("https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
                      header = TRUE, stringsAsFactors = FALSE) %>% as_tibble()

# ASO (Aug-Sep-Oct) is the standard window for describing a hurricane season's
# ENSO state - it covers the climatological peak of Atlantic activity.
oni_autumn <- oni_raw %>%
  filter(SEAS == "ASO") %>%
  transmute(season = as.integer(YR), oni = as.numeric(ANOM)) %>%
  mutate(
    enso = case_when(oni >=  0.5 ~ "El Nino (storms suppressed)",
                     oni <= -0.5 ~ "La Nina (storms enhanced)",
                     TRUE        ~ "Neutral")
  )

message("ONI autumn values: ", min(oni_autumn$season), "-", max(oni_autumn$season))

# -----------------------------------------------------------------------------
# 2. Arrival timing per season (from script 11)
# -----------------------------------------------------------------------------
timing <- read_csv("output/rsw_arrival_timing.csv", show_col_types = FALSE)

dat <- timing %>%
  inner_join(oni_autumn, by = "season") %>%
  filter(!excluded)          # storms and COVID already removed by script 11

message(nrow(dat), " clean seasons with ONI matched")

# -----------------------------------------------------------------------------
# 3. The direct test
# -----------------------------------------------------------------------------
cat("\n=====================================================================\n")
cat("  DOES A QUIET (EL NINO) SEASON BRING PEOPLE BACK SOONER?\n")
cat("=====================================================================\n\n")

cat("Autumn share = fraction of the season's arrivals landing Oct-Dec.\n")
cat("HIGHER autumn share = arriving earlier.\n\n")

dat %>%
  group_by(enso) %>%
  summarise(
    seasons = n(),
    `mean autumn share` = sprintf("%.1f%%", 100 * mean(autumn_share)),
    `mean centroid` = round(mean(centroid), 3),
    .groups = "drop"
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

fit_share <- lm(autumn_share ~ oni, data = dat)
fit_cent  <- lm(centroid ~ oni, data = dat)

co <- function(f) summary(f)$coefficients["oni", c("Estimate", "Pr(>|t|)")]

cat("\n--- Correlation with ONI (higher ONI = El Nino = fewer hurricanes) ---\n")
cat(sprintf("Autumn share: %+.3f points per 1.0 ONI   p = %.3f\n",
            100 * co(fit_share)[1], co(fit_share)[2]))
cat(sprintf("Centroid:     %+.3f months per 1.0 ONI   p = %.3f\n",
            co(fit_cent)[1], co(fit_cent)[2]))
cat("  (positive autumn share / negative centroid = arriving EARLIER)\n")

r <- cor(dat$oni, dat$autumn_share)
cat(sprintf("\nPlain correlation r = %+.3f  (r-squared %.3f, n = %d)\n",
            r, r^2, nrow(dat)))

# -----------------------------------------------------------------------------
# 4. What the storm seasons themselves did
# -----------------------------------------------------------------------------
# The cleanest natural experiment available: seasons a major storm actually hit
# southwest Florida, against everything else.
all_timing <- read_csv("output/rsw_arrival_timing.csv", show_col_types = FALSE) %>%
  filter(!covid)

cat("\n--- Seasons a hurricane actually hit southwest Florida ---\n")
all_timing %>%
  group_by(`hit by a storm` = storm) %>%
  summarise(
    seasons = n(),
    `autumn share` = sprintf("%.1f%%", 100 * mean(autumn_share)),
    `centroid` = round(mean(centroid), 3),
    .groups = "drop"
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

storm_diff <- mean(all_timing$autumn_share[all_timing$storm]) -
              mean(all_timing$autumn_share[!all_timing$storm])
cat(sprintf("\nStorm seasons run %+.1f percentage points on autumn share.\n",
            100 * storm_diff))

# -----------------------------------------------------------------------------
# 5. The confound: does El Nino also warm the north?
# -----------------------------------------------------------------------------
# If it does, the hurricane pathway and the temperature pathway pull in
# opposite directions, and the raw correlation above is a blend of the two.
cat("\n--- The confound: El Nino and northern winter temperature ---\n")

north <- read_csv("data/origin_state_temps.csv", show_col_types = FALSE) %>%
  mutate(season = if_else(month(date) >= 7, year(date), year(date) - 1L)) %>%
  filter(month(date) %in% c(10, 11, 12)) %>%
  group_by(season) %>%
  summarise(north_autumn = weighted.mean(temp, people, na.rm = TRUE), .groups = "drop")

conf <- north %>% inner_join(oni_autumn, by = "season")

if (nrow(conf) >= 8) {
  fit_conf <- lm(north_autumn ~ oni, data = conf)
  cc <- summary(fit_conf)$coefficients["oni", c("Estimate", "Pr(>|t|)")]
  cat(sprintf("Northern autumn temperature: %+.2f F per 1.0 ONI   p = %.3f  (n = %d)\n",
              cc[1], cc[2], nrow(conf)))
  cat(if (cc[1] > 0)
        "  El Nino autumns ARE warmer up north - which pushes arrivals LATER,\n  working against the fewer-hurricanes effect.\n"
      else
        "  El Nino autumns are not warmer up north here, so the two pathways\n  do not obviously cancel.\n")
}

# -----------------------------------------------------------------------------
# 6. Verdict
# -----------------------------------------------------------------------------
cat("\n=====================================================================\n")
cat("  VERDICT\n")
cat("=====================================================================\n")

p_share <- co(fit_share)[2]
e_share <- co(fit_share)[1]

if (p_share < 0.05 && e_share > 0) {
  cat("Quiet (El Nino) seasons DO show earlier arrivals, significantly.\n")
} else if (p_share < 0.05 && e_share < 0) {
  cat("Quiet (El Nino) seasons show LATER arrivals, significantly - the\n")
  cat("opposite of the intuition. The warm-northern-winter pathway wins.\n")
} else {
  cat(sprintf("No significant relationship (p = %.2f). Across %d seasons, how\n",
              p_share, nrow(dat)))
  cat("quiet the hurricane season was does not predict when people arrive.\n")
  cat("\nThe likely reason: hurricane risk is judged in advance and priced into\n")
  cat("plans months ahead, so the ABSENCE of storms cannot pull anyone earlier -\n")
  cat("nobody knows it was quiet until it already is. A storm that actually\n")
  cat("lands is a different matter, and that shows up below.\n")
}

write_csv(dat, "output/hurricane_timing_test.csv")

# -----------------------------------------------------------------------------
# 7. Chart
# -----------------------------------------------------------------------------
p <- ggplot(dat, aes(oni, 100 * autumn_share)) +
  geom_vline(xintercept = c(-0.5, 0.5), linetype = "dotted", colour = "grey55") +
  geom_point(aes(colour = enso), size = 2.6, alpha = 0.85) +
  geom_smooth(method = "lm", se = TRUE, colour = "#2a6f97", linewidth = 1) +
  annotate("text", x = -1.6, y = Inf, label = "more hurricanes", vjust = 1.6,
           size = 3.3, colour = "grey40") +
  annotate("text", x =  1.6, y = Inf, label = "fewer hurricanes", vjust = 1.6,
           size = 3.3, colour = "grey40") +
  scale_colour_manual(values = c("El Nino (storms suppressed)" = "#c1121f",
                                 "Neutral" = "grey55",
                                 "La Nina (storms enhanced)" = "#3d5a80")) +
  labs(
    title = "Do quiet hurricane seasons bring snowbirds back sooner?",
    subtitle = paste0("Each point is one season. Higher = arriving earlier.\n",
                      sprintf("r = %+.2f across %d clean seasons - ", r, nrow(dat)),
                      if (p_share >= 0.05) "no significant relationship."
                      else "significant relationship."),
    x = "Autumn ONI  (negative = La Nina, positive = El Nino)",
    y = "Autumn share of arrivals (%)", colour = NULL
  ) +
  theme(legend.position = "top")

ggsave("output/14_hurricanes_vs_timing.png", p, width = 10, height = 5.5, dpi = 150)
message("\nChart written to output/14_hurricanes_vs_timing.png")
