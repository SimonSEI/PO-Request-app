# =============================================================================
# AUTOMATIC DISCOUNTED RESENDS - with a kill switch
# =============================================================================
# Every 7am run, quotes that are due go out with 10% off, provided ALL of:
#
#   - the switch on the page is ON (it starts OFF, and is re-read right before
#     EACH send, so turning it off stops a run part-way)
#   - the quote is 'awaiting response' (never 'changes requested')
#   - its resend date has arrived
#   - the client is a confirmed or likely snowbird
#   - the client is NOT a business, HOA or landscaping/trade company
#   - the quote is between SNOWBIRD_MIN_QUOTE_AGE_MONTHS (default 3) and
#     SNOWBIRD_MAX_QUOTE_AGE_MONTHS (default 13) months old
#   - its total is under SNOWBIRD_MAX_QUOTE_VALUE (default $14,000)
#   - this quote has never been sent by this service before
#   - today's cap has not been reached
#
# Only the scheduled 7am run sends. "Refresh now" never does.
# Every attempt, sent or skipped, is written to sent_quotes.csv on the volume.
# =============================================================================

SWITCH_FILE <- file.path(JOBBER_DIR, "auto_send_switch.rds")
SENT_LOG    <- file.path(JOBBER_DIR, "sent_quotes.csv")
DRYRUN_LOG  <- file.path(JOBBER_DIR, "dry_run_log.csv")
DAILY_CAP   <- as.integer(Sys.getenv("AUTO_SEND_DAILY_CAP", "10"))

# Same setting R/18 uses to build the plan. Re-read here rather than trusted
# from the file, so the sender enforces today's rule, not the rule that was in
# force whenever the plan on the volume happened to be written.
MIN_QUOTE_AGE_MONTHS <- as.integer(Sys.getenv("SNOWBIRD_MIN_QUOTE_AGE_MONTHS", "3"))
MAX_QUOTE_AGE_MONTHS <- as.integer(Sys.getenv("SNOWBIRD_MAX_QUOTE_AGE_MONTHS", "13"))
MAX_QUOTE_VALUE      <- as.numeric(Sys.getenv("SNOWBIRD_MAX_QUOTE_VALUE", "14000"))

# The Jobber calls that discount and send a quote are written only after the
# schema probe shows what this API version actually offers. Until then this
# stays FALSE and the switch cannot send anything, whatever its position.
SEND_READY <- FALSE

switch_state <- function() {
  if (!file.exists(SWITCH_FILE)) return(list(on = FALSE, changed_at = NA, changed_by = NA))
  readRDS(SWITCH_FILE)
}

set_switch <- function(on, by = "dashboard") {
  saveRDS(list(on = isTRUE(on), changed_at = Sys.time(), changed_by = by), SWITCH_FILE)
  log_line("auto-send switch turned ", if (isTRUE(on)) "ON" else "OFF", " (", by, ")")
}

sent_log <- function() {
  if (!file.exists(SENT_LOG)) return(tibble(quote_id = character(), quote_number = character(),
                                            client = character(), attempted_at = character(),
                                            total = character(), total_10pct_off = character(),
                                            result = character()))
  read_csv(SENT_LOG, col_types = cols(.default = col_character()))
}

append_sent <- function(row) {
  write_csv(row, SENT_LOG, append = file.exists(SENT_LOG), na = "")
}

# ---------------------------------------------------------------------------
# Dry run: the record of what WOULD have gone out
# ---------------------------------------------------------------------------
# The 7am run already logs a count when it declines to send, but a count is not
# reviewable - by the time anyone asks "who exactly would that have been?" the
# plan has been rebuilt underneath them. So every declined run writes the names
# too, and they accumulate. Before the switch is ever turned on, this file is
# the evidence for whether the rules pick the right people.
#
# would_send models the cap as well as the rules: the sender takes the first
# DAILY_CAP rows of an already-sorted list, so the rest would wait for tomorrow
# even though they qualify today.
dry_run_log <- function() {
  if (!file.exists(DRYRUN_LOG)) return(tibble(run_at = character(), reason = character(),
                                              quote_id = character(), quote_number = character(),
                                              client = character(), resend_on = character(),
                                              total = character(), total_10pct_off = character(),
                                              would_send = character()))
  read_csv(DRYRUN_LOG, col_types = cols(.default = col_character()))
}

