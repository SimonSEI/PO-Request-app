# =============================================================================
# 06 - WHERE DO THEY ACTUALLY COME FROM?
# =============================================================================
# Up to now the six "northern origin cities" were my guess. Guesses are fine as
# a starting point and terrible as a foundation. This script replaces them with
# measured data.
#
# THE SOURCE: the IRS publishes county-to-county migration every year, built
# from address changes between tax returns. For any county you can see exactly
# how many households arrived and where each came from. It is the best
# public record of who moves where in the US.
#
# THE METHOD:
#   1. Pull every inflow into Collier County (Naples)
#   2. Attach each origin county's geographic centre (Census gazetteer)
#   3. Collapse to states, putting each state's point at the migration-weighted
#      centre of its origin counties - so Illinois sits on Chicago, where the
#      migrants are, not on a cornfield in the geometric middle
#   4. Weight every state's temperature by how many people it actually sends
#
# THE CAVEAT THAT MATTERS: IRS data tracks people who CHANGE THEIR TAX ADDRESS.
# Classic snowbirds don't - they keep the northern house and the northern
# domicile, often deliberately for tax reasons. So this measures permanent
# relocation to Naples, and we are using it as a proxy for seasonal movement.
# The two are related but they are NOT the same thing, and the gap between
# them is the biggest weakness in this whole project.
#
# It also misses Canadians entirely (no US tax return), and Ontario is a real
# source of Naples snowbirds. Treat the weights as indicative, not exact.
# =============================================================================

library(tidyverse)
library(jsonlite)

COLLIER_STATE  <- "12"   # Florida
COLLIER_COUNTY <- "021"  # Collier

# Point these at wherever you downloaded them (see README for URLs).
IRS_FILE <- "C:/Users/SWeardon/AppData/Local/Temp/claude/C--Users-SWeardon-Desktop-Coding-in-R/56267a43-4d94-42e8-8b39-eef1ca5d0ec4/scratchpad/countyinflow2223.csv"
GAZ_FILE <- "C:/Users/SWeardon/AppData/Local/Temp/claude/C--Users-SWeardon-Desktop-Coding-in-R/56267a43-4d94-42e8-8b39-eef1ca5d0ec4/scratchpad/2023_Gaz_counties_national.txt"

N_STATES   <- 12          # how many origin states to model
START_DATE <- "2000-01-01"
END_DATE   <- "2026-08-31"

# -----------------------------------------------------------------------------
# 1. Collier County inflows
# -----------------------------------------------------------------------------
inflow <- read_csv(IRS_FILE, col_types = cols(.default = col_character())) %>%
  filter(y2_statefips == COLLIER_STATE, y2_countyfips == COLLIER_COUNTY) %>%
  mutate(
    n2  = as.numeric(n2),    # n2 = exemptions, i.e. roughly PEOPLE
    agi = as.numeric(agi)
  )

# The file mixes real county rows with summary rows. Left in, the totals would
# be counted alongside their own components and swamp everything.
#   y1_statefips 96/97/98 = aggregate rows
#   y1_state "DS"/"SS"/"FR" = "other flows" buckets, not real places
# We also drop Florida: intra-Florida moves are not snowbirds.
origins <- inflow %>%
  filter(
    !y1_statefips %in% c("96", "97", "98"),
    !y1_state %in% c("DS", "SS", "FR"),
    y1_state != "FL",
    !is.na(n2), n2 > 0
  ) %>%
  transmute(
    geoid = paste0(y1_statefips, y1_countyfips),
    state = y1_state,
    county = y1_countyname,
    people = n2,
    agi
  )

message(nrow(origins), " origin counties, ",
        format(sum(origins$people), big.mark = ","), " people")

# -----------------------------------------------------------------------------
# 2. Attach each county's centre point
# -----------------------------------------------------------------------------
gaz <- read_tsv(GAZ_FILE, col_types = cols(.default = col_character())) %>%
  # the gazetteer has trailing spaces in its header names - trim everything
  rename_with(str_trim) %>%
  transmute(
    geoid = GEOID,
    lat = as.numeric(INTPTLAT),
    lon = as.numeric(str_trim(INTPTLONG))
  )

origins <- origins %>%
  inner_join(gaz, by = "geoid") %>%
  filter(!is.na(lat), !is.na(lon))

