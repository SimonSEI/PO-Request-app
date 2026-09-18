# =============================================================================
# SNOWBIRD CLIENTS - the clients tool inside the Office App's Snowbirds app
# =============================================================================
# Part of the Office App: people open it from the Snowbirds card, and the
# Office App's own login and roles decide who gets in (admin and office only).
# It holds client names, addresses and quote values, so it keeps everything on
# its own Railway volume. Nothing here is in GitHub.
#
#   - Connect Jobber   read-only OAuth; the admin approves on Jobber's own page
#   - Every day 7am ET pull quotes, refresh the property roll monthly, rebuild
#                      the resend plan (R/17 + R/18)
#   - Resend plan      outstanding snowbird quotes in the order to resend them
#   - All clients      every client with the second-home evidence
#
# It never writes to Jobber and never sends anything to anyone.
#
# Railway variables (set in the Railway dashboard, never in code):
#   SNOWBIRDS_SSO_SECRET (shared with the Office App), OFFICE_APP_URL,
#   JOBBER_CLIENT_ID, JOBBER_CLIENT_SECRET, JOBBER_CALLBACK_URL
# =============================================================================

# The pipeline scripts use paths from the project root. Shiny runs button
# handlers from the app's own folder (clients/), NOT from wherever this file
# last setwd()'d - so anything that sources a script pins the folder itself
# with in_root(). Without it, Refresh failed with "cannot open the connection".
ROOT <- normalizePath(Sys.getenv("APP_ROOT", ".."))
in_root <- function(expr) {
  owd <- setwd(ROOT)
  on.exit(setwd(owd), add = TRUE)
  expr
}

suppressPackageStartupMessages({
  library(shiny); library(bslib); library(DT); library(tidyverse); library(later)
})
source(file.path(ROOT, "R/jobber_api.R"))
source(file.path(ROOT, "clients/fetch_roll.R"))
# local = TRUE: auto_send.R uses TZ and log_line from this file.
source(file.path(ROOT, "clients/auto_send.R"), local = TRUE)

OUT_DIR  <- Sys.getenv("SNOWBIRD_CLIENT_OUT", "output/clients")
PLAN_CSV <- file.path(OUT_DIR, "quote_resend_plan.csv")
DB_CSV   <- file.path(OUT_DIR, "client_second_homes.csv")
EXCL_CSV <- file.path(OUT_DIR, "excluded_from_plan.csv")
PROBE_JSON <- file.path(JOBBER_DIR, "schema_probe.json")
LOG_FILE <- file.path(JOBBER_DIR, "refresh_log.txt")
TZ       <- "America/New_York"
OFFICE_URL <- sub("/+$", "", Sys.getenv("OFFICE_APP_URL", "https://web-production-01609.up.railway.app"))

# -----------------------------------------------------------------------------
# Sign-in from the Office App
# -----------------------------------------------------------------------------
# The Office App (Python) checks its own login and role, then sends the browser
# here with a short-lived signed ticket:  base64url("sso|user|role|expiry").hmac
# signed with SNOWBIRDS_SSO_SECRET, which both services share and nobody types.
# A valid ticket becomes a 12-hour signed cookie so a page reload does not bounce
# people back to the Office App. Same format, purpose "session".
SSO_SECRET    <- Sys.getenv("SNOWBIRDS_SSO_SECRET")
ALLOWED_ROLES <- c("admin", "office")
SESSION_HOURS <- 12

b64url_decode <- function(s) {
  s <- chartr("-_", "+/", s)
  s <- paste0(s, strrep("=", (4 - nchar(s) %% 4) %% 4))
  rawToChar(openssl::base64_decode(s))
}

sign_ticket <- function(purpose, user, role, expires) {
  payload <- paste(purpose, user, role, as.integer(expires), sep = "|")
  sig <- as.character(openssl::sha256(payload, key = SSO_SECRET))
  paste0(b64url(charToRaw(payload)), ".", sig)
}

# Returns list(user, role) for a valid, unexpired ticket of that purpose; else NULL.
verify_ticket <- function(ticket, purpose) {
  if (!nzchar(SSO_SECRET) || is.null(ticket) || !nzchar(ticket)) return(NULL)
  parts <- strsplit(ticket, ".", fixed = TRUE)[[1]]
  if (length(parts) != 2) return(NULL)
  payload <- tryCatch(b64url_decode(parts[1]), error = function(e) NA_character_)
  if (is.na(payload)) return(NULL)
  expected <- as.character(openssl::sha256(payload, key = SSO_SECRET))
  # Compare digests of the two signatures so the comparison time does not leak
  # how many leading characters matched.
  if (!identical(as.character(openssl::sha256(parts[2])), as.character(openssl::sha256(expected)))) return(NULL)
  f <- strsplit(payload, "|", fixed = TRUE)[[1]]
  if (length(f) != 4 || f[1] != purpose) return(NULL)
  if (suppressWarnings(as.numeric(f[4])) < as.numeric(Sys.time())) return(NULL)
  if (!(f[3] %in% ALLOWED_ROLES)) return(NULL)
  list(user = f[2], role = f[3])
}

