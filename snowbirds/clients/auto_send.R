# =============================================================================
# DISCOUNTED RESENDS - discount by API, sent from Jobber
# =============================================================================
# Jobber's API has no mutation that emails a quote. It was checked against the
# live schema: of 109 mutations, the quote ones are create, edit, line items
# and notes, and none of them sends anything. Setting sentAt marks the record
# without emailing the client. So this service cannot be the thing that sends.
#
# What it can do is the half that is automatable: apply the 10% discount
# through the API, then hand the quote to a person to press Send in Jobber.
# The client then gets Jobber's own email and PDF, and - the reason for doing
# it this way - the send lands in that client's Jobber communications log,
# which an email from us never would.
#
# A quote is eligible to be prepared when ALL of:
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
#   - this quote has not already been prepared or sent by this service
#   - today's cap has not been reached
#
# Nothing here emails a client, so no run - 7am or otherwise - can send. The
# 7am run records what is due and stops. Applying a discount is always a
# deliberate click, because it writes to a real quote in the Jobber account.
# Every attempt is written to sent_quotes.csv on the volume.
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

# Sending from here is not merely unbuilt, it is not offered by the API. This
# stays FALSE so the automatic run can never email anyone; it would only become
# TRUE if the resends were ever moved onto our own mail server, which would
# also take them out of Jobber's communications log.
SEND_READY <- FALSE

# Applying the discount DOES write to a live quote in the Jobber account, so it
# is off until someone turns it on deliberately and watches the first one. The
# mutation name is configurable because it is the one piece not confirmed by
# reading the schema here - if this API version calls it something else, set
# JOBBER_QUOTE_EDIT_MUTATION rather than editing code.
DISCOUNT_ENABLED    <- Sys.getenv("JOBBER_DISCOUNT_ENABLED", "") %in% c("1", "true", "yes", "on")
QUOTE_EDIT_MUTATION <- Sys.getenv("JOBBER_QUOTE_EDIT_MUTATION", "quoteEdit")
DISCOUNT_PCT        <- as.numeric(Sys.getenv("SNOWBIRD_DISCOUNT_PCT", "10"))
PROBE_FILE          <- file.path(JOBBER_DIR, "schema_probe.json")

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
  # "prepared" counts as done: its discount is already on the quote in Jobber
  # and it is waiting for a person to press Send. Offering it again would apply
  # a second 10% off. It stays visible in the prepared list instead.
  already <- sent_log() %>% filter(result %in% c("sent", "prepared")) %>% pull(quote_id)

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

# Kept so the automatic path has something to refuse against. There is nothing
# to write here: this API version has no mutation that emails a quote, so a
# send can only happen in Jobber, by a person.
send_discounted_quote <- function(quote_id) {
  stop("Jobber's API cannot send a quote - it has to be sent from Jobber", call. = FALSE)
}

# ---------------------------------------------------------------------------
# Applying the discount
# ---------------------------------------------------------------------------
# The one thing the schema check did not pin down is what this API version
# calls its quote-edit mutation and how the discount field is shaped. Rather
# than guess and find out by writing to a real client's quote, the saved probe
# is consulted first: if it does not list the mutation, or lists it without a
# discount field, nothing is attempted and the message says what was found.
quote_edit_offered <- function() {
  if (!file.exists(PROBE_FILE))
    return(list(ok = NA, msg = "no schema check on file yet - open the Jobber API tab and run it"))
  p <- tryCatch(jsonlite::fromJSON(PROBE_FILE, simplifyDataFrame = FALSE), error = function(e) NULL)
  if (is.null(p) || is.null(p$mutations))
    return(list(ok = NA, msg = "the schema check on file could not be read"))
  m <- Filter(function(x) identical(x$mutation, QUOTE_EDIT_MUTATION), p$mutations)
  if (length(m) == 0) {
    seen <- paste(vapply(p$mutations, function(x) as.character(x$mutation %||% ""), character(1)),
                  collapse = ", ")
    return(list(ok = FALSE,
                msg = paste0("the schema check lists no mutation called '", QUOTE_EDIT_MUTATION,
                             "'. What it did find: ", seen,
                             ". Set JOBBER_QUOTE_EDIT_MUTATION to the right one")))
  }
  flds <- unlist(lapply(m[[1]]$args, function(a) a$fields))
  if (!any(grepl("discount", flds, ignore.case = TRUE)))
    return(list(ok = FALSE,
                msg = paste0("'", QUOTE_EDIT_MUTATION,
                             "' exists but the schema check lists no discount field on its input")))
  list(ok = TRUE, msg = "")
}

