# =============================================================================
# BACKGROUND REFRESH - runs in its own R process, never inside the web app
# =============================================================================
#   Rscript clients/refresh_job.R <scope> <send> <trigger>
#     scope    quotes | all        (see R/17)
#     send     send | nosend       only the 7am run passes "send"
#     trigger  free text for the log, e.g. "every 30 min"
#
# Why a separate process: Shiny serves every visitor from ONE R process. When
# the refresh ran inside it, the page could not respond until the pull finished
# - 20 minutes on 35,000 records - which looked exactly like a freeze.
#
# A lock file stops two refreshes overlapping (a scheduled run and a click).
# A status file tells the page what is happening; the page watches it.
# =============================================================================

args    <- commandArgs(trailingOnly = TRUE)
scope   <- if (length(args) >= 1) args[1] else "quotes"
send    <- length(args) >= 2 && args[2] == "send"
trigger <- if (length(args) >= 3) args[3] else "manual"

ROOT <- normalizePath(Sys.getenv("APP_ROOT", "."))
setwd(ROOT)
suppressPackageStartupMessages({ library(tidyverse); library(jsonlite) })
source("R/jobber_api.R")
source("clients/fetch_roll.R")

TZ       <- "America/New_York"
OUT_DIR  <- Sys.getenv("SNOWBIRD_CLIENT_OUT", "output/clients")
PLAN_CSV <- file.path(OUT_DIR, "quote_resend_plan.csv")
LOG_FILE <- file.path(JOBBER_DIR, "refresh_log.txt")
LOCK     <- file.path(JOBBER_DIR, "refresh.lock")
STATUS   <- file.path(JOBBER_DIR, "refresh_status.json")

log_line <- function(...) {
  line <- paste(format(Sys.time(), "%Y-%m-%d %H:%M %Z", tz = TZ), "|", paste0(...))
  message(line)
  cat(line, "\n", file = LOG_FILE, append = TRUE, sep = "")
}
source("clients/auto_send.R", local = TRUE)

write_status <- function(...) {
  old <- if (file.exists(STATUS)) tryCatch(fromJSON(STATUS), error = function(e) list()) else list()
  new <- modifyList(old, list(...))
  tmp <- paste0(STATUS, ".partial")
  write_json(new, tmp, auto_unbox = TRUE, pretty = TRUE)
  invisible(file.rename(tmp, STATUS))
}

# --- lock ---------------------------------------------------------------------
# A lock older than 45 minutes belongs to a run that died (a redeploy mid-pull);
# take it over rather than blocking refreshes forever.
if (file.exists(LOCK) && difftime(Sys.time(), file.mtime(LOCK), units = "mins") < 45) {
  message("Refresh already running - skipping (", trigger, ")")
  quit(save = "no", status = 0)
}
writeLines(as.character(Sys.getpid()), LOCK)
on_exit <- function() unlink(LOCK)

now_txt <- function() format(Sys.time(), "%Y-%m-%d %H:%M:%S", tz = TZ)
write_status(state = "running", scope = scope, trigger = trigger, started = now_txt(), message = "")

if (!file.exists(TOKEN_FILE)) {
  write_status(state = "idle", message = "Jobber is not connected yet.")
  log_line(trigger, ": skipped, Jobber is not connected")
  on_exit(); quit(save = "no", status = 0)
}

res <- tryCatch({
  ensure_collier_roll(Sys.getenv("COLLIER_ROLL", "data/raw/collier_int_parcels.csv"))
  Sys.setenv(PULL_SCOPE = scope)
  source("R/17_jobber_pull.R", local = new.env())
  source("R/18_client_second_homes.R", local = new.env())
  if (!file.exists(file.path(JOBBER_DIR, "schema_probe.json"))) try(jobber_probe_schema())
  "done"
}, error = function(e) paste("failed:", conditionMessage(e)))

log_line(trigger, " (", scope, "): ", res)
fields <- list(state = if (res == "done") "done" else "failed", finished = now_txt(), message = res)
if (res == "done") {
  fields$last_quotes <- now_txt()
  if (scope == "all") fields$last_all <- now_txt()
}
do.call(write_status, fields)

if (send && res == "done") {
  tryCatch(run_auto_send(PLAN_CSV), error = function(e) log_line("auto-send failed: ", conditionMessage(e)))
  write_status(last_send_run = format(Sys.Date(), "%Y-%m-%d"))
}

on_exit()