read_cookie <- function(cookie_header, name) {
  if (is.null(cookie_header) || !nzchar(cookie_header)) return(NULL)
  kv <- strsplit(strsplit(cookie_header, ";\\s*")[[1]], "=", fixed = FALSE)
  for (p in kv) if (length(p) >= 2 && p[1] == name) return(paste(p[-1], collapse = "="))
  NULL
}
dir.create(OUT_DIR, showWarnings = FALSE, recursive = TRUE)

log_line <- function(...) {
  line <- paste(format(Sys.time(), "%Y-%m-%d %H:%M %Z", tz = TZ), "|", paste0(...))
  message(line)
  cat(line, "\n", file = LOG_FILE, append = TRUE, sep = "")
}

# -----------------------------------------------------------------------------
# Keeping the data current - automatically, in the background
# -----------------------------------------------------------------------------
# Refreshes run as a separate R process (clients/refresh_job.R). The web app
# only starts them and watches the files they write, so the page stays usable
# the whole time. The schedule, all times Eastern:
#
#   every 30 min, 6am-9pm   quotes only (a couple of minutes) - quote status is
#                           what goes stale during the working day
#   2am                     everything: quotes, clients, job history
#   7am                     quotes, then the automatic resends (switch permitting)
#
# A check runs every 5 minutes and starts whatever is due. It also runs when
# the service starts, so a redeploy catches up straight away.
STATUS_FILE    <- file.path(JOBBER_DIR, "refresh_status.json")
LOCK_FILE      <- file.path(JOBBER_DIR, "refresh.lock")

# --- clear a lock left behind by a killed refresh -----------------------------
# The refresh runs as a CHILD of this process and writes its pid to the lock,
# removing it on exit. A redeploy that lands mid-pull kills it before that, and
# the lock survives on the volume. Both this app and refresh_job.R then refuse
# every refresh - scheduled and manual - for the full 45-minute timeout, and
# the only symptom is that "Refresh now" quietly does nothing.
#
# This process has just started, so any pid in that file is from the container
# that died. Check whether it is actually alive before deciding, so a lock held
# by a genuinely running refresh is never stolen.
local({
  if (!file.exists(LOCK_FILE) || !dir.exists("/proc")) return(invisible())
  pid   <- suppressWarnings(as.integer(readLines(LOCK_FILE, warn = FALSE)[1]))
  alive <- !is.na(pid) && dir.exists(file.path("/proc", pid))
  if (!alive) {
    unlink(LOCK_FILE)
    message("Cleared a stale refresh lock (pid ", pid, " is not running) - ",
            "a refresh was killed mid-pull, probably by a redeploy.")
  }
})
QUOTES_EVERY   <- as.numeric(Sys.getenv("QUOTES_REFRESH_MINUTES", "30"))
DAY_HOURS      <- 6:21

read_status <- function() {
  if (!file.exists(STATUS_FILE)) return(list())
  tryCatch(jsonlite::fromJSON(STATUS_FILE), error = function(e) list())
}
refresh_running <- function() {
  file.exists(LOCK_FILE) && difftime(Sys.time(), file.mtime(LOCK_FILE), units = "mins") < 45
}
minutes_since <- function(txt, now = Sys.time()) {
  if (is.null(txt) || length(txt) == 0 || is.na(txt) || !nzchar(txt)) return(Inf)
  as.numeric(difftime(now, as.POSIXct(txt, tz = TZ), units = "mins"))
}

# What should run right now, given the last status? list(scope, send, trigger)
# or NULL. Kept free of side effects so the schedule can be tested at any hour.
due_refresh <- function(s, now = Sys.time()) {
  lt    <- as.POSIXlt(now, tz = TZ)
  today <- format(lt, "%Y-%m-%d")
  if (lt$hour == 7 && !identical(s$last_send_run, today))
    return(list(scope = "quotes", send = TRUE, trigger = "7am refresh + resends"))
  if (lt$hour >= 2 && lt$hour < 6 && substr(s$last_all %||% "", 1, 10) != today)
    return(list(scope = "all", send = FALSE, trigger = "overnight full refresh"))
  if (lt$hour %in% DAY_HOURS && minutes_since(s$last_quotes, now) >= QUOTES_EVERY)
    return(list(scope = "quotes", send = FALSE, trigger = sprintf("every %d min", QUOTES_EVERY)))
  if (is.infinite(minutes_since(s$last_all, now)) && is.infinite(minutes_since(s$last_quotes, now)))
    return(list(scope = "all", send = FALSE, trigger = "first refresh"))
  NULL
}

start_refresh <- function(scope = "quotes", send = FALSE, trigger = "manual") {
  if (refresh_running()) return(FALSE)
  if (!file.exists(TOKEN_FILE)) return(FALSE)
  rscript <- file.path(R.home("bin"), "Rscript")
  system2(rscript, c(file.path(ROOT, "clients/refresh_job.R"), scope,
                     if (send) "send" else "nosend", shQuote(trigger)),
          wait = FALSE, stdout = "", stderr = "")
  TRUE
}

