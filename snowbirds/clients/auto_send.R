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
#   - this quote has never been sent by this service before
#   - today's cap has not been reached
#
# Only the scheduled 7am run sends. "Refresh now" never does.
# Every attempt, sent or skipped, is written to sent_quotes.csv on the volume.
# =============================================================================

SWITCH_FILE <- file.path(JOBBER_DIR, "auto_send_switch.rds")
SENT_LOG    <- file.path(JOBBER_DIR, "sent_quotes.csv")
DAILY_CAP   <- as.integer(Sys.getenv("AUTO_SEND_DAILY_CAP", "10"))

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

# What WOULD go out now, before the switch and the cap are applied.
due_for_auto_send <- function(plan_path, today = as.Date(format(Sys.time(), tz = TZ))) {
  if (!file.exists(plan_path)) return(tibble())
  p <- read_csv(plan_path, col_types = cols(.default = col_character()))
  if (!"quote_id" %in% names(p)) return(tibble())
  already <- sent_log() %>% filter(result == "sent") %>% pull(quote_id)
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

run_auto_send <- function(plan_path) {
  due <- due_for_auto_send(plan_path)
  if (nrow(due) == 0) { log_line("auto-send: nothing due"); return(invisible(0)) }
  if (!switch_state()$on) {
    log_line("auto-send: switch is OFF - ", nrow(due), " quote(s) would have been sent")
    return(invisible(0))
  }
  if (!SEND_READY) {
    log_line("auto-send: switch is ON but sending is not built yet - ", nrow(due), " quote(s) waiting")
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
