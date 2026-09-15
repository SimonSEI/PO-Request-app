# =============================================================================
# 12 - THE WATCHER
# =============================================================================
# Checks every data source for new material, re-runs whatever it affects, and
# raises an alert if a headline prediction actually moves - saying which source
# caused it and by how much.
#
# Run it as often as you like. It is deliberately cheap when nothing has
# changed: a handful of HTTP requests, no downloads, no recomputation.
#
# HONEST EXPECTATION SETTING
#
# "Constantly scanning" will usually find nothing, and that is correct
# behaviour rather than a failure. The three sources move at very different
# speeds:
#
#   Open-Meteo weather     new data every day, but one extra day out of 9,700
#                          moves a 26-year trend by almost nothing
#   RSW airport            one new month, roughly 3-4 weeks after month end.
#                          This is the source that will actually fire alerts
#   FDOT traffic database  one new edition per YEAR. This is the only source
#                          that can move the peak/trough forecast at all,
#                          because that forecast is fitted to daily counts
#
# So: expect a meaningful alert about once a month, a big one once a year, and
# silence the rest of the time. An alert every run would mean the thresholds
# are too sensitive, not that the watcher is working hard.
# =============================================================================

suppressPackageStartupMessages({
  library(tidyverse)
  library(lubridate)
  library(pdftools)
})

STATE_FILE   <- "data/watch_state.csv"
ALERT_FILE   <- "output/alerts.csv"
HISTORY_FILE <- "output/prediction_history.csv"

NOW <- Sys.time()
dir.create("output", showWarnings = FALSE)

say <- function(...) cat(format(NOW, "%Y-%m-%d %H:%M"), "|", ..., "\n")

# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------
UA <- "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0.0.0"

http_ok <- function(url) {
  # HEAD-style check without downloading the body.
  res <- try(
    suppressWarnings(
      system2("curl", c("-s", "-k", "-L", "-m", "15", "-A", shQuote(UA),
                        "-o", if (.Platform$OS.type == "windows") "NUL" else "/dev/null",
                        "-w", "%{http_code}", shQuote(url)),
              stdout = TRUE)
    ), silent = TRUE)
  if (inherits(res, "try-error") || length(res) == 0) return(FALSE)
  identical(trimws(tail(res, 1)), "200")
}

fetch_text <- function(url) {
  res <- try(suppressWarnings(
    system2("curl", c("-s", "-k", "-L", "-m", "30", "-A", shQuote(UA), shQuote(url)),
            stdout = TRUE)), silent = TRUE)
  if (inherits(res, "try-error")) return("")
  paste(res, collapse = "\n")
}

read_state <- function() {
  # col_types = "c" for everything, deliberately.
  # Without it, read_csv GUESSES types - and it guessed checked_at was a
  # datetime, which then refused to bind_rows() with the character timestamp
  # written back. That bug only appeared on the SECOND run, because on the
  # first there is no state file to read and everything is character already.
  #
  # Anything that re-reads its own output must pin the types, or it works once
  # and fails forever after.
  if (file.exists(STATE_FILE)) {
    read_csv(STATE_FILE, show_col_types = FALSE, col_types = cols(.default = col_character()))
  } else {
    tibble(source = character(), fingerprint = character(), checked_at = character())
  }
}

put_state <- function(st, src, fp) {
  bind_rows(filter(st, source != src),
            tibble(source = src, fingerprint = as.character(fp),
                   checked_at = format(NOW)))
}

get_fp <- function(st, src) {
  v <- st %>% filter(source == src) %>% pull(fingerprint)
  if (length(v) == 0) NA_character_ else v[1]
}

state <- read_state()
changes <- list()   # accumulates: source, old, new, detail

# =============================================================================
# SOURCE 1 - FDOT traffic database (annual; the only one that moves the forecast)
# =============================================================================
say("checking FDOT traffic database...")

fdot_page <- fetch_text("https://www.fdot.gov/statistics/trafficinfo/default.shtm")
fti_name  <- str_extract(fdot_page, "fti_[0-9]{4}\\.zip")

if (!is.na(fti_name)) {
  old <- get_fp(state, "fdot_fti")
  if (!is.na(old) && old != fti_name) {
    changes[["fdot_fti"]] <- list(
      source = "FDOT traffic database",
      old = old, new = fti_name,
      detail = paste0(
        "A NEW EDITION IS PUBLISHED (", fti_name, ", was ", old, "). This is the ",
        "only source that can move the peak and trough forecast, because that ",
        "forecast is fitted to daily counting-station data. It needs a manual ",
        "step: download it from https://www.fdot.gov/statistics/trafficinfo/ ",
        "(~97MB zip), unzip, point FTI_PATH in R/04_fetch_fti.R at the .mdb, ",
        "then run R/04, R/09 and R/10. That will give a SECOND year of daily ",
        "data - which for the first time would let us measure how much the ",
        "season shifts between years, rather than assuming."
      ))
  }
  state <- put_state(state, "fdot_fti", fti_name)
  say("  FTI edition:", fti_name, if (!is.na(old) && old != fti_name) "** NEW **" else "(unchanged)")
} else {
  say("  could not read FDOT page - skipping")
}

