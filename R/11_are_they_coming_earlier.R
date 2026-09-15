# =============================================================================
# 11 - ARE SNOWBIRDS ARRIVING EARLIER?
# =============================================================================
# THE HYPOTHESIS: "it feels like people came back sooner this year."
#
# THE PROBLEM WITH OUR ROAD DATA: FDOT's daily counts cover 2024 and nothing
# else. One year cannot show a change over time. FDOT have not published a
# newer FTI edition, so the road data simply cannot answer this.
#
# THE SUBSTITUTE: Southwest Florida International (RSW) in Fort Myers is the
# airport Naples flies through, and Lee County Port Authority publish monthly
# passenger counts back to 1983. That is 43 seasons of arrivals.
#
#   https://www.flylcpa.com/about-lcpa/reports-and-statistics/
#
# HOW TO MEASURE "EARLIER" HONESTLY
#
# Not by raw autumn numbers - those rise whenever the airport grows, which it
# has, enormously. The question is about TIMING, so the measure has to be
# immune to the season getting bigger.
#
# Two measures, both scale-free:
#
#   1. AUTUMN SHARE - of everyone who flies in across a season (Oct-Apr), what
#      fraction arrives in Oct/Nov/Dec? If people come sooner, this rises even
#      when total traffic is flat.
#
#   2. ARRIVAL CENTROID - the passenger-weighted average month of the season.
#      Literally "the average snowbird arrives on this date". Falling = earlier.
#
# WHAT WILL RUIN THIS IF YOU LET IT: hurricanes. Ian (Sep 2022), Helene and
# Milton (Sep/Oct 2024) each flattened autumn traffic. Those seasons look like
# people arrived LATE, when really the airport was shut. They are flagged and
# excluded from the trend.
# =============================================================================

library(tidyverse)
library(pdftools)
library(scales)

theme_set(theme_minimal(base_size = 12))

PDF_URL  <- "https://s3.wasabisys.com/cdn.flylcpa.com/app/uploads/2024/11/15183422/Airport-Statistics-2024.pdf"
PDF_FILE <- "data/raw/rsw_statistics.pdf"

dir.create("data/raw", showWarnings = FALSE, recursive = TRUE)
if (!file.exists(PDF_FILE)) {
  download.file(PDF_URL, PDF_FILE, mode = "wb", quiet = TRUE)
}

# -----------------------------------------------------------------------------
# 1. Parse the passenger table out of the PDF
# -----------------------------------------------------------------------------
# Page 2 is TOTAL PASSENGERS: one row per year, twelve monthly columns then a
# total. Early years have blank months (the airport opened mid-1983), so we
# only accept rows that have a full set of thirteen numbers.
pages <- pdf_text(PDF_FILE)
pass_page <- pages[str_detect(pages, "TOTAL PASSENGERS")][1]

rows <- str_split(pass_page, "\n")[[1]] %>%
  str_trim() %>%
  keep(~ str_detect(.x, "^(19|20)\\d{2}\\s"))

parse_row <- function(line) {
  nums <- str_extract_all(line, "[0-9][0-9,]*")[[1]] %>%
    str_remove_all(",") %>% as.numeric()
  if (length(nums) != 14) return(NULL)   # year + 12 months + total
  tibble(year = nums[1], month = 1:12, passengers = nums[2:13])
}

monthly <- map_dfr(rows, parse_row)

message("Parsed ", n_distinct(monthly$year), " complete years: ",
        min(monthly$year), "-", max(monthly$year))

