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
# The refresh, and the 7am schedule
# -----------------------------------------------------------------------------
busy <- new.env(); busy$on <- FALSE

# allow_send is TRUE only for the scheduled 7am run. "Refresh now" rebuilds
# the plan but never sends anything.
run_refresh <- function(trigger, allow_send = FALSE) {
  if (busy$on) return("A refresh is already running.")
  if (!file.exists(TOKEN_FILE)) {
    log_line(trigger, ": skipped, Jobber is not connected")
    return("Jobber is not connected yet.")
  }
  busy$on <- TRUE
  on.exit(busy$on <- FALSE)
  res <- tryCatch(in_root({
    ensure_collier_roll(Sys.getenv("COLLIER_ROLL", "data/raw/collier_int_parcels.csv"))
    source("R/17_jobber_pull.R",         local = new.env())
    source("R/18_client_second_homes.R", local = new.env())
    # One-off: find out what this Jobber API allows before automating sends.
    if (!file.exists(file.path(JOBBER_DIR, "schema_probe.json"))) try(jobber_probe_schema())
    "done"
  }), error = function(e) paste("failed:", conditionMessage(e)))
  log_line(trigger, ": ", res)
  if (allow_send && res == "done")
    tryCatch(run_auto_send(PLAN_CSV), error = function(e) log_line("auto-send failed: ", conditionMessage(e)))
  res
}

secs_to_next_7am <- function() {
  now <- Sys.time()
  nxt <- as.POSIXct(paste(format(now, "%Y-%m-%d", tz = TZ), "07:00:00"), tz = TZ)
  if (nxt <= now) nxt <- as.POSIXct(paste(format(now + 86400, "%Y-%m-%d", tz = TZ), "07:00:00"), tz = TZ)
  as.numeric(difftime(nxt, now, units = "secs"))
}
schedule_daily <- function() {
  later(function() { run_refresh("7am scheduled refresh", allow_send = TRUE); schedule_daily() }, secs_to_next_7am())
}
# Off switch for automated tests, which otherwise wait on the queued 7am job.
if (Sys.getenv("CLIENTS_NO_SCHEDULE") != "true") schedule_daily()

# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
CSS <- "
body { background:#E6E6EB; }
.wrap { max-width:1400px; margin:0 auto; padding:20px 16px 40px; }
.top-title { font-size:1.4rem; font-weight:700; letter-spacing:-.02em; color:#1D1D1F; }
.top-sub { font-size:.83rem; color:#6E6E73; }
.tile { background:#fff; border-radius:14px; padding:14px 16px; box-shadow:0 0 0 1px rgba(0,0,0,.045),0 1px 3px rgba(0,0,0,.055); height:100%; }
.tile-label { font-size:.78rem; color:#6E6E73; font-weight:500; }
.tile-num { font-size:1.6rem; font-weight:700; letter-spacing:-.03em; color:#1D1D1F; line-height:1.15; }
.tile-sub { font-size:.76rem; color:#8E8E93; margin-top:2px; }
.login { max-width:380px; margin:12vh auto; }
.note { font-size:.8rem; color:#6E6E73; }
table.dataTable { font-size:.84rem; }
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

  observeEvent(input$refresh, {
    req(authed())
    msg <- withProgress(message = "Pulling quotes from Jobber and rebuilding the plan...", value = .3,
                        run_refresh("manual refresh"))
    flash(list(type = if (msg == "done") "success" else "warning",
               text = if (msg == "done") "Refreshed." else msg))
    tick(tick() + 1)
  })

  # Files change on the 7am run too, not only on clicks - so watch them.
  files_state <- reactivePoll(10000, session,
    checkFunc = function() paste(file.mtime(c(PLAN_CSV, DB_CSV, TOKEN_FILE, LOG_FILE)), collapse = "|"),
    valueFunc = function() Sys.time())

  plan <- reactive({ req(authed()); files_state(); tick()
    if (file.exists(PLAN_CSV)) read_csv(PLAN_CSV, col_types = cols(.default = col_character())) else NULL })
  db <- reactive({ req(authed()); files_state(); tick()
    if (file.exists(DB_CSV)) read_csv(DB_CSV, col_types = cols(.default = col_character())) else NULL })

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
    last_log  <- if (file.exists(LOG_FILE)) tail(readLines(LOG_FILE, warn = FALSE), 1) else "No refresh yet"
    p <- plan(); d <- db()
    today <- as.Date(format(Sys.time(), tz = TZ))
    due   <- if (!is.null(p)) sum(as.Date(p$resend_on) <= today, na.rm = TRUE) else 0
    week  <- if (!is.null(p)) sum(as.Date(p$resend_on) > today & as.Date(p$resend_on) <= today + 7, na.rm = TRUE) else 0
    value <- if (!is.null(p)) sum(as.numeric(p$total), na.rm = TRUE) else 0
    birds <- if (!is.null(d)) sum(d$snowbird == "TRUE", na.rm = TRUE) else 0

    div(class = "wrap",
      div(class = "d-flex justify-content-between align-items-end flex-wrap gap-2 mb-3",
        div(div(class = "top-title", "Snowbird Clients"),
            div(class = "top-sub", if (connected) paste("Jobber:", acct$name %||% "connected") else "Jobber not connected",
                " · ", last_log)),
        div(class = "d-flex gap-2",
          actionButton("connect", if (connected) "Reconnect Jobber" else "Connect Jobber",
                       class = if (connected) "btn-outline-secondary btn-sm" else "btn-primary btn-sm",
                       disabled = !has_creds),
          actionButton("refresh", "Refresh now", class = "btn-outline-primary btn-sm",
                       disabled = !connected),
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
            p("Quotes are pulled and the plan rebuilt every day at 7:00 am Eastern, and whenever Refresh now is clicked. ",
              "The property roll is re-downloaded monthly."))))
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

  output$plan_tbl <- renderDT({
    p <- plan()
    shiny::validate(shiny::need(!is.null(p), "No plan yet. Connect Jobber, then click Refresh now."))
    t <- p %>% transmute(`Resend on` = resend_on, Client = client, `Home up north` = northern_home,
                         `Due back` = predicted_return, `Quote #` = quote_number, Quote = quote_title,
                         Total = scales::dollar(as.numeric(total)), `With 10% off` = scales::dollar(as.numeric(total_10pct_off)),
                         Status = snowbird_status,
                         `Auto-send` = if ("auto_send" %in% names(p)) auto_send else "",
                         `Why this date` = why_this_date, Jobber = link_col(jobber_link))
    datatable(t, rownames = FALSE, escape = setdiff(seq_along(t), ncol(t)),
              options = list(pageLength = 25, order = list(list(0, "asc")), scrollX = TRUE))
  })

  output$db_tbl <- renderDT({
    d <- db()
    shiny::validate(shiny::need(!is.null(d), "No client list yet. Connect Jobber, then click Refresh now."))
    t <- d %>% transmute(Client = client, Status = status, `Home up north` = coalesce(home_state, home_country),
                         Region = home_region, `Due back` = predicted_return, Evidence = evidence,
                         Property = property_address, Jobber = link_col(client_link))
    datatable(t, rownames = FALSE, escape = setdiff(seq_along(t), ncol(t)),
              options = list(pageLength = 25, scrollX = TRUE))
  })

  output$dl_plan <- downloadHandler(
    filename = function() paste0("quote_resend_plan_", Sys.Date(), ".csv"),
    content  = function(f) { req(authed()); file.copy(PLAN_CSV, f) })
  output$dl_db <- downloadHandler(
    filename = function() paste0("client_second_homes_", Sys.Date(), ".csv"),
    content  = function(f) { req(authed()); file.copy(DB_CSV, f) })
}

shinyApp(ui, server)
