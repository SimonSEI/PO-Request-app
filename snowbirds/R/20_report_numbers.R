# =============================================================================
# 20 - REGENERATE THE README'S NUMBERS FROM THE CSVs
# =============================================================================
# WHY THIS EXISTS
#
# The README used to quote the forecast by hand. Then R/09 changed what it
# fitted, nobody retyped the tables, and the documentation spent months stating
# a season opening of 17 Nov while the code was producing 4 Nov. Both numbers
# were "right" at some point; that is exactly what makes the drift hard to
# spot.
#
# So the numbers are no longer typed. Each generated region of README.md sits
# between a pair of markers:
#
#   <!-- BEGIN GENERATED: forecast-key-dates -->
#   ...whatever this script writes...
#   <!-- END GENERATED: forecast-key-dates -->
#
# Edit the prose around them freely. Anything between a pair is overwritten.
#
# Run it after R/09 and R/10:   Rscript R/20_report_numbers.R
# =============================================================================

local({
  lib <- file.path(getwd(), ".Rlib")
  if (dir.exists(lib)) .libPaths(c(lib, .libPaths()))
})

suppressPackageStartupMessages({
  library(tidyverse)
  library(lubridate)
})

# The README contains en dashes and multiplication signs. In a container whose
# locale is plain "C", R treats those bytes as native-encoded and every regex
# over them fails ("input string is invalid UTF-8"). Ask for a UTF-8 locale,
# and mark the text as UTF-8 regardless of whether we got one.
suppressWarnings(
  for (loc in c("C.UTF-8", "en_US.UTF-8", "")) {
    if (!is.na(Sys.setlocale("LC_CTYPE", loc)) && grepl("UTF-8", Sys.getlocale("LC_CTYPE"))) break
  }
)

README <- "README.md"

EN <- "\u2013"   # en dash, as the README's tables use
TIMES <- "\u00d7"
EM    <- "\u2014"   # em dash, as the README's prose uses

need <- function(path) {
  if (!file.exists(path))
    stop("Missing ", path, " - run R/09 and R/10 first.", call. = FALSE)
  read_csv(path, show_col_types = FALSE)
}

fc       <- need("output/season_forecast.csv")
by_cty   <- need("output/season_forecast_by_county.csv")
by_stn   <- need("output/season_forecast_by_station.csv")
curve    <- need("output/seasonal_curve.csv")
nsd      <- need("output/next_season_dates.csv")
nsw      <- need("output/next_season_windows.csv")

PRIMARY <- as.character(fc$county[1])
prim    <- by_cty %>% filter(scope == PRIMARY)
if (nrow(prim) != 1)
  stop("No row for primary county '", PRIMARY, "' in season_forecast_by_county.csv",
       call. = FALSE)

# --- formatting -------------------------------------------------------------
# "09 Mar" reads badly in a table; the README has always used "9 Mar".
no_pad  <- function(x) sub("^0", "", x)
d_doy   <- function(d) no_pad(format(as.Date(round(d) - 1, origin = "2025-01-01"), "%d %b"))
d_full  <- function(d) no_pad(format(as.Date(d), "%a %d %b %Y"))
d_day   <- function(d) no_pad(format(as.Date(d), "%d %b"))
rng_doy <- function(lo, hi) paste0(d_doy(lo), " ", EN, " ", d_doy(hi))
pc      <- function(x, dp = 1) sprintf(paste0("%.", dp, "f%%"), x)

# --- the block machinery ----------------------------------------------------
render_block <- function(txt, name, body) {
  b <- paste0("<!-- BEGIN GENERATED: ", name, " -->")
  e <- paste0("<!-- END GENERATED: ",   name, " -->")
  # Compare on bytes: marker lines are pure ASCII, but other lines in the file
  # are not, and a locale-sensitive trim would trip over them.
  flat <- sub("[ \t]+$", "", sub("^[ \t]+", "", txt, useBytes = TRUE), useBytes = TRUE)
  i <- which(flat == b)
  j <- which(flat == e)
  if (length(i) != 1 || length(j) != 1 || j <= i)
    stop("Markers for '", name, "' are missing or malformed in ", README, call. = FALSE)

  changed <- !identical(txt[(i + 1):(j - 1)], body)
  if (changed) message("  updated: ", name)
  c(txt[1:i], body, txt[j:length(txt)])
}

# --- block: the next-season dates -------------------------------------------
block_next_season <- function() {
  run_on <- as.Date(nsd$date[1]) - as.integer(nsd$days_away[1])

  tbl <- c(
    "| Event | Date | Days away |",
    "|---|---|---|",
    sprintf("| **%s** | **%s** | %d |", nsd$event, d_full(nsd$date), as.integer(nsd$days_away))
  )

  win_line <- function(w) {
    r <- nsw %>% filter(window == w)
    inside <- if (isTRUE(as.logical(r$inside_today))) " (we are inside it now)" else ""
    sprintf("- **%s window: %s %s %s %s**%s", w,
            d_day(r$from), EN, d_day(r$to), format(as.Date(r$to), "%Y"), inside)
  }

  c("",
    sprintf("From `R/10_next_season_dates.R`, run %s:",
            no_pad(format(run_on, "%d %b %Y"))),
    "", tbl, "",
    win_line("Peak"),
    win_line("Trough"),
    sprintf("- Peak runs **%.2f%s** an average day, trough **%.2f%s** %s a **%s fall** from",
            prim$peak_val, TIMES, prim$trough_val, TIMES, EM, pc(prim$decline_pct, 0)),
    sprintf("  peak to trough, or a **%s rise** from trough to peak.",
            pc(prim$increase_pct, 0)),
    "")
}