# -----------------------------------------------------------------------------
# 3. Collapse to states at the migration-weighted centre
# -----------------------------------------------------------------------------
# weighted.mean() puts each state's point where its migrants actually live.
#
# ORDER MATTERS HERE, and it is a genuine trap.
# summarise() evaluates its arguments TOP TO BOTTOM, and each one immediately
# shadows the column it names. Writing people = sum(people) first would replace
# the 112-row `people` column with a single number, and the weighted.mean()
# below would then fail with:
#     'x' and 'w' must have the same length
# So: take the weighted means while `people` is still the full column, and
# collapse it to a total last.
states <- origins %>%
  group_by(state) %>%
  summarise(
    lat      = weighted.mean(lat, people),
    lon      = weighted.mean(lon, people),
    counties = n(),
    mean_agi = sum(agi) / sum(people),
    people   = sum(people),      # must come AFTER the two weighted means
    .groups  = "drop"
  ) %>%
  arrange(desc(people)) %>%
  mutate(share = people / sum(people))

write_csv(states, "data/origin_states.csv")

cat("\n=== Where Naples newcomers come from ===\n")
states %>%
  slice_head(n = 20) %>%
  transmute(
    state, people,
    share = paste0(round(100 * share, 1), "%"),
    lat = round(lat, 2), lon = round(lon, 2)
  ) %>%
  as.data.frame() %>% print(row.names = FALSE)

top_states <- states %>% slice_head(n = N_STATES)

cat("\nTop ", N_STATES, " states cover ",
    round(100 * sum(top_states$share)), "% of out-of-state arrivals\n", sep = "")

# -----------------------------------------------------------------------------
# 4. Temperature for each origin state
# -----------------------------------------------------------------------------
# Only ONE variable this time (mean temp). Open-Meteo prices a request by
# variables x days, and we hit 429s in script 01 asking for three at once.
# Ask for less and you get rate-limited less.
fetch_with_retry <- function(url, max_tries = 6) {
  for (attempt in seq_len(max_tries)) {
    result <- try(jsonlite::fromJSON(url), silent = TRUE)
    if (!inherits(result, "try-error")) return(result)
    if (attempt < max_tries) {
      wait <- 5 * 2^(attempt - 1)
      message("    rate-limited; waiting ", wait, "s (", attempt, "/", max_tries, ")")
      Sys.sleep(wait)
    }
  }
  stop("Gave up on: ", url)
}

fetch_state <- function(state, latitude, longitude) {
  cache <- file.path("data", "raw", paste0("state_", state, ".csv"))
  if (file.exists(cache)) {
    message("  cached: ", state)
    return(read_csv(cache, show_col_types = FALSE))
  }
  message("  downloading: ", state)

  url <- paste0(
    "https://archive-api.open-meteo.com/v1/archive",
    "?latitude=", round(latitude, 4), "&longitude=", round(longitude, 4),
    "&start_date=", START_DATE, "&end_date=", END_DATE,
    "&daily=temperature_2m_mean&temperature_unit=fahrenheit&timezone=auto"
  )

  raw <- fetch_with_retry(url)
  out <- tibble(
    state = state,
    date  = as.Date(raw$daily$time),
    temp  = raw$daily$temperature_2m_mean
  )
  write_csv(out, cache)
  Sys.sleep(5)
  out
}

message("\nFetching temperatures for ", nrow(top_states), " origin states...")

state_temps <- top_states %>%
  select(state, lat, lon) %>%
  pmap_dfr(function(state, lat, lon) fetch_state(state, lat, lon))

state_temps <- state_temps %>%
  left_join(select(top_states, state, people, share), by = "state")

write_csv(state_temps, "data/origin_state_temps.csv")

message("Saved ", format(nrow(state_temps), big.mark = ","), " rows")

# -----------------------------------------------------------------------------
# 5. The weighted gap
# -----------------------------------------------------------------------------
naples <- read_csv("data/weather_daily.csv", show_col_types = FALSE) %>%
  filter(city == "Naples FL") %>%
  select(date, naples = temp_mean)

# Two versions of "the north", so we can see whether weighting matters:
#   plain    - every state counts equally
#   weighted - states count in proportion to the people they send
weighted_gap <- state_temps %>%
  group_by(date) %>%
  summarise(
    north_plain    = mean(temp, na.rm = TRUE),
    north_weighted = weighted.mean(temp, people, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  inner_join(naples, by = "date") %>%
  mutate(
    gap_plain    = naples - north_plain,
    gap_weighted = naples - north_weighted
  ) %>%
  arrange(date)

write_csv(weighted_gap, "data/weighted_gap.csv")

cat("\n=== Does weighting change anything? ===\n")
cat("Mean gap, states equal:    ", round(mean(weighted_gap$gap_plain, na.rm = TRUE), 2), " deg F\n")
cat("Mean gap, migrant-weighted:", round(mean(weighted_gap$gap_weighted, na.rm = TRUE), 2), " deg F\n")
cat("Difference:                ",
    round(mean(weighted_gap$gap_weighted - weighted_gap$gap_plain, na.rm = TRUE), 2), " deg F\n")

message("\nDone. Run R/07_origin_charts.R for the charts.")
