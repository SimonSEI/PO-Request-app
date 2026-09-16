# =============================================================================
# 02 - FETCH TRAFFIC DATA (Collier County = Naples)
# =============================================================================
# Source: FDOT's "Florida Traffic Online" map server. This is the same database
# behind FDOT's public traffic map, but we're asking it directly instead of
# clicking around a website. It speaks a standard called ArcGIS REST: you send
# a URL with a filter, it sends back JSON.
#
# Two things we pull:
#   A) The 7 continuous-count stations - machines in the road counting cars
#      24/7/365. These are what produce seasonal data.
#   B) AADT (Annual Average Daily Traffic) for every road segment, 2021-2025.
#      "AADT" = average cars per day over a whole year.
#
# IMPORTANT CAVEAT, stated up front: AADT is an ANNUAL average. It deliberately
# flattens out the seasonal swing we care about. So AADT tells us how Naples
# traffic is GROWING year over year - it cannot by itself tell us WHEN in the
# year the snowbirds arrive. We handle that in script 03.
# =============================================================================

library(tidyverse)
library(jsonlite)

BASE <- "https://gis.fdot.gov/arcgis/rest/services/FTO/fto_PROD/MapServer"

# -----------------------------------------------------------------------------
# A helper to query any layer. Note: FDOT's county names are Title Case -
# 'Collier' works, 'COLLIER' silently returns zero rows. Fun.
# -----------------------------------------------------------------------------
#
# PAGINATION - the bug that bites everyone once:
# ArcGIS servers refuse to send more than 1,000 records in one reply. They do
# NOT warn you. You just get 1,000 rows and a quiet sense that everything is
# fine. Our first run returned exactly 1000 segment-years, with 2025 showing
# 183 segments when every other year had ~205. The missing rows weren't absent
# from FDOT - they were sitting on page two.
#
# So: ask repeatedly, shifting `resultOffset` each time, until a page comes
# back short. A short page means we've reached the end.
#
# Rule of thumb: any time a row count is a suspiciously round number, assume
# you hit a limit rather than the end of the data.
fdot_query <- function(layer_id, where, out_fields = "*", geometry = FALSE) {

  PAGE_SIZE <- 1000
  offset    <- 0
  pages     <- list()   # collect each page, stack them all at the end

  repeat {
    # URLencode() escapes spaces and quotes so they survive inside a URL.
    url <- paste0(
      BASE, "/", layer_id, "/query",
      "?where=",          URLencode(where, reserved = TRUE),
      "&outFields=",      URLencode(out_fields, reserved = TRUE),
      "&returnGeometry=", tolower(as.character(geometry)),
      "&outSR=4326",
      "&resultOffset=",      offset,
      "&resultRecordCount=", PAGE_SIZE,
      "&f=json"
    )

    raw <- fromJSON(url)

    if (!is.null(raw$error)) {
      stop("FDOT said no: ", raw$error$message)
    }

    # No features at all means we've run off the end.
    if (is.null(raw$features) || length(raw$features) == 0) break

    attrs <- raw$features$attributes
    if (is.null(attrs) || nrow(attrs) == 0) break

    page <- as_tibble(attrs)

    # If we asked for locations, glue the lat/lon columns on.
    if (geometry && !is.null(raw$features$geometry)) {
      page <- bind_cols(page, as_tibble(raw$features$geometry)) %>%
        rename(lon = x, lat = y)
    }

    pages[[length(pages) + 1]] <- page
    offset <- offset + nrow(page)
    message("    ", offset, " rows so far...")

    # A short page means that was the last one.
    if (nrow(page) < PAGE_SIZE) break
  }

  bind_rows(pages)
}

# -----------------------------------------------------------------------------
# A) The continuous count stations
# -----------------------------------------------------------------------------
message("Fetching continuous count stations in Collier County...")

stations <- fdot_query(
  layer_id   = 1,
  where      = "COUNTYNM='Collier'",
  out_fields = "COSITE,AADT,YEAR_,SITETYPE,ACTIVE,COUNTYNM,KFCTR,DFCTR",
  geometry   = TRUE
) %>%
  rename(site = COSITE, aadt = AADT, year = YEAR_) %>%
  arrange(desc(aadt))

write_csv(stations, "data/collier_count_stations.csv")
message("  ", nrow(stations), " stations found.")

# KFCTR is worth understanding: it's the "K factor", the share of yearly traffic
# happening in the single busiest hour of the year. Higher K = spikier road.
print(stations %>% select(site, aadt, kfctr = KFCTR, lat, lon))

# -----------------------------------------------------------------------------
# B) AADT by road segment, all available years
# -----------------------------------------------------------------------------
message("Fetching AADT 2021-2025...")

aadt <- fdot_query(
  layer_id   = 7,
  where      = "COUNTY='Collier'",
  out_fields = "YEAR_,COSITE,ROADWAY,DESC_FRM,DESC_TO,AADT,KFCTR,DFCTR,COUNTY"
) %>%
  rename(year = YEAR_, site = COSITE, aadt = AADT) %>%
  filter(!is.na(aadt), aadt > 0)

write_csv(aadt, "data/collier_aadt.csv")

message("  ", format(nrow(aadt), big.mark = ","), " segment-years saved.")

# A first look: is Naples traffic growing? count() tallies rows per group.
aadt %>%
  group_by(year) %>%
  summarise(
    segments   = n(),
    median_aadt = median(aadt),
    total_aadt  = sum(aadt)
  ) %>%
  print()