# --- block: key dates -------------------------------------------------------
block_key_dates <- function() {
  row <- function(label, m, bold = TRUE) {
    nm <- if (bold) paste0("**", label, "**") else label
    sprintf("| %s | %s | %s |", nm, d_doy(prim[[m]]),
            rng_doy(prim[[paste0(m, "_lo")]], prim[[paste0(m, "_hi")]]))
  }

  pk <- curve %>% filter(index >= max(index) * 0.99)
  tr <- curve %>% filter(index <= min(index) * 1.01)

  c("",
    "| | Estimate | 90% CI |",
    "|---|---|---|",
    row("Season starts", "start_doy"),
    row("Peak",          "peak_doy"),
    row("Season ends",   "end_doy"),
    row("Trough",        "trough_doy"),
    sprintf("| Season length | %d days | %d %s %d |",
            as.integer(prim$season_days), as.integer(round(prim$season_days_lo)),
            EN, as.integer(round(prim$season_days_hi))),
    "",
    "**Practical ranges** (within 1% of the extreme \u2014 more honest than a single day,",
    "since the curve is flat at the top):",
    "",
    sprintf("- **Peak period: %s** (%d days)",   rng_doy(min(pk$doy), max(pk$doy)), nrow(pk)),
    sprintf("- **Trough period: %s** (%d days)", rng_doy(min(tr$doy), max(tr$doy)), nrow(tr)),
    "")
}

# --- block: magnitude -------------------------------------------------------
block_magnitude <- function() {
  c("",
    "| | Estimate | 90% CI |",
    "|---|---|---|",
    sprintf("| Peak level | %.3f%s average day | %.3f %s %.3f |",
            prim$peak_val, TIMES, prim$peak_val_lo, EN, prim$peak_val_hi),
    sprintf("| Trough level | %.3f%s average day | %.3f %s %.3f |",
            prim$trough_val, TIMES, prim$trough_val_lo, EN, prim$trough_val_hi),
    sprintf("| **Decline from peak** | **%s** | %.1f %s %s |",
            pc(prim$decline_pct), prim$decline_pct_lo, EN, pc(prim$decline_pct_hi)),
    sprintf("| **Increase from trough** | **%s** | %.1f %s %s |",
            pc(prim$increase_pct), prim$increase_pct_lo, EN, pc(prim$increase_pct_hi)),
    "")
}

# --- block: by county -------------------------------------------------------
block_by_county <- function() {
  lab <- function(s) {
    if (s == PRIMARY) paste0("**", s, "** (what the forecast reports)")
    else if (s == "Pooled") "Pooled (kept only as a warning)"
    else s
  }
  c("",
    "| Scope | Stations | Starts | Peak | Ends | Trough | Decline | R\u00b2 |",
    "|---|---|---|---|---|---|---|---|",
    sprintf("| %s | %d | %s | %s | %s | %s | %s | %.3f |",
            map_chr(by_cty$scope, lab), as.integer(by_cty$n_stations),
            d_doy(by_cty$start_doy), d_doy(by_cty$peak_doy),
            d_doy(by_cty$end_doy),   d_doy(by_cty$trough_doy),
            pc(by_cty$decline_pct), by_cty$model_r2),
    "")
}

# --- block: by station ------------------------------------------------------
# The friendly names are the only hand-maintained thing left here; a station
# with no entry falls back to its bare number.
STATION_NAMES <- c(
  "03-0094" = "0094 (Naples urban)",
  "03-0270" = "0270 (Everglades, rural)",
  "03-0351" = "0351",
  "12-0184" = "0184 (Lee)",
  "12-0273" = "0273 (Lee)"
)

block_by_station <- function() {
  nm <- coalesce(unname(STATION_NAMES[by_stn$site]), sub("^\\d+-", "", by_stn$site))
  c("",
    "| Station | County | Peak | Trough | Starts | Ends | Decline |",
    "|---|---|---|---|---|---|---|",
    sprintf("| %s | %s | %s | %s | %s | %s | %s |",
            nm, by_stn$county_name,
            d_doy(by_stn$peak_doy),  d_doy(by_stn$trough_doy),
            d_doy(by_stn$start_doy), d_doy(by_stn$end_doy),
            pc(by_stn$decline_pct)),
    "")
}

# --- go ---------------------------------------------------------------------
txt <- readLines(README, warn = FALSE)
Encoding(txt) <- "UTF-8"
before <- txt

message("Regenerating README blocks from output/*.csv (primary county: ", PRIMARY, ")")
txt <- render_block(txt, "next-season-dates",   block_next_season())
txt <- render_block(txt, "forecast-key-dates",  block_key_dates())
txt <- render_block(txt, "forecast-magnitude",  block_magnitude())
txt <- render_block(txt, "forecast-by-county",  block_by_county())
txt <- render_block(txt, "forecast-by-station", block_by_station())

if (identical(before, txt)) {
  message("README.md already matches the CSVs - nothing to do.")
} else {
  con <- file(README, open = "wb")
  writeLines(enc2utf8(txt), con, useBytes = TRUE)
  close(con)
  message("README.md rewritten.")
}