# =============================================================================
# SOURCE 2 - RSW airport monthly passengers (monthly; drives arrival timing)
# =============================================================================
# The news page sits behind Cloudflare and refuses plain HTTP, but the PDFs
# themselves are served fine. So instead of scraping the listing we probe the
# known URL pattern:
#
#   /app/uploads/{YYYY}/{MM}/{YY}-{NN}-{Month}-{YYYY}-Airport-Statistics.pdf
#
# The release number NN is not predictable, so we try a bounded range. The
# upload directory is not reliably the publish month either (July 2026 landed
# in a 2024/11 folder), so we try a few candidates. Only ever runs when a new
# month is actually due.
MONTH_NAMES <- c("January","February","March","April","May","June",
                 "July","August","September","October","November","December")

find_release <- function(year, month) {
  yy <- substr(as.character(year + (month == 12) * 0), 3, 4)
  mname <- MONTH_NAMES[month]

  # A month's release appears a few weeks after it ends.
  pub <- ymd(paste(year, month, 1)) %m+% months(1)
  dirs <- list(
    c(year(pub), month(pub)),
    c(year(pub %m+% months(1)), month(pub %m+% months(1))),
    c(2024, 11)                                  # observed legacy folder
  )

  for (d in dirs) {
    for (nn in sprintf("%02d", 1:28)) {
      url <- sprintf(
        "https://www.flylcpa.com/app/uploads/%d/%02d/%s-%s-%s-%d-Airport-Statistics.pdf",
        d[1], d[2], yy, nn, mname, year)
      if (http_ok(url)) return(url)
    }
  }
  NA_character_
}

say("checking RSW airport releases...")

rsw <- if (file.exists("data/rsw_monthly_passengers.csv")) {
  read_csv("data/rsw_monthly_passengers.csv", show_col_types = FALSE)
} else NULL

new_rsw_months <- character()

if (!is.null(rsw)) {
  last <- rsw %>% arrange(year, month) %>% slice_tail(n = 1)
  nxt  <- ymd(paste(last$year, last$month, 1)) %m+% months(1)

  # Only look for months that have finished and had time to be published.
  while (nxt %m+% months(1) < today() && length(new_rsw_months) < 6) {
    say("  looking for", MONTH_NAMES[month(nxt)], year(nxt), "...")
    url <- find_release(year(nxt), month(nxt))

    if (is.na(url)) { say("    not published yet"); break }

    cache <- sprintf("data/raw/rsw_%d_%02d.pdf", year(nxt), month(nxt))
    download.file(url, cache, mode = "wb", quiet = TRUE)
    txt <- pdf_text(cache)[1]
    m <- str_match(txt, "During\\s+\\w+,?\\s+([0-9][0-9,]*)\\s+passengers")

    if (!is.na(m[1, 2])) {
      n <- as.numeric(str_remove_all(m[1, 2], ","))
      say("    FOUND:", format(n, big.mark = ","), "passengers")
      new_rsw_months <- c(new_rsw_months,
                          sprintf("%s %d: %s passengers",
                                  MONTH_NAMES[month(nxt)], year(nxt),
                                  format(n, big.mark = ",")))
      rsw <- bind_rows(rsw, tibble(year = year(nxt), month = month(nxt),
                                   passengers = n))
      write_csv(arrange(rsw, year, month), "data/rsw_monthly_passengers.csv")
    }
    nxt <- nxt %m+% months(1)
  }
}

if (length(new_rsw_months) > 0) {
  changes[["rsw"]] <- list(
    source = "RSW airport monthly passengers",
    old = "-", new = paste(new_rsw_months, collapse = "; "),
    detail = paste0("New month(s) published: ", paste(new_rsw_months, collapse = "; "),
                    ". This feeds the arrival-timing analysis (are snowbirds ",
                    "coming earlier), not the peak/trough forecast."))
}

# =============================================================================
# SOURCE 3 - Open-Meteo weather (daily; barely moves anything)
# =============================================================================
say("checking Open-Meteo...")

wx <- if (file.exists("data/weather_daily.csv")) {
  read_csv("data/weather_daily.csv", show_col_types = FALSE)
} else NULL

if (!is.null(wx)) {
  have_to <- max(wx$date, na.rm = TRUE)
  archive_to <- today() - 6          # the archive runs about 5-6 days behind
  gap <- as.numeric(archive_to - have_to)
  state <- put_state(state, "weather_to", format(have_to))
  say("  weather data to", format(have_to), "| archive has ~", gap, "more days")
  if (gap > 30) {
    changes[["weather"]] <- list(
      source = "Open-Meteo weather archive",
      old = format(have_to), new = format(archive_to),
      detail = paste0(gap, " days of new temperature data are available. ",
                      "Delete data/raw/weather_*.csv and re-run R/01 to pull them. ",
                      "Note this moves a 26-year trend very little."))
  }
}

