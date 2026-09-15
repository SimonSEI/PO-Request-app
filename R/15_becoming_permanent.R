# =============================================================================
# 15 - ARE SNOWBIRDS BECOMING PERMANENT RESIDENTS?
# =============================================================================
# Two separate questions, and they need different instruments:
#
#   1. ARE MORE PEOPLE MOVING HERE FOR GOOD?
#      The IRS records every household that changes its tax address. Changing
#      your tax address IS the act of becoming a permanent resident - it is not
#      a proxy for it. Twelve years are published, 2011-12 through 2022-23.
#
#   2. ARE THE ONES WHO STILL COME SEASONALLY STAYING LONGER?
#      Different question, different data. If stays are lengthening, the
#      SHOULDER months either side of the season should be growing relative to
#      the peak - people arriving before the rush and leaving after it. RSW
#      passenger data gives 43 seasons of that shape.
#
# WHY BOTH MATTER TOGETHER: a place can have rising permanent migration while
# its seasonal visitors stay exactly as long as they always did. Those are
# different populations behaving differently, and one number cannot describe
# both.
#
# THE LIMIT WORTH STATING: IRS data cannot see a snowbird who keeps their
# northern domicile - which is most of them, often deliberately for tax
# reasons. So question 1 measures the flow of people CONVERTING to permanent,
# not the stock of seasonal residents.
# =============================================================================

local({
  lib <- file.path(getwd(), ".Rlib")
  if (dir.exists(lib)) .libPaths(c(lib, .libPaths()))
})

suppressPackageStartupMessages({
  library(tidyverse)
  library(lubridate)
  library(scales)
})

theme_set(theme_minimal(base_size = 15))

COLLIER_STATE  <- "12"
COLLIER_COUNTY <- "021"

dir.create("data/raw", showWarnings = FALSE, recursive = TRUE)

# Northern states only - we are asking about snowbirds, not about people moving
# up from Miami. These are the ones with a genuine winter.
NORTHERN <- c("IL","NY","MA","NJ","PA","OH","MI","CT","MN","WI","IN","RI",
              "NH","VT","ME","IA","ND","SD","NE","MO","MD","DE","WV","KY")

# -----------------------------------------------------------------------------
# 1. Twelve years of permanent moves into Collier County
# -----------------------------------------------------------------------------
periods <- c("1112","1213","1314","1415","1516","1617",
             "1718","1819","1920","2021","2122","2223")

read_inflow <- function(p) {
  f <- file.path("data", "raw", paste0("countyinflow", p, ".csv"))
  if (!file.exists(f)) {
    message("  downloading ", p)
    ok <- try(download.file(paste0("https://www.irs.gov/pub/irs-soi/countyinflow", p, ".csv"),
                            f, mode = "wb", quiet = TRUE), silent = TRUE)
    if (inherits(ok, "try-error")) return(NULL)
  }

  d <- read_csv(f, col_types = cols(.default = col_character()), progress = FALSE)

  # Column names drift between editions (y2_statefips vs Y2_STATEFIPS etc).
  names(d) <- tolower(names(d))

  need <- c("y2_statefips","y2_countyfips","y1_statefips","y1_state","n1","n2")
  if (!all(need %in% names(d))) {
    message("  unexpected columns in ", p); return(NULL)
  }

  # FIPS PADDING VARIES BETWEEN EDITIONS, and it will cost you years if you
  # do not normalise it. 2011-2020 and 2022-23 store Collier as "12","021";
  # the 2020-21 and 2021-22 files store the same county as "12","21".
  # A string comparison against "021" silently matches nothing in those two
  # years - no error, no warning, just two years quietly missing from a trend.
  # Re-pad everything numerically before comparing.
  d <- d %>%
    mutate(
      y2_statefips  = sprintf("%02d", as.integer(y2_statefips)),
      y2_countyfips = sprintf("%03d", as.integer(y2_countyfips)),
      y1_statefips  = sprintf("%02d", as.integer(y1_statefips))
    )

  d %>%
    filter(y2_statefips == COLLIER_STATE, y2_countyfips == COLLIER_COUNTY) %>%
    filter(!y1_statefips %in% c("96","97","98"),
           !y1_state %in% c("DS","SS","FR"),
           y1_state != "FL") %>%
    transmute(
      period = p,
      # The filing year the move was recorded in - "2223" means tax year 2023.
      year   = 2000L + as.integer(substr(p, 3, 4)),
      state  = y1_state,
      households = as.numeric(n1),
      people     = as.numeric(n2)
    ) %>%
    filter(!is.na(people), people > 0)
}