record_dry_run <- function(due, reason) {
  if (nrow(due) == 0) return(invisible(0))
  cap  <- min(nrow(due), DAILY_CAP)
  rows <- tibble(
    run_at          = format(Sys.time(), "%Y-%m-%d %H:%M", tz = TZ),
    reason          = reason,
    quote_id        = due$quote_id,
    quote_number    = due$quote_number,
    client          = due$client,
    resend_on       = due$resend_on,
    total           = due$total,
    total_10pct_off = due$total_10pct_off,
    would_send      = c(rep("yes", cap),
                        rep(paste0("no - past today's cap of ", DAILY_CAP), nrow(due) - cap)))
  write_csv(rows, DRYRUN_LOG, append = file.exists(DRYRUN_LOG), na = "")
  log_line("dry run (", reason, "): ", cap, " would go, ", nrow(due) - cap, " would wait")
  invisible(nrow(rows))
}

# What WOULD go out now, before the switch and the cap are applied.
due_for_auto_send <- function(plan_path, today = as.Date(format(Sys.time(), tz = TZ))) {
  if (!file.exists(plan_path)) return(tibble())
  p <- read_csv(plan_path, col_types = cols(.default = col_character()))
  if (!"quote_id" %in% names(p)) return(tibble())
  already <- sent_log() %>% filter(result == "sent") %>% pull(quote_id)

  # ---------------------------------------------------------------------------
  # Belt and braces on the two "never send" rules
  # ---------------------------------------------------------------------------
  # R/18 already drops organisations and over-age quotes when it builds the
  # plan. This is the last gate before an email actually leaves, and the plan
  # is a file on a volume that can outlive the code that wrote it - so both
  # rules are checked again here. A plan with no such columns fails closed.
  if (!"client_is_company" %in% names(p)) p$client_is_company <- NA_character_
  if (!"quote_created"     %in% names(p)) p$quote_created     <- NA_character_

  oldest  <- lubridate::`%m-%`(today, lubridate::period(months = MAX_QUOTE_AGE_MONTHS))
  newest  <- lubridate::`%m-%`(today, lubridate::period(months = MIN_QUOTE_AGE_MONTHS))
  created <- suppressWarnings(as.Date(p$quote_created))
  value   <- suppressWarnings(as.numeric(p$total))
  is_co   <- tolower(str_squish(p$client_is_company)) %in% c("yes", "true", "t", "1")

  too_old   <- is.na(created) | created < oldest
  too_new   <- !is.na(created) & created > newest
  too_big   <- is.na(value) | value >= MAX_QUOTE_VALUE
  blocked   <- is_co | too_old | too_new | too_big

  if (any(blocked)) {
    log_line("auto-send: ", sum(blocked), " quote(s) held back - ",
             sum(is_co), " company/HOA, ",
             sum(!is_co & too_old), " older than ", MAX_QUOTE_AGE_MONTHS, " months, ",
             sum(!is_co & !too_old & too_new), " newer than ", MIN_QUOTE_AGE_MONTHS, " months, ",
             sum(!is_co & !too_old & !too_new & too_big), " at or above the value ceiling")
    p <- p[!blocked, , drop = FALSE]
  }

  p %>%
    filter(quote_status == "awaiting_response",
           str_starts(snowbird_status, "Second home"),
           as.Date(resend_on) <= today,
           !(quote_id %in% already)) %>%
    arrange(resend_on, desc(as.numeric(total)))
}

# Placeholder until the probe confirms the right mutations. Must: re-check the
# quote is still awaiting response live in Jobber, apply 10% off, send it.
send_discounted_quote <- function(quote_id) {
  stop("sending is not built yet - waiting on the Jobber schema probe", call. = FALSE)
}