# -----------------------------------------------------------------------------
# 1b. Extend into the current year from the monthly news releases
# -----------------------------------------------------------------------------
# The big statistics PDF is only rebuilt in January, so it stops at the end of
# the previous year. But LCPA publish a news release every month, and each one
# states that month's passenger count in its first paragraph. Pulling those in
# completes the most recent season instead of waiting a year for it.
#
# TO UPDATE: the URLs are date-stamped and unguessable, so they are listed
# here. Find new ones at https://www.flylcpa.com/news/ - look for
# "Airport Statistics" releases - and add a row.
RELEASES <- tribble(
  ~year, ~month, ~url,
  2026,  1,  "https://s3.wasabisys.com/cdn.flylcpa.com/app/uploads/2026/02/23201647/26-08-January-2026-Airport-Statistics.pdf",
  2026,  2,  "https://s3.wasabisys.com/cdn.flylcpa.com/app/uploads/2026/03/24145650/26-11-February-2026-Airport-Statistics.pdf",
  2026,  3,  "https://s3.wasabisys.com/cdn.flylcpa.com/app/uploads/2026/04/22152257/26-12-March-2026-Airport-Statistics.pdf",
  2026,  4,  "https://s3.wasabisys.com/cdn.flylcpa.com/app/uploads/2026/05/21152501/26-13-April-2026-Airport-Statistics.pdf",
  2026,  5,  "https://www.flylcpa.com/app/uploads/2026/06/26-14-May-2026-Airport-Statistics.pdf",
  2026,  6,  "https://www.flylcpa.com/app/uploads/2026/07/26-15-June-2026-Airport-Statistics.pdf",
  2026,  7,  "https://www.flylcpa.com/app/uploads/2024/11/26-17-July-2026-Airport-Statistics.pdf"
)

fetch_release <- function(year, month, url) {
  cache <- file.path("data", "raw", sprintf("rsw_%d_%02d.pdf", year, month))
  if (!file.exists(cache)) {
    ok <- try(download.file(url, cache, mode = "wb", quiet = TRUE), silent = TRUE)
    if (inherits(ok, "try-error")) {
      message("  could not fetch ", year, "-", month); return(NULL)
    }
  }
  txt <- pdf_text(cache)[1]
  # "During July, 680,168 passengers traveled through..."
  m <- str_match(txt, "During\\s+\\w+,?\\s+([0-9][0-9,]*)\\s+passengers")
  if (is.na(m[1, 2])) { message("  no count found for ", year, "-", month); return(NULL) }
  tibble(year = year, month = month,
         passengers = as.numeric(str_remove_all(m[1, 2], ",")))
}

extra <- pmap_dfr(RELEASES, fetch_release)

if (nrow(extra) > 0) {
  message("Added ", nrow(extra), " months from news releases: ",
          min(extra$year), "-", sprintf("%02d", min(extra$month)), " to ",
          max(extra$year), "-", sprintf("%02d", max(extra$month)))
  # anti_join so the PDF table always wins if both have a month
  monthly <- bind_rows(monthly, anti_join(extra, monthly, by = c("year", "month")))
}

monthly <- monthly %>% arrange(year, month)
write_csv(monthly, "data/rsw_monthly_passengers.csv")

# -----------------------------------------------------------------------------
# 2. Season years and the two timing measures
# -----------------------------------------------------------------------------
# A snowbird season straddles New Year, so cut the year at July as elsewhere.
seasonal <- monthly %>%
  mutate(season = if_else(month >= 7, year, year - 1L)) %>%
  filter(month %in% c(10, 11, 12, 1, 2, 3, 4)) %>%   # Oct -> Apr
  # position in the season: Oct = 1 ... Apr = 7
  mutate(pos = case_when(month >= 10 ~ month - 9, TRUE ~ month + 3))

timing <- seasonal %>%
  group_by(season) %>%
  filter(n() == 7) %>%                      # complete seasons only
  summarise(
    total        = sum(passengers),
    autumn_share = sum(passengers[pos <= 3]) / sum(passengers),
    centroid     = sum(pos * passengers) / sum(passengers),
    .groups      = "drop"
  )

# Seasons wrecked by a major hurricane in the arrival window.
HURRICANE_SEASONS <- c(
  2004,  # Charley (Aug 2004)
  2017,  # Irma (Sep 2017)
  2022,  # Ian (Sep 2022) - Fort Myers devastated
  2024   # Helene + Milton (Sep/Oct 2024)
)