message("Reading IRS migration, ", length(periods), " years...")
inflow <- map_dfr(periods, read_inflow)

stopifnot(nrow(inflow) > 0)

perm <- inflow %>%
  mutate(northern = state %in% NORTHERN) %>%
  group_by(year) %>%
  summarise(
    total_people    = sum(people),
    northern_people = sum(people[northern]),
    northern_share  = northern_people / total_people,
    .groups = "drop"
  )

write_csv(perm, "data/permanent_moves.csv")

cat("\n=====================================================================\n")
cat("  PERMANENT MOVES INTO COLLIER COUNTY (IRS tax-address changes)\n")
cat("=====================================================================\n\n")

perm %>%
  transmute(
    Year = year,
    `From out of state` = comma(total_people),
    `From northern states` = comma(northern_people),
    `Northern share` = sprintf("%.1f%%", 100 * northern_share)
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

fit_n <- lm(northern_people ~ year, data = perm)
cn <- summary(fit_n)$coefficients["year", c("Estimate","Pr(>|t|)")]

first_n <- perm$northern_people[which.min(perm$year)]
last_n  <- perm$northern_people[which.max(perm$year)]

cat(sprintf("\nNorthern arrivals: %s in %d -> %s in %d  (%+.0f%%)\n",
            comma(first_n), min(perm$year), comma(last_n), max(perm$year),
            100 * (last_n / first_n - 1)))
cat(sprintf("Trend: %+.0f people per year   p = %.4f\n", cn[1], cn[2]))

# ROBUSTNESS. 2020-2022 contain the pandemic relocation wave - 2021 alone is
# 11,566, far above anything before it. A trend that exists only because of
# those three years is a story about COVID, not about snowbirds. Refit without
# them and see whether it survives.
perm_nc <- perm %>% filter(!year %in% c(2020, 2021, 2022))
fit_nc  <- lm(northern_people ~ year, data = perm_nc)
cnc <- summary(fit_nc)$coefficients["year", c("Estimate","Pr(>|t|)")]

cat(sprintf("Excluding the 2020-22 pandemic wave: %+.0f people per year   p = %.4f   (n = %d)\n",
            cnc[1], cnc[2], nrow(perm_nc)))
cat(if (cnc[2] < 0.05)
      "  -> the rise holds up without the pandemic years.\n"
    else
      "  -> WITHOUT the pandemic years the trend is not significant. Most of\n     the apparent rise is the COVID relocation wave, not a steady shift.\n")

# -----------------------------------------------------------------------------
# 2. Are seasonal visitors staying longer?
# -----------------------------------------------------------------------------
# SHOULDER SHARE: October, April and May against the Dec-Mar core. Longer stays
# mean arriving earlier and leaving later, which fattens the shoulders whether
# or not the total grows.
rsw <- read_csv("data/rsw_monthly_passengers.csv", show_col_types = FALSE)

season_shape <- rsw %>%
  mutate(season = if_else(month >= 7, year, year - 1L)) %>%
  filter(month %in% c(10, 11, 12, 1, 2, 3, 4, 5)) %>%
  group_by(season) %>%
  filter(n() == 8) %>%
  summarise(
    shoulder = sum(passengers[month %in% c(10, 4, 5)]),
    core     = sum(passengers[month %in% c(12, 1, 2, 3)]),
    total    = sum(passengers),
    .groups  = "drop"
  ) %>%
  mutate(shoulder_ratio = shoulder / core)

# Same exclusions as script 11 - storms and COVID distort the shape badly.
EXCLUDE <- c(2004, 2017, 2019, 2020, 2022, 2024)
shape_clean <- season_shape %>% filter(!season %in% EXCLUDE)

cat("\n=====================================================================\n")
cat("  ARE SEASONAL VISITORS STAYING LONGER?\n")
cat("=====================================================================\n\n")
cat("Shoulder ratio = (Oct + Apr + May) / (Dec-Mar core).\n")
cat("Rising = arriving earlier and leaving later, i.e. longer stays.\n\n")

shape_clean %>%
  slice_tail(n = 12) %>%
  transmute(
    Season = paste0(season, "-", substr(season + 1, 3, 4)),
    Shoulder = comma(shoulder),
    Core = comma(core),
    Ratio = round(shoulder_ratio, 3)
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

fit_s <- lm(shoulder_ratio ~ season, data = shape_clean)
cs <- summary(fit_s)$coefficients["season", c("Estimate","Pr(>|t|)")]

cat(sprintf("\nTrend: %+.4f per year (%+.1f%% per decade)   p = %.4f   n = %d\n",
            cs[1], 1000 * cs[1] / mean(shape_clean$shoulder_ratio), cs[2],
            nrow(shape_clean)))

write_csv(season_shape, "data/season_shape.csv")

# -----------------------------------------------------------------------------
# 3. Verdict
# -----------------------------------------------------------------------------
cat("\n=====================================================================\n")
cat("  VERDICT\n")
cat("=====================================================================\n")

cat("\n1. MORE PEOPLE MOVING PERMANENTLY?  ")
if (cn[2] < 0.05 && cn[1] > 0 && cnc[2] < 0.05) {
  cat("YES\n")
  cat(sprintf("   Northern arrivals rising by about %.0f people a year (p = %.3f),\n",
              cn[1], cn[2]))
  cat("   and the rise survives removing the pandemic years.\n")
} else if (cn[2] < 0.05 && cn[1] > 0) {
  # Significant overall, but not once COVID is taken out. Report the weaker
  # claim, because that is the one the evidence actually supports.
  cat("MOSTLY A PANDEMIC EFFECT\n")
  cat(sprintf("   Across all %d years the rise looks solid (%+.0f people/year, p = %.3f).\n",
              nrow(perm), cn[1], cn[2]))
  cat(sprintf("   Remove 2020-22 and it collapses to %+.0f/year, p = %.2f.\n",
              cnc[1], cnc[2]))
  cat("   2021 alone brought 11,566 northern arrivals against a pre-COVID norm\n")
  cat("   near 7,000. That is the remote-work exodus, not snowbirds gradually\n")
  cat("   converting. The level has stayed somewhat higher since, but the\n")
  cat("   evidence for a STEADY underlying shift is weak.\n")
} else if (cn[2] < 0.05 && cn[1] < 0) {
  cat("NO - FALLING\n")
} else {
  cat("NO CLEAR TREND\n")
  cat(sprintf("   p = %.2f across %d years.\n", cn[2], nrow(perm)))
}

cat("\n2. SEASONAL VISITORS STAYING LONGER?  ")
if (cs[2] < 0.05 && cs[1] > 0) {
  cat("YES\n")
  cat("   The shoulder months are growing against the core, which is what\n")
  cat("   longer stays look like.\n")
} else if (cs[2] < 0.05 && cs[1] < 0) {
  cat("NO - STAYS ARE SHORTENING\n")
  cat("   The season is concentrating into its core months.\n")
} else {
  cat("NO CLEAR TREND\n")
  cat(sprintf("   p = %.2f across %d clean seasons.\n", cs[2], nrow(shape_clean)))
}

# -----------------------------------------------------------------------------
# 4. Charts
# -----------------------------------------------------------------------------
p1 <- perm %>%
  pivot_longer(c(northern_people, total_people), names_to = "grp", values_to = "n") %>%
  mutate(grp = recode(grp,
                      northern_people = "From northern states",
                      total_people    = "From anywhere out of state")) %>%
  ggplot(aes(year, n, colour = grp)) +
  geom_line(linewidth = 1.3) +
  geom_point(size = 2.8) +
  scale_y_continuous(labels = comma) +
  scale_colour_manual(values = c("From northern states" = "#c1121f",
                                 "From anywhere out of state" = "#3d5a80")) +
  labs(title = "People moving permanently into Collier County",
       subtitle = "IRS tax-address changes. These are moves, not visits.",
       x = NULL, y = "People per year", colour = NULL) +
  theme(legend.position = "top")

ggsave("output/15_permanent_moves.png", p1, width = 10, height = 5.5, dpi = 150)

p2 <- ggplot(shape_clean, aes(season, shoulder_ratio)) +
  geom_line(colour = "grey65", linewidth = 0.8) +
  geom_point(size = 2.8, colour = "#3d5a80") +
  geom_smooth(method = "lm", se = TRUE, colour = "#c1121f", linewidth = 1.2) +
  labs(title = "Are seasonal visitors staying longer?",
       subtitle = paste0("Shoulder months (Oct, Apr, May) against the Dec-Mar core.\n",
                         "Rising = arriving earlier and leaving later. Storm and COVID seasons excluded."),
       x = "Season (year it began)", y = "Shoulder / core ratio")

ggsave("output/16_staying_longer.png", p2, width = 10, height = 5.5, dpi = 150)

message("\nCharts written to output/")