# ---------------------------------------------------------------------------
# One quote, sent on purpose by a person
# ---------------------------------------------------------------------------
# The switch governs the unattended 7am run. Someone reading the queue and
# choosing a single quote is a different decision, so this does not consult the
# switch - but it gets no shortcut round the rules either. Eligibility is
# re-derived through due_for_auto_send(), the same gate the automatic run uses,
# so a company, a quote outside the age window, one over the value ceiling or
# one already sent cannot be pushed through by hand. The id is matched against
# that list rather than trusted, so a stale page cannot send the wrong quote.
#
# The log row records result "sent" exactly as the automatic path does, because
# both the never-send-twice check and the daily count read that value. Who
# pressed it goes to the refresh log rather than a new column: sent_quotes.csv
# already exists on the volume, and appending a wider row would misalign it.
send_one_quote <- function(plan_path, quote_id, by = "dashboard") {
  due <- due_for_auto_send(plan_path)
  q   <- due[due$quote_id == quote_id, , drop = FALSE]
  if (nrow(q) == 0)
    return(list(ok = FALSE,
                msg = paste("That quote is no longer eligible - it may have been sent already,",
                            "answered, or fallen outside the rules. Nothing was sent.")))
  if (!SEND_READY)
    return(list(ok = FALSE,
                msg = paste("Sending is not built yet - it waits on the Jobber API check.",
                            "Nothing was sent.")))

  q   <- q[1, ]
  res <- tryCatch({ send_discounted_quote(q$quote_id); "sent" },
                  error = function(e) paste("failed:", conditionMessage(e)))
  append_sent(tibble(quote_id = q$quote_id, quote_number = q$quote_number, client = q$client,
                     attempted_at = format(Sys.time(), "%Y-%m-%d %H:%M", tz = TZ),
                     total = q$total, total_10pct_off = q$total_10pct_off, result = res))
  log_line("send now by ", by, ": ", q$quote_number, " (", q$client, ") - ", res)
  list(ok  = identical(res, "sent"),
       msg = if (identical(res, "sent"))
               sprintf("Sent %s to %s with 10%% off.", q$quote_number, q$client)
             else sprintf("Could not send %s: %s", q$quote_number, sub("^failed: ", "", res)))
}

run_auto_send <- function(plan_path) {
  due <- due_for_auto_send(plan_path)
  if (nrow(due) == 0) { log_line("auto-send: nothing due"); return(invisible(0)) }
  if (!switch_state()$on) {
    log_line("auto-send: switch is OFF - ", nrow(due), " quote(s) would have been sent")
    record_dry_run(due, "switch OFF")
    return(invisible(0))
  }
  if (!SEND_READY) {
    log_line("auto-send: switch is ON but sending is not built yet - ", nrow(due), " quote(s) waiting")
    record_dry_run(due, "sending not built yet")
    return(invisible(0))
  }

  sent_today <- sent_log() %>%
    filter(result == "sent", as.Date(substr(attempted_at, 1, 10)) == as.Date(format(Sys.time(), tz = TZ))) %>%
    nrow()
  n <- 0
  for (i in seq_len(nrow(due))) {
    if (sent_today + n >= DAILY_CAP) { log_line("auto-send: daily cap of ", DAILY_CAP, " reached"); break }
    # Re-read the switch before EVERY send so turning it off stops the run.
    if (!switch_state()$on) { log_line("auto-send: switch turned OFF mid-run - stopping"); break }
    q <- due[i, ]
    res <- tryCatch({ send_discounted_quote(q$quote_id); "sent" },
                    error = function(e) paste("failed:", conditionMessage(e)))
    append_sent(tibble(quote_id = q$quote_id, quote_number = q$quote_number, client = q$client,
                       attempted_at = format(Sys.time(), "%Y-%m-%d %H:%M", tz = TZ),
                       total = q$total, total_10pct_off = q$total_10pct_off, result = res))
    if (res == "sent") n <- n + 1
  }
  log_line("auto-send: ", n, " sent")
  invisible(n)
}