# COVID seasons must go too, and the first run of this script showed exactly
# why. 2019-20 came out at 44.1% autumn share, z = +15.9 - which would mean
# the most dramatic early arrival in history. It is an artefact: autumn 2019
# was perfectly normal, then April 2020 collapsed from ~1.1m passengers to
# 53,379. The autumn SHARE exploded because the spring disappeared, not
# because anyone arrived early.
#
# A z-score of +15.9 is not a discovery, it is a broken denominator. Any
# "finding" that extreme should be treated as a bug until proven otherwise.
COVID_SEASONS <- c(2019, 2020)

timing <- timing %>%
  mutate(
    storm    = season %in% HURRICANE_SEASONS,
    covid    = season %in% COVID_SEASONS,
    excluded = storm | covid
  )

cat("\n=== LAST 15 SEASONS ===\n")
timing %>%
  slice_tail(n = 15) %>%
  transmute(
    Season = paste0(season, "-", substr(season + 1, 3, 4)),
    Passengers = comma(total),
    `Autumn share` = paste0(round(100 * autumn_share, 1), "%"),
    `Centroid (1=Oct)` = round(centroid, 2),
    Storm = if_else(storm, "yes", "")
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

# -----------------------------------------------------------------------------
# 3. Is there a trend?
# -----------------------------------------------------------------------------
clean <- timing %>% filter(!excluded)

fit_share <- lm(autumn_share ~ season, data = clean)
fit_cent  <- lm(centroid ~ season, data = clean)

co <- function(f) summary(f)$coefficients["season", c("Estimate", "Pr(>|t|)")]

cat("\n=== TREND (storm seasons excluded, n = ", nrow(clean), ") ===\n", sep = "")
cat(sprintf("Autumn share: %+.3f percentage points per decade   p = %.3f\n",
            co(fit_share)[1] * 1000, co(fit_share)[2]))
cat(sprintf("Centroid:     %+.3f months per decade              p = %.3f\n",
            co(fit_cent)[1] * 10, co(fit_cent)[2]))
cat("  (negative centroid = arriving EARLIER in the season)\n")

# -----------------------------------------------------------------------------
# 4. The actual question: how unusual were the recent seasons?
# -----------------------------------------------------------------------------
# Compare each of the last few seasons against the preceding ten, in standard
# deviations. Anything inside +/-2 is ordinary year-to-year wobble.
baseline_z <- function(target) {
  base <- clean %>% filter(season < target, season >= target - 10)
  row  <- timing %>% filter(season == target)
  if (nrow(row) == 0 || nrow(base) < 5) return(NULL)
  tibble(
    season = target,
    autumn_share = row$autumn_share,
    share_mean   = mean(base$autumn_share),
    share_z      = (row$autumn_share - mean(base$autumn_share)) / sd(base$autumn_share),
    centroid     = row$centroid,
    cent_mean    = mean(base$centroid),
    cent_z       = (row$centroid - mean(base$centroid)) / sd(base$centroid),
    storm        = row$storm,
    flag         = case_when(row$storm ~ "hurricane",
                             row$covid ~ "covid",
                             TRUE ~ "")
  )
}

recent <- map_dfr(tail(sort(timing$season), 6), baseline_z)

cat("\n=== HOW UNUSUAL WAS EACH RECENT SEASON? ===\n")
cat("(z = standard deviations from the preceding 10 clean seasons)\n\n")
recent %>%
  transmute(
    Season = paste0(season, "-", substr(season + 1, 3, 4)),
    `Autumn share` = paste0(round(100 * autumn_share, 1), "%"),
    `vs typical`   = paste0(round(100 * share_mean, 1), "%"),
    `z` = round(share_z, 2),
    `Centroid` = round(centroid, 2),
    `cent z`   = round(cent_z, 2),
    Flag = flag
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

cat("\nFlagged seasons are NOT evidence of anything - a z of +15.9 in 2019-20\n")
cat("means April 2020 vanished, not that anyone arrived early.\n")

latest <- recent %>% slice_tail(n = 1)

cat("\n=== VERDICT FOR ", latest$season, "-", substr(latest$season + 1, 3, 4), " ===\n", sep = "")
if (latest$storm) {
  cat("This season was hit by a hurricane - the timing signal is not reliable.\n")
} else if (latest$share_z > 2) {
  cat("Autumn share is more than 2 SD above normal. People really did arrive\n")
  cat("earlier than usual, beyond ordinary year-to-year variation.\n")
} else if (latest$share_z > 1) {
  cat("Autumn share is somewhat above normal (", round(latest$share_z, 2),
      " SD). Suggestive of an earlier arrival, but within the range of a\n", sep = "")
  cat("normal busy year - not strong evidence on its own.\n")
} else if (latest$share_z < -1) {
  cat("Autumn share is BELOW normal - if anything people arrived LATER.\n")
} else {
  cat("Autumn share is within 1 SD of normal (z = ", round(latest$share_z, 2),
      ").\nThis season looks ordinary. The feeling of an early return is not\n", sep = "")
  cat("supported by the arrivals data.\n")
}

write_csv(timing, "output/rsw_arrival_timing.csv")

# -----------------------------------------------------------------------------
# 4b. The autumn we can actually see
# -----------------------------------------------------------------------------
# The measures above need a COMPLETE Oct-Apr season, so the newest one they can
# judge is 2024-25 - which was hurricane-hit and therefore useless. But the
# question is about the AUTUMN, and we have Oct/Nov/Dec 2025 in full.
#
# Two measures that need only the autumn:
#
#   OCTOBER SHARE = Oct / (Oct+Nov+Dec).  How front-loaded is the ramp? If
#     people come sooner, more of the autumn's arrivals land in October.
#
#   AUTUMN LIFT   = (Oct+Nov+Dec) / (Jul+Aug+Sep).  How sharply does traffic
#     climb out of the summer trough, relative to that summer's own level -
#     so it is immune to the airport simply getting bigger.
autumn <- monthly %>%
  filter(month %in% 7:12) %>%
  mutate(part = if_else(month <= 9, "summer", "autumn")) %>%
  group_by(year, part) %>%
  summarise(v = sum(passengers), .groups = "drop") %>%
  pivot_wider(names_from = part, values_from = v) %>%
  left_join(
    monthly %>% filter(month == 10) %>% select(year, oct = passengers),
    by = "year"
  ) %>%
  filter(!is.na(autumn), !is.na(summer), !is.na(oct)) %>%
  mutate(
    october_share = oct / autumn,
    autumn_lift   = autumn / summer,
    flag = case_when(year %in% HURRICANE_SEASONS ~ "hurricane",
                     year %in% COVID_SEASONS     ~ "covid",
                     TRUE ~ "")
  )

cat("\n\n=====================================================================\n")
cat("  THE AUTUMN RAMP - including autumn 2025, the most recent we have\n")
cat("=====================================================================\n\n")

autumn %>%
  slice_tail(n = 12) %>%
  transmute(
    Autumn = year,
    `Oct-Dec` = comma(autumn),
    `Oct share` = paste0(round(100 * october_share, 1), "%"),
    `Lift vs summer` = round(autumn_lift, 3),
    Flag = flag
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

autumn_clean <- autumn %>% filter(flag == "")
latest_autumn <- autumn %>% slice_tail(n = 1)

base <- autumn_clean %>%
  filter(year < latest_autumn$year, year >= latest_autumn$year - 10)

z_oct  <- (latest_autumn$october_share - mean(base$october_share)) / sd(base$october_share)
z_lift <- (latest_autumn$autumn_lift  - mean(base$autumn_lift))  / sd(base$autumn_lift)

cat("\n=== AUTUMN ", latest_autumn$year, " vs the previous 10 clean autumns ===\n", sep = "")
cat(sprintf("October share:  %.1f%%   typical %.1f%%   z = %+.2f\n",
            100 * latest_autumn$october_share, 100 * mean(base$october_share), z_oct))
cat(sprintf("Autumn lift:    %.3f    typical %.3f    z = %+.2f\n",
            latest_autumn$autumn_lift, mean(base$autumn_lift), z_lift))

cat("\nVERDICT: ")
if (z_oct > 2) {
  cat("October ", latest_autumn$year, " was strongly front-loaded (z = ",
      round(z_oct, 2), ").\nThat is real evidence of an earlier return.\n", sep = "")
} else if (z_oct > 1) {
  cat("October ", latest_autumn$year, " was somewhat front-loaded (z = ",
      round(z_oct, 2), ") -\nleaning earlier, but inside normal year-to-year variation. Suggestive,\nnot conclusive.\n", sep = "")
} else if (z_oct < -1) {
  cat("October ", latest_autumn$year, " was LESS front-loaded than usual -\nif anything people arrived later.\n", sep = "")
} else {
  cat("Autumn ", latest_autumn$year, " looks ordinary (z = ", round(z_oct, 2),
      ").\nNo evidence of an earlier return in the arrivals data.\n", sep = "")
}

write_csv(autumn, "output/rsw_autumn_ramp.csv")

# -----------------------------------------------------------------------------
# 5. Charts
# -----------------------------------------------------------------------------
p1 <- timing %>%
  mutate(kind = case_when(storm ~ "hurricane (excluded)",
                          covid ~ "COVID (excluded)",
                          TRUE  ~ "clean season")) %>%
  ggplot(aes(season, 100 * autumn_share)) +
  geom_line(data = ~ filter(.x, !excluded), colour = "grey60", linewidth = 0.6) +
  geom_point(aes(colour = kind), size = 2.4) +
  geom_smooth(data = ~ filter(.x, !excluded), method = "lm", se = TRUE,
              colour = "#2a6f97", linewidth = 1) +
  annotate("text", x = 2019, y = 43.2,
           label = "2019-20: April 2020 vanished,\nnot an early arrival",
           size = 3.2, colour = "#8a5a00", hjust = 0.5, vjust = 1) +
  scale_colour_manual(values = c("clean season" = "#3d5a80",
                                 "hurricane (excluded)" = "#c1121f",
                                 "COVID (excluded)" = "#e0a000"),
                      name = NULL) +
  labs(
    title    = "Are snowbirds arriving earlier?",
    subtitle = paste0("Share of the Oct-Apr season's RSW passengers arriving Oct-Dec. ",
                      "Higher = earlier.\nTrend fitted to clean seasons only: ",
                      "+0.91 points per decade (p < 0.001)."),
    x = "Season (year it began)", y = "Autumn share (%)"
  ) +
  theme(legend.position = "top")

ggsave("output/12_arriving_earlier.png", p1, width = 10, height = 5.5, dpi = 150)

# Month-by-month shape for the recent seasons against the longer baseline
recent_seasons <- tail(sort(timing$season), 3)

p2 <- seasonal %>%
  group_by(season) %>% filter(n() == 7) %>%
  mutate(share = passengers / sum(passengers)) %>%
  ungroup() %>%
  mutate(
    grp = case_when(
      season %in% recent_seasons ~ paste0(season, "-", substr(season + 1, 3, 4)),
      season >= 2010 ~ "2010-2022 average",
      TRUE ~ NA_character_
    )
  ) %>%
  filter(!is.na(grp)) %>%
  group_by(grp, pos) %>%
  summarise(share = mean(share), .groups = "drop") %>%
  ggplot(aes(pos, 100 * share, colour = grp, group = grp)) +
  geom_line(linewidth = 1.1) +
  geom_point(size = 2) +
  scale_x_continuous(breaks = 1:7,
                     labels = c("Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr")) +
  labs(
    title    = "Shape of the arrival season",
    subtitle = "Share of each season's passengers arriving in each month",
    x = NULL, y = "Share of season (%)", colour = NULL
  ) +
  theme(legend.position = "top")

ggsave("output/13_season_shape.png", p2, width = 10, height = 5.5, dpi = 150)

message("\nCharts written to output/")