apply_quote_discount <- function(quote_id, pct = DISCOUNT_PCT) {
  if (!DISCOUNT_ENABLED)
    return(list(ok = FALSE,
                msg = paste("Applying discounts is turned off. Set JOBBER_DISCOUNT_ENABLED=true",
                            "once you are ready for this to write to real quotes.")))
  chk <- quote_edit_offered()
  if (identical(chk$ok, FALSE)) return(list(ok = FALSE, msg = paste0("Not attempted - ", chk$msg, ".")))

  q <- sprintf(paste0("mutation($id: EncodedId!, $input: QuoteEditAttributes!) { ",
                      "%s(id: $id, input: $input) { quote { id } userErrors { message } } }"),
               QUOTE_EDIT_MUTATION)
  res <- tryCatch(jobber_gql(q, list(id = quote_id, input = list(discount = pct))),
                  error = function(e) e)
  if (inherits(res, "error")) return(list(ok = FALSE, msg = conditionMessage(res)))
  errs <- res[[QUOTE_EDIT_MUTATION]]$userErrors
  if (length(errs) > 0)
    return(list(ok = FALSE,
                msg = paste(vapply(errs, function(e) as.character(e$message %||% ""), character(1)),
                            collapse = "; ")))
  list(ok = TRUE, msg = "")
}

# ---------------------------------------------------------------------------
# One quote, prepared on purpose by a person
# ---------------------------------------------------------------------------
# Applies the discount and hands back the Jobber link, so whoever clicked can
# press Send there. It gets no shortcut round the rules: eligibility is
# re-derived through due_for_auto_send(), the same gate everything else uses,
# and the row's quote id is matched against that list rather than trusted, so a
# page left open while the plan moved on cannot discount the wrong quote.
#
# The log row records "prepared", not "sent", because this service cannot know
# whether the person went on to press Send. That is the honest state, and it is
# enough to stop the quote being offered again and discounted twice.
prepare_one_quote <- function(plan_path, quote_id, by = "dashboard") {
  due <- due_for_auto_send(plan_path)
  q   <- due[due$quote_id == quote_id, , drop = FALSE]
  if (nrow(q) == 0)
    return(list(ok = FALSE,
                msg = paste("That quote is no longer eligible - it may have been prepared already,",
                            "answered, or fallen outside the rules. Nothing was changed.")))
  q <- q[1, ]
  r   <- apply_quote_discount(q$quote_id)
  res <- if (isTRUE(r$ok)) "prepared" else paste("failed:", r$msg)
  append_sent(tibble(quote_id = q$quote_id, quote_number = q$quote_number, client = q$client,
                     attempted_at = format(Sys.time(), "%Y-%m-%d %H:%M", tz = TZ),
                     total = q$total, total_10pct_off = q$total_10pct_off, result = res))
  log_line("prepare by ", by, ": ", q$quote_number, " (", q$client, ") - ", res)
  list(ok   = isTRUE(r$ok),
       link = q$jobber_link,
       msg  = if (isTRUE(r$ok))
                sprintf("%s now has %g%% off. Open it in Jobber and press Send.",
                        q$quote_number, DISCOUNT_PCT)
              else sprintf("Could not discount %s: %s", q$quote_number, r$msg))
}

# Quotes discounted and waiting for someone to press Send in Jobber.
prepared_quotes <- function() {
  sent_log() %>% filter(result == "prepared") %>% arrange(desc(attempted_at))
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
    log_line("auto-send: switch is ON but Jobber's API cannot send a quote - ",
             nrow(due), " quote(s) waiting for someone to send them from Jobber")
    record_dry_run(due, "API cannot send - must be sent from Jobber")
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