# =============================================================================
# RE-RUN WHAT CHANGED
# =============================================================================
if (length(new_rsw_months) > 0) {
  say("re-running arrival-timing analysis (R/11)...")
  r <- try(source("R/11_are_they_coming_earlier.R", local = new.env(), echo = FALSE),
           silent = TRUE)
  if (inherits(r, "try-error")) say("  R/11 failed:", conditionMessage(attr(r, "condition")))
}

# =============================================================================
# CURRENT PREDICTIONS
# =============================================================================
# Read whatever the analysis currently says, so we can compare it to last time.
current <- NULL
if (file.exists("output/season_forecast.csv")) {
  fc <- read_csv("output/season_forecast.csv", show_col_types = FALSE)

  next_occ <- function(doy) {
    if (is.na(doy)) return(as.Date(NA))
    d <- as.Date(paste0(year(today()), "-01-01")) + (doy - 1)
    if (d < today()) d <- as.Date(paste0(year(today()) + 1, "-01-01")) + (doy - 1)
    d
  }

  current <- tibble(
    run_at       = format(NOW),
    peak_date    = format(next_occ(fc$peak_doy)),
    trough_date  = format(next_occ(fc$trough_doy)),
    start_date   = format(next_occ(fc$start_doy)),
    end_date     = format(next_occ(fc$end_doy)),
    decline_pct  = round(fc$decline_pct, 1),
    increase_pct = round(fc$increase_pct, 1)
  )
}

history <- if (file.exists(HISTORY_FILE)) {
  read_csv(HISTORY_FILE, show_col_types = FALSE, col_types = cols(.default = col_character()))
} else NULL

alerts <- tibble()

if (!is.null(current)) {
  if (is.null(history) || nrow(history) == 0) {
    say("first run - recording baseline predictions")
  } else {
    prev <- history %>% slice_tail(n = 1)

    # What caused any change? If exactly one source moved, attribution is
    # unambiguous. If none did, a prediction shift means something else was
    # edited by hand - which is worth flagging loudly.
    cause <- if (length(changes) == 0) {
      "no upstream source changed - was the analysis or a script edited by hand?"
    } else {
      paste(map_chr(changes, "source"), collapse = " + ")
    }

    for (f in c("peak_date", "trough_date", "start_date", "end_date")) {
      o <- prev[[f]]; n <- current[[f]]
      if (!is.na(o) && !is.na(n) && o != n) {
        shift <- as.numeric(as.Date(n) - as.Date(o))
        alerts <- bind_rows(alerts, tibble(
          detected_at = format(NOW),
          field = f,
          old_value = o, new_value = n,
          change = sprintf("%+d days", shift),
          caused_by = cause,
          detail = if (length(changes) > 0)
            paste(map_chr(changes, "detail"), collapse = " | ") else
            "No source fingerprint changed this run."
        ))
      }
    }

    for (f in c("decline_pct", "increase_pct")) {
      o <- suppressWarnings(as.numeric(prev[[f]]))
      n <- suppressWarnings(as.numeric(current[[f]]))
      if (!is.na(o) && !is.na(n) && abs(n - o) >= 0.5) {
        alerts <- bind_rows(alerts, tibble(
          detected_at = format(NOW), field = f,
          old_value = as.character(o), new_value = as.character(n),
          change = sprintf("%+.1f points", n - o),
          caused_by = cause,
          detail = paste(map_chr(changes, "detail"), collapse = " | ")
        ))
      }
    }
  }

  write_csv(bind_rows(history, mutate(current, across(everything(), as.character))),
            HISTORY_FILE)
}

# Sources that changed but did not move a prediction are still worth recording.
for (nm in names(changes)) {
  ch <- changes[[nm]]
  already <- nrow(alerts) > 0 && any(str_detect(alerts$caused_by, fixed(ch$source)))
  if (!already) {
    alerts <- bind_rows(alerts, tibble(
      detected_at = format(NOW), field = "new data",
      old_value = as.character(ch$old), new_value = as.character(ch$new),
      change = "no change to headline dates",
      caused_by = ch$source, detail = ch$detail))
  }
}

if (nrow(alerts) > 0) {
  old_alerts <- if (file.exists(ALERT_FILE))
    read_csv(ALERT_FILE, show_col_types = FALSE, col_types = cols(.default = col_character()))
  else NULL
  write_csv(bind_rows(old_alerts, mutate(alerts, across(everything(), as.character))),
            ALERT_FILE)

  cat("\n")
  cat("=====================================================================\n")
  cat("  ", nrow(alerts), " ALERT(S)\n", sep = "")
  cat("=====================================================================\n")
  for (i in seq_len(nrow(alerts))) {
    a <- alerts[i, ]
    cat("\n", a$field, ": ", a$old_value, " -> ", a$new_value,
        "  (", a$change, ")\n", sep = "")
    cat("  caused by: ", a$caused_by, "\n", sep = "")
    cat("  ", str_wrap(a$detail, 66, exdent = 2), "\n", sep = "")
  }
  cat("\n")
} else {
  say("no changes - predictions unchanged")
}

write_csv(state, STATE_FILE)
say("done")
