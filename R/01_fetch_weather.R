# =============================================================================
# 01 - FETCH TEMPERATURE DATA
# =============================================================================
# Goal: daily temperatures for Naples FL and the northern cities snowbirds
# actually come FROM, going back to 2000.
#
# Why the northern cities matter: nobody flees south because Naples got warm.
# They flee because CLEVELAND got cold. The thing that should drive migration
# is the GAP between the two - so we need both ends of the journey.
#
# Data source: Open-Meteo's historical archive. Free, no signup, no API key,
# daily data back to 1940. https://open-meteo.com/en/docs/historical-weather-api
# =============================================================================

library(tidyverse)
library(jsonlite)

# -----------------------------------------------------------------------------
# 1. Define our locations
# -----------------------------------------------------------------------------
# tribble() builds a small table by hand, laid out so you can read it.
# The ~name bits are the column headers.
cities <- tribble(
  ~city,          ~role,    ~lat,     ~lon,
  "Naples FL",    "south",  26.1420, -81.7948,   # the destination
  "Chicago IL",   "north",  41.8781, -87.6298,
  "Detroit MI",   "north",  42.3314, -83.0458,
  "Cleveland OH", "north",  41.4993, -81.6944,
  "New York NY",  "north",  40.7128, -74.0060,
  "Boston MA",    "north",  42.3601, -71.0589,
  "Toronto ON",   "north",  43.6532, -79.3832    # Canadians are a big slice
)

START_DATE <- "2000-01-01"
END_DATE   <- "2026-08-31"   # archive lags ~5 days behind today

# -----------------------------------------------------------------------------
# 2a. Fetching politely: retry with backoff
# -----------------------------------------------------------------------------
# Free APIs rate-limit you. Ask too fast and you get HTTP 429 ("Too Many
# Requests") and your script dies halfway through.
#
# The standard answer is EXPONENTIAL BACKOFF: if a request fails, wait, then
# try again - and wait longer each time. 5s, then 10s, then 20s, then 40s.
# The idea is to back off fast enough that you stop making the problem worse.
#
# This is the difference between a script that works on your machine once and
# one you can actually leave running.
fetch_with_retry <- function(url, max_tries = 5) {

  for (attempt in seq_len(max_tries)) {

    # try() means "attempt this; if it errors, hand me the error instead of
    # stopping the whole script". Without it, one blip kills the run.
    result <- try(jsonlite::fromJSON(url), silent = TRUE)

    # inherits(x, "try-error") is how you ask "did that fail?"
    if (!inherits(result, "try-error")) {
      return(result)
    }

    if (attempt < max_tries) {
      wait <- 5 * 2^(attempt - 1)          # 5, 10, 20, 40 seconds
      message("    rate-limited; waiting ", wait, "s (attempt ",
              attempt, "/", max_tries, ")")
      Sys.sleep(wait)
    }
  }

  stop("Gave up after ", max_tries, " attempts: ", url)
}

# -----------------------------------------------------------------------------
# 2b. A function to fetch one city
# -----------------------------------------------------------------------------
# A function is a reusable recipe. You define it once, call it many times.
# Everything between { } is the body. The last expression is what it gives back.
fetch_city <- function(city_name, latitude, longitude) {

  # Cache to disk so we only hit the internet once per city. Re-running this
  # script then takes a second instead of a minute - and is polite to a free API.
  cache_file <- file.path("data", "raw", paste0("weather_", make.names(city_name), ".csv"))

  if (file.exists(cache_file)) {
    message("  cached: ", city_name)
    return(read_csv(cache_file, show_col_types = FALSE))
  }

  message("  downloading: ", city_name)

  # Build the URL. paste0() glues strings together with nothing in between.
  url <- paste0(
    "https://archive-api.open-meteo.com/v1/archive",
    "?latitude=",  latitude,
    "&longitude=", longitude,
    "&start_date=", START_DATE,
    "&end_date=",   END_DATE,
    "&daily=temperature_2m_mean,temperature_2m_max,temperature_2m_min",
    "&temperature_unit=fahrenheit",
    "&timezone=auto"
  )

  # Fetch the URL and turn the JSON reply into an R list - retrying if the
  # API pushes back.
  raw <- fetch_with_retry(url)

  # raw$daily holds the actual numbers. $ means "reach inside and grab".
  out <- tibble(
    city      = city_name,
    date      = as.Date(raw$daily$time),
    temp_mean = raw$daily$temperature_2m_mean,
    temp_max  = raw$daily$temperature_2m_max,
    temp_min  = raw$daily$temperature_2m_min
  )

  write_csv(out, cache_file)
  Sys.sleep(4)   # pause between requests - don't hammer a free service
  out
}

# -----------------------------------------------------------------------------
# 3. Fetch every city and stack the results
# -----------------------------------------------------------------------------
message("Fetching temperature data for ", nrow(cities), " cities...")

# pmap() runs fetch_city() once per ROW of `cities`, handing it the columns
# it asks for. _dfr means "stack all the results into one data frame".
weather <- cities %>%
  select(city, lat, lon) %>%
  purrr::pmap_dfr(function(city, lat, lon) fetch_city(city, lat, lon))

# Attach the north/south label back on. A "join" matches rows by a shared column.
weather <- weather %>%
  left_join(select(cities, city, role), by = "city")

# -----------------------------------------------------------------------------
# 4. Save the combined result
# -----------------------------------------------------------------------------
write_csv(weather, "data/weather_daily.csv")

message("Done. ", format(nrow(weather), big.mark = ","), " rows saved to data/weather_daily.csv")

# glimpse() is the single most useful "what am I looking at?" command in R.
glimpse(weather)