scheduler_tick <- function() {
  tryCatch({
    if (file.exists(TOKEN_FILE) && !refresh_running()) {
      d <- due_refresh(read_status())
      if (!is.null(d)) start_refresh(d$scope, send = d$send, trigger = d$trigger)
    }
  }, error = function(e) message("scheduler: ", conditionMessage(e)))
  later(scheduler_tick, 300)
}
# Off switch for automated tests, which otherwise wait on the queued job.
if (Sys.getenv("CLIENTS_NO_SCHEDULE") != "true") later(scheduler_tick, 20)

# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
CSS <- "
body { background:#E6E6EB; }
/* 1400px left a wide monitor mostly empty either side of a thirteen-column
   table. Use the screen that is there, with a cap so the prose columns do not
   run to an unreadable line length on an ultrawide. */
.wrap { max-width:2000px; margin:0 auto; padding:20px 24px 40px; }
.top-title { font-size:1.4rem; font-weight:700; letter-spacing:-.02em; color:#1D1D1F; }
.top-sub { font-size:.83rem; color:#6E6E73; }
.tile { background:#fff; border-radius:14px; padding:14px 16px; box-shadow:0 0 0 1px rgba(0,0,0,.045),0 1px 3px rgba(0,0,0,.055); height:100%; }
.tile-label { font-size:.78rem; color:#6E6E73; font-weight:500; }
.tile-num { font-size:1.6rem; font-weight:700; letter-spacing:-.03em; color:#1D1D1F; line-height:1.15; }
.tile-sub { font-size:.76rem; color:#8E8E93; margin-top:2px; }
.login { max-width:380px; margin:12vh auto; }
.note { font-size:.8rem; color:#6E6E73; }
table.dataTable { font-size:.84rem; border-collapse:separate; }

/* Room to breathe. The default DT cell is tight enough that thirteen columns
   read as one grey block, and long values collide with their neighbours. */
table.dataTable td, table.dataTable th { padding:10px 14px; vertical-align:top; }
table.dataTable thead th { font-weight:600; }
/* Long values wrap onto a second line instead of being clipped mid-word. */
table.dataTable td { white-space:normal; overflow-wrap:break-word; line-height:1.45; }
/* ...except dates, quote numbers and money, which must stay on one line. */
table.dataTable td.dt-nowrap, table.dataTable th.dt-nowrap { white-space:nowrap; }
table.dataTable td.dt-money, table.dataTable th.dt-money {
  white-space:nowrap; text-align:right; font-variant-numeric:tabular-nums;
}
table.dataTable tbody tr:hover td { background:#F2F6FA; }
table.dataTable tbody td { border-top:1px solid #ECECF0; }
/* Fill the card rather than sitting at whatever width the columns happen to
   add up to, which left a band of empty white down the right-hand side. */
table.dataTable { width:100% !important; }
.dataTables_wrapper { width:100%; }

/* Keep the column headings visible while reading down a long table. These
   tables run to hundreds of rows and the plan has twelve columns, so by the
   time you are half way down there is no way to tell which column is which.
   position:sticky keeps the header row pinned to the top of the viewport as
   the page scrolls, and an opaque background stops rows showing through it. */
table.dataTable thead th {
  position: sticky;
  top: 0;
  z-index: 3;
  background: #fff;
  box-shadow: inset 0 -1px 0 rgba(0,0,0,.12);
}
/* DT puts its sort arrows on a pseudo-element that would otherwise sit under
   the pinned row. */
table.dataTable thead th:before, table.dataTable thead th:after { z-index: 4; }
/* scrollX wraps the table in its own scroller; let the sticky header work
   inside it as well as on the page. */
.dataTables_scrollBody { overflow-y: visible !important; }
"

ui <- page_fluid(
  title = "Snowbird Clients",
  theme = bs_theme(version = 5, bg = "#FFFFFF", fg = "#1D1D1F", primary = "#0071E3",
                   base_font = font_collection("-apple-system", "BlinkMacSystemFont", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif")),
  tags$head(
    tags$style(HTML(CSS)),
    tags$meta(name = "robots", content = "noindex, nofollow"),
    tags$script(HTML("
      Shiny.addCustomMessageHandler('go', function(url) { window.location.href = url; });
      Shiny.addCustomMessageHandler('cleanUrl', function(x) { history.replaceState(null, '', location.pathname); });
      Shiny.addCustomMessageHandler('setSession', function(x) {
        document.cookie = 'sb_session=' + x.value + '; path=/; max-age=' + x.maxAge + '; secure; samesite=lax';
      });
      Shiny.addCustomMessageHandler('clearSession', function(x) {
        document.cookie = 'sb_session=; path=/; max-age=0; secure; samesite=lax';
        window.location.href = x;
      });
    "))
  ),
  uiOutput("page")
)

# -----------------------------------------------------------------------------
# Server
# -----------------------------------------------------------------------------
server <- function(input, output, session) {

  # Signed in already? A still-valid session cookie from an earlier visit.
  who     <- reactiveVal(verify_ticket(read_cookie(session$request$HTTP_COOKIE, "sb_session"), "session"))
  authed  <- reactive(!is.null(who()))
  flash   <- reactiveVal(NULL)
  tick    <- reactiveVal(0)          # bumped after a manual refresh or connect

  observeEvent(session$clientData$url_search, once = TRUE, {
    qs <- parseQueryString(session$clientData$url_search)

    # --- Arriving from the Office App's Snowbirds card (?sso=...) -------------
    if (!is.null(qs$sso)) {
      session$sendCustomMessage("cleanUrl", TRUE)
      w <- verify_ticket(qs$sso, "sso")
      if (is.null(w)) {
        flash(list(type = "warning", text = "That sign-in link has expired. Open Snowbirds from the Office App again."))
        return()
      }
      expires <- Sys.time() + SESSION_HOURS * 3600
      session$sendCustomMessage("setSession", list(value = sign_ticket("session", w$user, w$role, expires),
                                                   maxAge = SESSION_HOURS * 3600))
      who(w)
      return()
    }

    # --- Jobber redirect lands here (?code=...&state=...) ---------------------
    # The state value was created by a signed-in user when they clicked
    # Connect, so a match is the proof this sign-in is ours.
    if (is.null(qs$code) && is.null(qs$error)) return()
    session$sendCustomMessage("cleanUrl", TRUE)
    if (!is.null(qs$error)) {
      flash(list(type = "warning", text = paste("Jobber did not connect:", qs$error)))
      return()
    }
    res <- tryCatch(paste0("Connected to Jobber account “", jobber_auth_finish(qs$code, qs$state), "”."),
                    error = function(e) paste("Jobber did not connect:", conditionMessage(e)))
    flash(list(type = if (startsWith(res, "Connected")) "success" else "warning", text = res))
    tick(tick() + 1)
  })

  observeEvent(input$signout, {
    session$sendCustomMessage("clearSession", paste0(OFFICE_URL, "/dashboard"))
  })

  observeEvent(input$connect, {
    req(authed())
    url <- tryCatch(jobber_auth_start(), error = function(e) { flash(list(type = "danger", text = conditionMessage(e))); NULL })
    if (!is.null(url)) session$sendCustomMessage("go", url)
  })

  # Starts a background refresh and returns at once - the page never waits on it.
  observeEvent(input$refresh, {
    req(authed())
    started <- start_refresh("quotes", trigger = paste("Refresh now by", who()$user))
    flash(if (started)
            list(type = "info", text = "Updating quotes in the background. The page updates itself when it finishes, usually within a few minutes.")
          else if (refresh_running())
            list(type = "info", text = "An update is already running. The page updates itself when it finishes.")
          else list(type = "warning", text = "Jobber is not connected yet."))
  })

  observeEvent(input$refresh_all, {
    req(authed())
    started <- start_refresh("all", trigger = paste("Full refresh by", who()$user))
    flash(if (started)
            list(type = "info", text = paste("Pulling quotes, clients and job history in the background.",
                                             "This takes longer than a quote refresh - usually 10 to 20 minutes.",
                                             "The page updates itself when it finishes."))
          else if (refresh_running())
            list(type = "info", text = "An update is already running. The page updates itself when it finishes.")
          else list(type = "warning", text = "Jobber is not connected yet."))
  })

  # Data files: the tables and tiles re-render only when these change, so an
  # update in progress does not reset the table someone is scrolling.
  files_state <- reactivePoll(10000, session,
    checkFunc = function() paste(file.mtime(c(PLAN_CSV, DB_CSV, TOKEN_FILE)), collapse = "|"),
    valueFunc = function() Sys.time())

  # Refresh status: its own small output, polled more often.
  status_state <- reactivePoll(5000, session,
    checkFunc = function() paste(file.mtime(STATUS_FILE), file.exists(LOCK_FILE), format(Sys.time(), "%H:%M")),
    valueFunc = function() list(s = read_status(), running = refresh_running()))

  output$status_ui <- renderUI({
    req(authed())
    st <- status_state(); s <- st$s
    ago <- function(txt) {
      m <- minutes_since(txt)
      if (is.infinite(m)) "never" else if (m < 1) "just now" else if (m < 60) sprintf("%d min ago", floor(m))
      else if (m < 1440) sprintf("%d h ago", floor(m / 60)) else sprintf("%d days ago", floor(m / 1440))
    }
    span(class = "top-sub",
      if (st$running) tags$span(style = "color:#0071E3; font-weight:600;", "⟳ Updating now… ")
      else if (identical(s$state, "failed")) tags$span(style = "color:#C0392B; font-weight:600;",
                                                      "Last update failed: ", s$message %||% "", " · "),
      "Quotes updated ", ago(s$last_quotes),
      " · clients and job history ", ago(s$last_all),
      sprintf(" · quotes refresh automatically every %d min, 6am–9pm", QUOTES_EVERY))
  })

  plan <- reactive({ req(authed()); files_state(); tick()
    if (file.exists(PLAN_CSV)) read_csv(PLAN_CSV, col_types = cols(.default = col_character())) else NULL })
  db <- reactive({ req(authed()); files_state(); tick()
    if (file.exists(DB_CSV)) read_csv(DB_CSV, col_types = cols(.default = col_character())) else NULL })
  excluded <- reactive({ req(authed()); files_state(); tick()
    if (file.exists(EXCL_CSV)) read_csv(EXCL_CSV, col_types = cols(.default = col_character())) else NULL })

  flash_ui <- function() {
    f <- flash(); if (is.null(f)) return(NULL)
    div(class = paste0("alert alert-", f$type, " py-2"), f$text)
  }

  tile <- function(label, num, sub = NULL)
    div(class = "tile", div(class = "tile-label", label), div(class = "tile-num", num),
        if (!is.null(sub)) div(class = "tile-sub", sub))

  output$page <- renderUI({
    if (!authed()) {
      return(div(class = "login",
        div(class = "tile",
          div(class = "top-title mb-1", "Snowbirds"),
          div(class = "top-sub mb-3", "Part of the Office App. Admin and office users only."),
          flash_ui(),
          if (!nzchar(SSO_SECRET)) div(class = "alert alert-warning py-2",
            "SNOWBIRDS_SSO_SECRET is not set on this service, so sign-in from the Office App cannot work yet."),
          tags$a(class = "btn btn-primary w-100", href = paste0(OFFICE_URL, "/snowbirds"), "Open from the Office App")
        )))
    }

    files_state(); tick()
    acct      <- if (file.exists(file.path(JOBBER_DIR, "account.rds"))) readRDS(file.path(JOBBER_DIR, "account.rds")) else NULL
    connected <- file.exists(TOKEN_FILE)
    has_creds <- nzchar(Sys.getenv("JOBBER_CLIENT_ID")) && nzchar(Sys.getenv("JOBBER_CLIENT_SECRET"))
    p <- plan(); d <- db()
    today <- as.Date(format(Sys.time(), tz = TZ))
    due   <- if (!is.null(p)) sum(as.Date(p$resend_on) <= today, na.rm = TRUE) else 0
    week  <- if (!is.null(p)) sum(as.Date(p$resend_on) > today & as.Date(p$resend_on) <= today + 7, na.rm = TRUE) else 0
    value <- if (!is.null(p)) sum(as.numeric(p$total), na.rm = TRUE) else 0
    birds <- if (!is.null(d)) sum(d$snowbird == "TRUE", na.rm = TRUE) else 0

    div(class = "wrap",
      div(class = "d-flex justify-content-between align-items-end flex-wrap gap-2 mb-3",
        div(div(class = "top-title", "Snowbird Clients"),
            div(class = "top-sub", if (connected) paste("Jobber:", acct$name %||% "connected") else "Jobber not connected"),
            uiOutput("status_ui")),
        div(class = "d-flex gap-2",
          actionButton("connect", if (connected) "Reconnect Jobber" else "Connect Jobber",
                       class = if (connected) "btn-outline-secondary btn-sm" else "btn-primary btn-sm",
                       disabled = !has_creds),
          actionButton("refresh", "Refresh now", class = "btn-outline-primary btn-sm",
                       disabled = !connected),
          # "Refresh now" pulls quotes only, which is all the daily plan needs.
          # Client records - names, billing addresses and Jobber's isCompany
          # flag - are only re-pulled by a full refresh, so the business and
          # HOA rules run on whatever clients.csv last captured until this is
          # used. Slower, hence separate.
          actionButton("refresh_all", "Full refresh (clients too)",
                       class = "btn-outline-secondary btn-sm", disabled = !connected),
          tags$a(class = "btn btn-outline-secondary btn-sm", href = paste0(OFFICE_URL, "/dashboard"), "← Office App"),
          actionButton("signout", paste("Sign out", who()$user), class = "btn-link btn-sm text-secondary"))),

      flash_ui(),
      if (!has_creds) div(class = "alert alert-warning py-2",
        "JOBBER_CLIENT_ID and JOBBER_CLIENT_SECRET are not set on this Railway service yet."),
      if (has_creds && !connected) div(class = "alert alert-info py-2",
        "Click Connect Jobber. A Jobber admin approves access on Jobber's page, then comes back here."),

      uiOutput("switch_ui"),

      layout_columns(col_widths = c(3, 3, 3, 3), class = "mb-3",
        tile("Resend now", due, "due today or overdue"),
        tile("Resend this week", week, "in the next 7 days"),
        tile("Snowbird quotes outstanding", if (!is.null(p)) nrow(p) else 0,
             paste(scales::dollar(value), "before discount")),
        tile("Clients with a home up north", birds,
             if (!is.null(d)) paste("of", nrow(d), "clients") else NULL)),

      navset_card_tab(
        nav_panel("Resend plan",
          div(class = "note mb-2",
              "Each outstanding quote from a client with a home up north, in the order to resend it with 10% off. ",
              "The date is 14 days before they are due back, or today if they are already here. ",
              "Only 'awaiting response' quotes can be sent automatically; 'changes requested' ones are for a person to handle."),
          DTOutput("plan_tbl"),
          downloadButton("dl_plan", "Download CSV", class = "btn-sm btn-outline-secondary mt-2")),
        nav_panel("Auto-send",
          div(class = "note mb-2",
              "Due today: awaiting-response quotes whose resend date has arrived and that have never been sent. ",
              "At 7:00 am these go out with 10% off, up to ", DAILY_CAP, " a day, but only while the switch above is ON."),
          DTOutput("due_tbl"),
          h6(class = "mt-4", "Send history"),
          DTOutput("sent_tbl")),
        nav_panel("All clients",
          div(class = "note mb-2",
              "Every Jobber client and the evidence behind their status. ",
              "Confirmed = the county property roll and their billing address agree. ",
              "Likely = one of the two. Year-round = homestead exemption."),
          DTOutput("db_tbl"),
          downloadButton("dl_db", "Download CSV", class = "btn-sm btn-outline-secondary mt-2")),
        nav_panel("Held back",
          div(class = "note mb-2",
              "Snowbird quotes deliberately kept out of the plan, and why. ",
              "Businesses, HOAs and landscaping or trade companies never get this offer. ",
              "Nor does a quote outside the eligible window: it has to be between ",
              MIN_QUOTE_AGE_MONTHS, " and ", MAX_QUOTE_AGE_MONTHS, " months old and under ",
              scales::dollar(MAX_QUOTE_VALUE), ". Too new and the client is still ",
              "considering the original; too old and the price wants re-quoting rather ",
              "than discounting; too large and it deserves a conversation, not an email. ",
              "If something is here that should not be, or a client slipped through that ",
              "should never be approached, add them to do_not_send.csv beside the Jobber ",
              "data - a single column of client names or ids, no redeploy needed."),
          DTOutput("excl_tbl"),
          downloadButton("dl_excl", "Download CSV", class = "btn-sm btn-outline-secondary mt-2")),
        nav_panel("Jobber API",
          div(class = "note mb-2",
              "What this app is actually allowed to do in Jobber, asked of the API itself ",
              "rather than assumed. Sending a discounted quote from here needs two things: a ",
              "mutation that can apply a discount and send, and a connected account that ",
              "granted write access. Both are below. Nothing here contains client data - only ",
              "the names of API operations and permissions."),
          actionButton("probe_now", "Re-run the check", class = "btn-outline-primary btn-sm mb-3"),
          uiOutput("probe_ui")),
        nav_panel("How it works",
          div(style = "max-width:76ch; line-height:1.6;",
            h5("Who counts as a snowbird"),
            p("Each property on a quote or job is matched to the Collier County property roll. No homestead exemption ",
              "and tax mail going out of state means a second home. Their Jobber billing address is the second check. ",
              "Lee County properties are judged on the billing address until Lee's roll is added."),
            h5("When they are back"),
            p("With two or more past seasons on file, their own habit: the date of their first quote or job each autumn. ",
              "With one season, the earlier of that and the area forecast. With none, the forecast's season opening."),
            h5("Updates"),
            p("Everything updates on its own, in the background, so the page stays usable. ",
              sprintf("Quotes are pulled and the plan rebuilt every %d minutes from 6am to 9pm Eastern. ", QUOTES_EVERY),
              "Clients and job history are reloaded in full overnight. At 7am the quotes update runs first, then any ",
              "automatic resends. Refresh now starts a quotes update immediately. ",
              "The county property roll is re-downloaded monthly."))))
    )
  })

  # --- Kill switch --------------------------------------------------------------
  # Its own output, so flipping it does not rebuild the whole page. Turning ON
  # asks for confirmation; turning OFF is one click and immediate, because the
  # sender re-reads the switch before every single quote.
  sw_tick <- reactiveVal(0)

  output$switch_ui <- renderUI({
    req(authed()); sw_tick(); files_state()
    s     <- switch_state()
    n_due <- nrow(due_for_auto_send(PLAN_CSV))
    when  <- if (is.na(s$changed_at)) "never changed" else
               paste("changed", format(s$changed_at, "%d %b %Y %I:%M %p", tz = TZ))
    div(class = "tile mb-3", style = paste0("border-left:6px solid ", if (s$on) "#34C759" else "#8E8E93", ";"),
      div(class = "d-flex justify-content-between align-items-center flex-wrap gap-2",
        div(
          div(class = "tile-label", "Automatic discounted resends"),
          div(class = "tile-num", style = paste0("color:", if (s$on) "#1E8E3E" else "#6E6E73"), if (s$on) "ON" else "OFF"),
          div(class = "tile-sub",
              if (s$on) sprintf("At 7:00 am, up to %d due quotes get 10%% off and are sent. %d due now.", DAILY_CAP, n_due)
              else sprintf("Nothing is sent automatically. %d quote%s would be due now.", n_due, if (n_due == 1) "" else "s"),
              " (", when, ")"),
          if (!SEND_READY) div(class = "tile-sub", style = "color:#E08600;",
              "Sending is not built yet: it waits on the Jobber API check. Even when ON, nothing is sent until then.")),
        if (s$on) actionButton("switch_off", "Turn OFF", class = "btn-danger")
        else      actionButton("switch_on",  "Turn ON",  class = "btn-outline-success")))
  })

  observeEvent(input$switch_off, {
    req(authed())
    set_switch(FALSE, who()$user)
    sw_tick(sw_tick() + 1)
    flash(list(type = "success", text = "Automatic resends are OFF. Nothing will be sent."))
  })

  observeEvent(input$switch_on, {
    req(authed())
    n_due <- nrow(due_for_auto_send(PLAN_CSV))
    showModal(modalDialog(
      title = "Turn on automatic resends?",
      p(sprintf("Every morning at 7:00 am, up to %d awaiting-response quotes to snowbird clients whose resend date has arrived will get 10%% off and be sent from Jobber, with nobody reviewing them first.", DAILY_CAP)),
      p(sprintf("%d quote%s would qualify right now. Check the Auto-send tab first.", n_due, if (n_due == 1) "" else "s")),
      p("You can turn it off at any time. It stops before the next quote."),
      footer = tagList(modalButton("Cancel"), actionButton("switch_on_confirm", "Turn ON", class = "btn-success"))))
  })

  observeEvent(input$switch_on_confirm, {
    req(authed())
    removeModal()
    set_switch(TRUE, who()$user)
    sw_tick(sw_tick() + 1)
    flash(list(type = "warning", text = "Automatic resends are ON."))
  })

  output$due_tbl <- renderDT({
    req(authed()); sw_tick(); files_state()
    d <- due_for_auto_send(PLAN_CSV)
    shiny::validate(shiny::need(nrow(d) > 0, "Nothing is due to be sent."))
    datatable(d %>% transmute(`Resend on` = resend_on, Client = client, `Quote #` = quote_number,
                              Quote = quote_title, Total = scales::dollar(as.numeric(total)),
                              `With 10% off` = scales::dollar(as.numeric(total_10pct_off)), Status = snowbird_status),
              rownames = FALSE, options = list(pageLength = 25, scrollX = TRUE))
  })

  output$sent_tbl <- renderDT({
    req(authed()); sw_tick(); files_state()
    s <- sent_log()
    shiny::validate(shiny::need(nrow(s) > 0, "Nothing has been sent yet."))
    datatable(s %>% arrange(desc(attempted_at)), rownames = FALSE, options = list(pageLength = 25, scrollX = TRUE))
  })

  link_col <- function(u) ifelse(!is.na(u) & grepl("^https://", u),
                                 sprintf('<a href="%s" target="_blank" rel="noopener">Open</a>', htmltools::htmlEscape(u, attribute = TRUE)), "")

  # "2026-11-17" is hard to read at a glance and sorts no better than "17 Nov
  # 2026" once DT is told the column is a date, so show the readable form.
  d_fmt <- function(x) {
    d <- suppressWarnings(as.Date(x))
    ifelse(is.na(d), "", format(d, "%d %b %Y"))
  }
  # "Second home - likely (billing address only)" in a narrow column just
  # renders as "Second". The prefix is the same on every row anyway.
  short_status <- function(x) {
    x <- x %||% ""
    case_when(
      grepl("confirmed",  x, ignore.case = TRUE) ~ "Confirmed",
      grepl("billing",    x, ignore.case = TRUE) ~ "Likely (billing)",
      grepl("roll only",  x, ignore.case = TRUE) ~ "Likely (roll)",
      grepl("Year-round", x, ignore.case = TRUE) ~ "Year-round",
      grepl("^Check",     x)                     ~ "Check",
      TRUE ~ x)
  }

  output$plan_tbl <- renderDT({
    p <- plan()
    shiny::validate(shiny::need(!is.null(p), "No plan yet. Connect Jobber, then click Refresh now."))
    t <- p %>% transmute(
      `Resend on` = d_fmt(resend_on),
      Client      = client,
      `Quote #`   = quote_number,
      Quote       = quote_title,
      Quoted      = if ("quote_created" %in% names(p)) d_fmt(quote_created) else "",
      Total       = scales::dollar(as.numeric(total)),
      `With 10% off` = scales::dollar(as.numeric(total_10pct_off)),
      Home        = northern_home,
      `Due back`  = d_fmt(predicted_return),
      Status      = short_status(snowbird_status),
      Sending     = if ("auto_send" %in% names(p)) if_else(auto_send == "yes", "Automatic", "By hand") else "",
      `Why this date` = why_this_date,
      Jobber      = link_col(jobber_link))

    datatable(
      t, rownames = FALSE, escape = setdiff(seq_along(t), ncol(t)),
      options = list(
        pageLength = 25, order = list(list(0, "asc")), scrollX = TRUE,
        autoWidth = FALSE,
        # Widths and wrapping, because 13 columns sharing the page evenly left
        # every one of them too narrow to read - dates broke mid-year and quote
        # titles were cut mid-word.
        columnDefs = list(
          list(targets = c(0, 4, 8), className = "dt-nowrap"),
          list(targets = c(5, 6),    className = "dt-money"),
          list(targets = 2,          className = "dt-nowrap"),
          list(targets = 9,  width = "120px"),
          list(targets = 10, width = "95px"),
          list(targets = 1,  width = "150px"),
          list(targets = 3,  width = "250px"),
          list(targets = 11, width = "330px"))))
  })

  output$db_tbl <- renderDT({
    d <- db()
    shiny::validate(shiny::need(!is.null(d), "No client list yet. Connect Jobber, then click Refresh now."))
    t <- d %>% transmute(Client = client, Status = short_status(status),
                         Home = coalesce(home_state, home_country),
                         Region = home_region, `Due back` = d_fmt(predicted_return),
                         Evidence = evidence,
                         Property = property_address, Jobber = link_col(client_link))
    datatable(t, rownames = FALSE, escape = setdiff(seq_along(t), ncol(t)),
              options = list(pageLength = 25, scrollX = TRUE))
  })

  probe <- reactive({
    req(authed()); tick()
    if (!file.exists(PROBE_JSON)) return(NULL)
    tryCatch(jsonlite::fromJSON(PROBE_JSON, simplifyVector = FALSE),
             error = function(e) NULL)
  })

  observeEvent(input$probe_now, {
    req(authed())
    if (!file.exists(TOKEN_FILE)) {
      flash(list(type = "warning", text = "Jobber is not connected yet."))
      return(invisible())
    }
    # Read-only and short: one introspection query plus one per input type it
    # finds. Run inline rather than as a background job so the answer is on
    # screen immediately.
    withProgress(message = "Asking Jobber what this app can do...", value = 0.5, {
      res <- tryCatch({ jobber_probe_schema(); "ok" },
                      error = function(e) conditionMessage(e))
    })
    flash(if (identical(res, "ok"))
            list(type = "success", text = "Done - the results are below.")
          else list(type = "warning", text = paste("The check failed:", res)))
    tick(tick() + 1)
  })

  output$probe_ui <- renderUI({
    p <- probe()
    if (is.null(p))
      return(div(class = "alert alert-secondary py-2 mb-0",
                 "No check has run yet. Connect Jobber, then press ",
                 strong("Re-run the check"), "."))

    # The file used to be a bare list of mutations; keep reading those too.
    muts   <- if (!is.null(p$mutations)) p$mutations else p
    scopes <- unlist(p$scopes %||% list())
    when   <- p$probed_at %||% format(file.mtime(PROBE_JSON), "%Y-%m-%d %H:%M")

    sendable <- Filter(function(m) grepl("send", m$mutation %||% "", ignore.case = TRUE), muts)
    discount <- Filter(function(m) grepl("discount", m$mutation %||% "", ignore.case = TRUE), muts)

    verdict <- function(label, hits, note) {
      ok <- length(hits) > 0
      div(class = paste("py-2 px-3 mb-2 rounded", if (ok) "bg-success-subtle" else "bg-warning-subtle"),
          strong(label), " ",
          if (ok) paste0("yes - ", paste(vapply(hits, function(m) m$mutation, ""), collapse = ", "))
          else "nothing matching was found",
          div(class = "small text-muted", note))
    }

    tagList(
      div(class = "small text-muted mb-2",
          sprintf("Checked %s · %s quote/send-related operations out of %s in the schema",
                  when, length(muts), p$total_mutations %||% "?")),

      verdict("Can a quote be sent from the API?", sendable,
              "Needed for a send to appear in the client's Jobber communication history."),
      verdict("Can a discount be applied?", discount,
              "Without this, the 10% has to be applied by hand before sending."),

      div(class = "py-2 px-3 mb-3 rounded bg-light",
          strong("Permissions granted by the connected account: "),
          if (length(scopes) == 0)
            span(class = "text-muted",
                 "not recorded yet - press Re-run the check (earlier checks did not save them)")
          else code(paste(scopes, collapse = "  "))),

      h6("Every quote, send and discount operation this API version exposes"),
      if (length(muts) == 0)
        div(class = "text-muted small", "None found.")
      else
        tags$ul(class = "small", lapply(muts, function(m) {
          tags$li(
            code(m$mutation %||% "?"),
            if (length(m$args))
              tags$ul(lapply(m$args, function(a) {
                tags$li(code(a$arg %||% "?"), " (", a$type %||% "?", ")",
                        if (length(a$fields))
                          div(class = "text-muted",
                              paste(unlist(a$fields), collapse = ", ")))
              }))
          )
        }))
    )
  })

  output$excl_tbl <- renderDT({
    e <- excluded()
    shiny::validate(shiny::need(!is.null(e), "Nothing held back yet - run Refresh now."))
    shiny::validate(shiny::need(nrow(e) > 0, "Nothing is being held back."))
    t <- e %>% transmute(Client = client, `Quote #` = quote_number, Quote = quote_title,
                         Quoted = d_fmt(quote_created),
                         `Age (days)` = as.integer(as.numeric(quote_age_days)),
                         Total = scales::dollar(as.numeric(total)),
                         Reason = excluded_because, Jobber = link_col(jobber_link))
    datatable(
      t, rownames = FALSE, escape = setdiff(seq_along(t), ncol(t)),
      options = list(
        pageLength = 25, order = list(list(4, "desc")), scrollX = TRUE, autoWidth = FALSE,
        columnDefs = list(
          list(targets = c(1, 3, 4), className = "dt-nowrap"),
          list(targets = 5,          className = "dt-money"),
          list(targets = 0, width = "170px"),
          list(targets = 2, width = "260px"),
          list(targets = 6, width = "330px"))))
  })

  output$dl_excl <- downloadHandler(
    filename = function() paste0("excluded_from_plan_", Sys.Date(), ".csv"),
    content  = function(f) { req(authed()); file.copy(EXCL_CSV, f) })

  output$dl_plan <- downloadHandler(
    filename = function() paste0("quote_resend_plan_", Sys.Date(), ".csv"),
    content  = function(f) { req(authed()); file.copy(PLAN_CSV, f) })
  output$dl_db <- downloadHandler(
    filename = function() paste0("client_second_homes_", Sys.Date(), ".csv"),
    content  = function(f) { req(authed()); file.copy(DB_CSV, f) })
}

shinyApp(ui, server)
