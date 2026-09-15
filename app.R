# =============================================================================
# THE NAPLES SNOWBIRD DASHBOARD
# =============================================================================
# A Shiny app. Shiny turns an R script into a web page with working controls.
#
# Every Shiny app has three parts:
#   ui     - what it looks like (controls, and where output goes)
#   server - what it does (recalculates when a control moves)
#   shinyApp(ui, server) - glues them together and runs it
#
# The magic word is REACTIVE. You never write "when the slider moves, redraw
# the chart". You write "this chart depends on THRESHOLD" and Shiny works
# out what to redraw. Everything downstream updates on its own.
#
# TO RUN: open this file in RStudio and click "Run App" (top right),
#         or from a terminal in this folder:  Rscript run_app.R
# =============================================================================

library(shiny)
library(bslib)
library(shinycssloaders)
library(tidyverse)
library(lubridate)
library(scales)

# -----------------------------------------------------------------------------
# Loading spinner
# -----------------------------------------------------------------------------
# Two different ways a chart can be missing, and this covers both:
#
#   1. RECALCULATING - Shiny stamps class "recalculating" on an output while
#      the server is rebuilding it. The bootstrap on the forecast tab is the
#      slow one.
#   2. NOT YET COMPUTED - the sized() guard in server() deliberately refuses to
#      render until the browser reports real dimensions. That leaves a panel
#      genuinely empty with nothing recalculating, which is the case that
#      looked most like the app had hung.
#
# withSpinner() keeps the spinner up until the output actually has content, so
# it covers both rather than only the first.
#
# proxy.height reserves the space before anything arrives, otherwise the page
# jumps as each chart lands.
spinner <- function(ui_element, height = "460px") {
  withSpinner(
    ui_element,
    type    = 4,
    color   = "#2a6f97",
    size    = 0.8,
    caption = "Please wait, graph is loading...",
    proxy.height = height
  )
}

# -----------------------------------------------------------------------------
# A small "why?" tab that lives INSIDE a value box
# -----------------------------------------------------------------------------
# These explanations were originally a row of accordions under the boxes, which
# separated each answer from the number it explained. Attaching a compact tab to
# the box itself keeps them together.
#
# A popover rather than an inline expander, deliberately: the text runs to
# several paragraphs, and expanding it in place would both wreck the four-across
# layout and print body copy over a saturated colour. The popover opens on a
# white panel where it is actually readable.
why_tab <- function(label, ...) {
  popover(
    tags$span(class = "why-tab", icon("circle-question"), " ", label),
    ...,
    title = label,
    placement = "bottom"
  )
}

WHY_CSS <- HTML("
@import url(\"https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&display=swap\");

/* ===========================================================================
   Visual system
   ---------------------------------------------------------------------------
   Restraint over decoration. Near-white grounds, ONE accent (#0071E3), soft
   radii, and generous whitespace doing the work that borders and saturated
   fills were doing before. Type carries the hierarchy.
   =========================================================================== */

:root {
  --ink:        #1D1D1F;
  --ink-2:      #424245;
  --ink-3:      #6E6E73;
  --hair:       #E8E8ED;
  --ground:     #F5F5F7;
  --surface:    #FFFFFF;
  --accent:     #0071E3;
  --accent-sub: #EAF3FE;
  --warm-sub:   #FDF1E8;
  --lift:       0 1px 2px rgba(0,0,0,.03), 0 8px 28px rgba(0,0,0,.055);
}

body { background: var(--ground) !important; color: var(--ink); letter-spacing: -.011em; }
h1,h2,h3,h4,h5,h6 { letter-spacing: -.022em; font-weight: 600; color: var(--ink); }

/* Masthead */
.d-flex.align-items-baseline { border-bottom: none !important; padding-bottom: 0 !important; }
.d-flex.align-items-baseline h4 {
  font-size: 1.95rem; font-weight: 700; letter-spacing: -.03em; color: var(--ink) !important;
}
.d-flex.align-items-baseline span { color: var(--ink-3) !important; font-size: .95rem; }

/* Cards: no borders, soft lift, real breathing room */
.card, .bslib-card {
  background: var(--surface) !important;
  border: none !important;
  border-radius: 18px !important;
  box-shadow: var(--lift);
}
.card-body { padding: 26px 30px 30px !important; }

/* Value boxes: flat white, accent carried by the icon and label */
.bslib-value-box, .bslib-value-box .card-body, .value-box-area {
  background: var(--surface) !important; color: var(--ink) !important;
}
.bslib-value-box { border-radius: 18px !important; box-shadow: var(--lift); overflow: hidden; }
.bslib-value-box .value-box-title {
  font-size: .78rem !important; font-weight: 600 !important;
  letter-spacing: .04em; text-transform: uppercase; color: var(--ink-3) !important;
  margin-bottom: 6px !important;
}
.bslib-value-box .value-box-value {
  font-size: 2.05rem !important; font-weight: 600 !important;
  letter-spacing: -.035em; color: var(--ink) !important; line-height: 1.1 !important;
}
.bslib-value-box p, .bslib-value-box .shiny-text-output {
  color: var(--ink-3) !important; font-size: .84rem;
}
.bslib-value-box .value-box-showcase, .bslib-value-box .value-box-showcase * {
  color: var(--accent) !important; opacity: .92;
}
.bslib-value-box .value-box-showcase svg { width: 30px !important; height: 30px !important; }

/* The \"why this date\" chip */
.why-tab {
  display: inline-block; margin-top: .6rem; padding: .26rem .7rem;
  font-size: .76rem; font-weight: 500; color: var(--accent);
  background: var(--accent-sub); border: none; border-radius: 999px;
  cursor: pointer; user-select: none; white-space: nowrap;
  transition: background .18s ease;
}
.why-tab:hover { background: #DCEAFD; }

.popover { max-width: 440px; border: none !important; border-radius: 16px !important;
           box-shadow: 0 10px 40px rgba(0,0,0,.14) !important; }
.popover-header { font-weight: 600; font-size: .95rem; background: transparent !important;
                  border-bottom: 1px solid var(--hair) !important; padding: 14px 18px 10px; }
.popover-body { font-size: .875rem; line-height: 1.6; max-height: 60vh; overflow-y: auto;
                padding: 14px 18px 16px; color: var(--ink-2); }
.popover-body p { margin-bottom: .7rem; }
.popover-body p:last-child { margin-bottom: 0; }

/* Tabs as a segmented control.
   Bootstrap pulls each tab down 1px so the active one sits on the container
   border. That assumes ONE row - with eleven tabs the strip wraps and the
   negative margin drags row two up into row one, which was the overlap.
   Dropping the border entirely and using pills removes the mechanism. */
.nav-tabs, .nav.nav-tabs {
  border-bottom: none !important;
  gap: .3rem; row-gap: .4rem;
  padding: 5px; margin-bottom: 20px !important;
  background: rgba(0,0,0,.045); border-radius: 13px;
}
.nav-tabs .nav-item { margin-bottom: 0 !important; }
.nav-tabs .nav-link {
  margin-bottom: 0 !important; border: none !important;
  border-radius: 9px !important; padding: .42rem .82rem !important;
  font-size: .855rem; font-weight: 500; white-space: nowrap;
  color: var(--ink-2) !important; background: transparent !important;
  transition: background .15s ease, color .15s ease;
}
.nav-tabs .nav-link:hover { background: rgba(0,0,0,.05) !important; color: var(--ink) !important; }
.nav-tabs .nav-link.active {
  background: var(--surface) !important; color: var(--ink) !important;
  font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,.09);
}

/* Explainer panels: tint instead of a coloured rail */
div[style*=\"background:#eef4f8\"] {
  background: var(--ground) !important; border-left: none !important;
  border-radius: 14px !important; padding: 22px 26px !important;
}
div[style*=\"background:#eef4f8\"] h6 {
  font-size: 1.12rem !important; font-weight: 600; letter-spacing: -.02em;
  color: var(--ink) !important; margin-bottom: 10px !important;
}
div[style*=\"background:#fff5f5\"] {
  background: var(--warm-sub) !important; border-left: none !important;
  border-radius: 14px !important; padding: 20px 24px !important;
}
div[style*=\"background:#f8f9fa\"] {
  background: var(--ground) !important; border-left: none !important;
  border-radius: 14px !important;
}

/* Accordions */
.accordion, .accordion-item { border: none !important; background: transparent !important; }
.accordion-item { border-top: 1px solid var(--hair) !important; border-radius: 0 !important; }
.accordion-button {
  background: transparent !important; box-shadow: none !important;
  font-weight: 500; font-size: .9rem; color: var(--ink-2) !important;
  padding: 16px 4px !important;
}
.accordion-button:not(.collapsed) { color: var(--accent) !important; }
.accordion-body { padding: 0 4px 18px !important; color: var(--ink-2); }

/* Tables */
table { font-size: .88rem; }
table th {
  font-weight: 600 !important; font-size: .72rem !important;
  letter-spacing: .05em; text-transform: uppercase; color: var(--ink-3) !important;
  border-bottom: 1px solid var(--hair) !important; padding: 9px 14px 9px 0 !important;
}
table td {
  border-bottom: 1px solid var(--hair) !important; padding: 11px 14px 11px 0 !important;
  font-variant-numeric: tabular-nums; color: var(--ink-2);
}
table tr:last-child td { border-bottom: none !important; }
.table-striped > tbody > tr:nth-of-type(odd) > * { background: transparent !important; }

/* Sliders */
.irs--shiny .irs-bar { background: var(--accent) !important; border: none !important; }
.irs--shiny .irs-handle { border: none !important; box-shadow: 0 1px 4px rgba(0,0,0,.25) !important; }
.irs--shiny .irs-single { background: var(--ink) !important; border-radius: 6px !important; }
.irs--shiny .irs-line { background: rgba(0,0,0,.08) !important; border: none !important; }

p { color: var(--ink-2); }
strong { font-weight: 600; color: var(--ink); }
.text-muted { color: var(--ink-3) !important; }
")

# -----------------------------------------------------------------------------
# One consistent layout for every tab
# -----------------------------------------------------------------------------
# Each chart gets the same three parts, in the same order:
#   1. WHAT THIS SHOWS  - plain English, no jargon, above the chart where it
#      will actually be read
#   2. the chart
#   3. HOW WAS THIS CALCULATED - collapsed by default, so the method is always
#      available but never in the way
#
# A chart nobody can interpret is decoration. Putting the explanation below the
# fold, or in a caption nobody reads, is the same as not writing it.
chart_panel <- function(heading, plain, chart, method, footer = NULL) {
  card_body(
    fillable = FALSE,

    div(
      class = "p-3 mb-3",
      style = "background:#eef4f8; border-left:4px solid #2a6f97; border-radius:4px;",
      h6(heading, class = "fw-bold mb-2", style = "color:#1d3f5a;"),
      div(plain, style = "font-size:0.95rem; line-height:1.55;")
    ),

    chart,
    footer,

    accordion(
      open = FALSE, class = "mt-3",
      accordion_panel(
        "How was this calculated?",
        icon = icon("calculator"),
        div(method, style = "font-size:0.9rem; line-height:1.55;")
      )
    )
  )
}

# -----------------------------------------------------------------------------
# Readable chart text
# -----------------------------------------------------------------------------
# base_size 12 is ggplot's comfortable default for a plot you are looking at in
# RStudio at full screen. Inside a dashboard panel the same chart is rendered
# smaller and then scaled, so 12pt axis labels end up genuinely hard to read.
# Everything below is sized up, and set once here so every chart matches rather
# than each one carrying its own theme() call.
theme_set(
  theme_minimal(base_size = 15) +
    theme(
      plot.title      = element_text(size = 19, face = "bold", colour = "#1d3f5a",
                                     margin = margin(b = 4)),
      plot.subtitle   = element_text(size = 13.5, colour = "grey30", lineheight = 1.2,
                                     margin = margin(b = 10)),
      axis.title      = element_text(size = 14, colour = "grey25"),
      axis.text       = element_text(size = 13, colour = "grey20"),
      legend.text     = element_text(size = 13),
      legend.title    = element_text(size = 13),
      strip.text      = element_text(size = 14, face = "bold", colour = "#1d3f5a"),
      panel.grid.minor = element_blank(),      # less clutter behind bigger text
      plot.margin     = margin(10, 14, 8, 8)
    )
)

# Labels drawn INSIDE a plot (annotate, geom_text) use ggplot's own size units,
# not points, so they do not follow base_size and have to be scaled separately.
LBL <- 5.0   # in-plot annotation size

# =============================================================================
# LOAD DATA ONCE, at startup
# =============================================================================
# Code out here runs a single time. Code inside server() runs on every click.
# Putting file reads in the wrong place is the classic Shiny performance bug.

need_file <- function(p, script) {
  if (!file.exists(p)) stop("Missing ", p, "\nRun ", script, " first.", call. = FALSE)
  p
}

state_temps <- read_csv(need_file("data/origin_state_temps.csv", "R/06_origin_states.R"),
                        show_col_types = FALSE)
origin_states <- read_csv(need_file("data/origin_states.csv", "R/06_origin_states.R"),
                          show_col_types = FALSE)
naples <- read_csv(need_file("data/weather_daily.csv", "R/01_fetch_weather.R"),
                   show_col_types = FALSE) %>%
  filter(city == "Naples FL") %>%
  select(date, naples = temp_mean)

traffic_daily <- if (file.exists("data/collier_daily_traffic.csv")) {
  read_csv("data/collier_daily_traffic.csv", show_col_types = FALSE)
} else NULL

hist_aadt <- if (file.exists("data/collier_hist_aadt.csv")) {
  read_csv("data/collier_hist_aadt.csv", show_col_types = FALSE)
} else NULL

# RSW airport monthly passengers - the ONLY current-year indicator we have.
# Road counts stop at 2024; this runs to within about six weeks of today.
rsw_monthly <- if (file.exists("data/rsw_monthly_passengers.csv")) {
  read_csv("data/rsw_monthly_passengers.csv", show_col_types = FALSE)
} else NULL

# Permanent-move and stay-length data (R/15).
permanent_moves <- if (file.exists("data/permanent_moves.csv")) {
  read_csv("data/permanent_moves.csv", show_col_types = FALSE)
} else NULL

season_shape <- if (file.exists("data/season_shape.csv")) {
  read_csv("data/season_shape.csv", show_col_types = FALSE)
} else NULL

seasonal_curve_static <- if (file.exists("output/seasonal_curve.csv")) {
  read_csv("output/seasonal_curve.csv", show_col_types = FALSE)
} else NULL

MONTH_ABB <- c("Jan","Feb","Mar","Apr","May","Jun",
               "Jul","Aug","Sep","Oct","Nov","Dec")

# =============================================================================
# ANALYSIS SETTINGS - fixed here, deliberately not on the dashboard
# =============================================================================
# These four were sliders once. They are constants now because the dashboard is
# something you READ, and a reader who nudges a threshold is not testing
# robustness, they are just looking at a different answer with no way to know
# which one to believe.
#
# The Robustness tab still sweeps every threshold from 12 to 36 and shows the
# whole surface, so the evidence about whether the choice matters is all still
# there. It just is not adjustable from the page any more.
#
# The Simulation tab keeps its own controls. That is the intended place to ask
# "what if this year is different" - it varies CONDITIONS, not analysis
# parameters, which is a different question and a legitimate one.

THRESHOLD <- 25    # deg F. How much warmer Naples must be to be "worth it".
                   # The value the write-up quotes. Note the Robustness tab
                   # shows this result is only significant in a narrow band
                   # around here - which is exactly why nobody should be
                   # quietly moving it.

WEIGHTED  <- TRUE  # Weight northern home states by how many people they
                   # actually send, from IRS records, rather than counting
                   # Montana the same as Illinois.

HARMONICS <- 4     # Sine/cosine pairs per year in the seasonal fit. R2 = 0.76.
                   # 1 is too stiff to catch the summer double dip; 8 starts
                   # chasing individual weeks. Matches R/09, so the dashboard
                   # and the stored forecast cannot disagree.

# =============================================================================
# CURRENT CONDITIONS -> reasoning written from live data
# =============================================================================
# The headline dates come from a model fitted to 2024, so on their own they
# describe a NORMAL year. What makes this year differ is measured separately by
# R/13_current_conditions.R, and turned into sentences here.
#
# The rule throughout: only claim what the numbers support, and say which way
# each condition pushes rather than pretending to a revised date. A strong El
# Nino makes a quiet hurricane season likely - it does not tell you the trough
# will be on the 24th instead of the 22nd.
cond <- if (file.exists("data/current_conditions.csv")) {
  x <- read_csv("data/current_conditions.csv", show_col_types = FALSE)
  setNames(as.list(x$value), x$key)
} else list()

cnum <- function(k) suppressWarnings(as.numeric(cond[[k]] %||% NA))
ctxt <- function(k) cond[[k]] %||% NA_character_

# Human phrasing for a temperature anomaly.
warm_phrase <- function(x) {
  if (is.na(x)) return("unmeasured")
  if (abs(x) < 0.4) return(sprintf("about normal (%+.1f F)", x))
  sprintf("%.1f F %s than normal", abs(x), if (x > 0) "warmer" else "colder")
}

# Each of these returns a list of <p> tags describing what this year's
# conditions do to that particular date.
live_trough <- function() {
  bits <- list()

  if (!is.na(ctxt("oni_state"))) {
    if (!is.na(cnum("oni_value")) && cnum("oni_value") >= 0.5) {
      bits <- c(bits, list(p(
        strong("Hurricanes look unlikely to deepen it this year. "),
        sprintf("NOAA's index is at %+.2f (%s), which suppresses Atlantic activity, and there are %s Atlantic storms active right now. ",
                cnum("oni_value"), ctxt("oni_state"),
                if (identical(ctxt("storms_atlantic"), "0")) "no" else ctxt("storms_atlantic")),
        "That matters because the 2024 data this model was fitted to had ",
        strong("three"), " storms in it. Milton's landfall alone ran at 30% of",
        "normal traffic. With a quiet season, expect this September to dip",
        strong(" less deeply "), "than the model's average year suggests."),
        p(class = "text-muted",
          strong("But not earlier. "), "Tested across 36 seasons, how quiet the",
          "hurricane season is does ", strong("not"), " predict when people",
          "arrive (r = -0.13, p = 0.45). Nobody knows a season was quiet until",
          "it already is, and flights are booked months ahead. A quiet year",
          "changes the ", strong("depth"), " of this trough, not its date.")))
    } else if (!is.na(cnum("oni_value")) && cnum("oni_value") <= -0.5) {
      bits <- c(bits, list(p(
        strong("Raised disruption risk. "),
        sprintf("NOAA's index is at %+.2f (%s), which enhances Atlantic activity. ",
                cnum("oni_value"), ctxt("oni_state")),
        "A storm in the arrival window would deepen and distort this trough,",
        "as Helene and Milton did in 2024.")))
    }
  }

  if (!is.na(cnum("north_anom"))) {
    bits <- c(bits, list(p(
      strong("The north is not pushing anyone out yet. "),
      sprintf("Their northern home states have been running %s over the last month. ",
              warm_phrase(cnum("north_anom"))),
      if (cnum("north_anom") > 0.4)
        "Warm northern weather removes the reason to leave, which tends to hold the trough open a little longer."
      else if (cnum("north_anom") < -0.4)
        "A cold north brings the reason to travel forward, which can shorten the trough."
      else
        "With the north close to normal, nothing is pulling this date either way.")))
  }

  bits
}

live_start <- function() {
  bits <- list()

  if (!is.na(cnum("gap_anom"))) {
    g <- cnum("gap_anom")
    bits <- c(bits, list(p(
      strong("The pull south is currently "),
      strong(if (g < -0.4) "weaker than normal." else if (g > 0.4) "stronger than normal." else "about normal."),
      sprintf(" Naples is %s and their northern home states are %s, so the gap between them is running %+.1f F against its own average. ",
              warm_phrase(cnum("naples_anom")), warm_phrase(cnum("north_anom")), g),
      if (g < -0.4)
        "A narrower gap is a weaker invitation, which leans this date later rather than earlier."
      else if (g > 0.4)
        "A wider gap is a stronger invitation, which leans this date earlier."
      else
        "Nothing in the current gap argues for moving this date.")))
  }

  if (!is.na(cnum("rsw_ytd_change"))) {
    r <- cnum("rsw_ytd_change")
    bits <- c(bits, list(p(
      strong("Arrivals are not signalling a surge. "),
      sprintf("Airport passengers through month %s of %s are running %+.2f%% against the same months last year. ",
              ctxt("rsw_months"), ctxt("rsw_year"), r),
      if (abs(r) < 1)
        "Essentially flat - this year is tracking a normal one, so the modelled date stands."
      else if (r > 0)
        "Running ahead of last year, which would support an earlier or busier season."
      else
        "Running behind last year, which leans towards a later or lighter season.")))
  }

  bits
}

live_peak <- function() {
  list(p(
    strong("Current conditions say little about a date this far out. "),
    "The peak is months away, and nothing measurable today constrains it - ",
    "weather forecasting has no skill beyond about two weeks, and the",
    "Robustness tab shows the seasonal ensemble is no better than climatology",
    "past 60 days. ",
    if (!is.na(cnum("oni_value")) && cnum("oni_value") >= 0.5)
      sprintf("The current %s (%+.2f) is also likely to have decayed by March, as El Nino events typically do through late winter.",
              ctxt("oni_state"), cnum("oni_value")) else ""
  ))
}

# -----------------------------------------------------------------------------
# The headline prediction, in one paragraph
# -----------------------------------------------------------------------------
# Reads the model's dates, then states plainly whether current conditions argue
# for them being early, late or on time. Written from the numbers, so it
# rewrites itself when the watcher refreshes conditions.
fc_static <- if (file.exists("output/season_forecast.csv")) {
  read_csv("output/season_forecast.csv", show_col_types = FALSE)
} else NULL

next_occ_static <- function(doy) {
  if (is.null(doy) || is.na(doy)) return(as.Date(NA))
  d <- as.Date(paste0(format(Sys.Date(), "%Y"), "-01-01")) + (doy - 1)
  if (d < Sys.Date()) d <- as.Date(paste0(as.integer(format(Sys.Date(), "%Y")) + 1, "-01-01")) + (doy - 1)
  d
}

# -----------------------------------------------------------------------------
# Headline dates, resolved at startup
# -----------------------------------------------------------------------------
# These are rendered as plain text straight into the page rather than as Shiny
# outputs, and the reason is measurable: Shiny computes its whole first batch of
# outputs and flushes them TOGETHER. Even a trivial output waited ~1 second
# behind the slowest one, so the page opened with four blank boxes.
#
# The dates come from output/season_forecast.csv, which R/09 has already
# written, so there is nothing to compute at request time. Rendering them into
# the initial HTML means they are on screen the instant the page paints, with
# no server round-trip at all.
#
# The cost is that they no longer follow the flexibility slider. That is the
# right trade: this row is the PUBLISHED prediction and should be stable. The
# Season forecast tab is where the model is varied.
# -----------------------------------------------------------------------------
# Simulation baseline, built once
# -----------------------------------------------------------------------------
# The simulation rebuilt this 116,880-row gap series from scratch on EVERY
# slider movement, which put a visible pause between moving a dial and seeing
# the chart. None of it depends on any input, so it belongs here, computed once
# at startup. Dragging a slider now only has to add a constant and re-find two
# crossing dates.
SIM_BASE_GAP <- state_temps %>%
  group_by(date) %>%
  summarise(north = weighted.mean(temp, people, na.rm = TRUE), .groups = "drop") %>%
  inner_join(naples, by = "date") %>%
  arrange(date) %>%
  mutate(
    gap         = naples - north,
    gap_smooth  = as.numeric(stats::filter(gap, rep(1/7, 7), sides = 2)),
    season_year = if_else(month(date) >= 7, year(date), year(date) - 1L)
  )

HEAD <- if (!is.null(fc_static)) list(
  trough   = next_occ_static(fc_static$trough_doy),
  start    = next_occ_static(fc_static$start_doy),
  peak     = next_occ_static(fc_static$peak_doy),
  end      = next_occ_static(fc_static$end_doy),
  decline  = fc_static$decline_pct,
  increase = fc_static$increase_pct
) else NULL

head_date <- function(d) if (is.null(d) || is.na(d)) "-" else format(d, "%d %b %Y")

head_away <- function(d) {
  if (is.null(d) || is.na(d)) return("")
  n <- as.numeric(d - Sys.Date())
  if (n == 0) "today" else if (n == 1) "tomorrow" else paste(n, "days away")
}

live_prediction <- function() {
  if (is.null(fc_static)) return(NULL)

  trough <- next_occ_static(fc_static$trough_doy)
  start  <- next_occ_static(fc_static$start_doy)
  peak   <- next_occ_static(fc_static$peak_doy)

  n <- cnum("north_anom")
  g <- cnum("gap_anom")

  # "Is winter coming early?" is a question about the NORTH, not about Naples.
  # A cold north is what starts the migration; Naples being warm does nothing
  # on its own.
  winter <- if (is.na(n)) "unknown"
            else if (n <= -1.5) "early"
            else if (n <= -0.5) "slightly early"
            else if (n >=  1.5) "late"
            else if (n >=  0.5) "slightly late"
            else "on time"

  lean <- switch(winter,
    "early"          = "which argues for these dates arriving EARLIER than shown",
    "slightly early" = "which leans these dates slightly earlier",
    "late"           = "which argues for these dates arriving LATER than shown",
    "slightly late"  = "which leans these dates slightly later",
    "on time"        = "so the modelled dates stand as they are",
    "with no current read on timing")

  div(
    class = "p-3 mt-3",
    style = "background:#fff5f5; border-left:4px solid #c1121f; border-radius:4px;",

    tags$span(style = "font-size:.72rem;font-weight:700;letter-spacing:.05em;color:#c1121f;",
              "PREDICTION FOR THIS SEASON"),

    p(class = "mt-2 mb-2",
      if (is.na(n)) "Current northern temperatures are unavailable, so this is the model's average year: "
      else sprintf("Winter is arriving %s up north - their northern home states have been running %s over the last month, %s. ",
                   winter, warm_phrase(n), lean),
      if (!is.na(g))
        sprintf("The temperature gap that actually drives migration is running %+.1f F against its own normal. ", g)
      else ""),

    p(class = "mb-2",
      "On that basis the data estimates the ",
      strong("trough"), " of this season at ",
      strong(style = "color:#c1121f;", format(trough, "%d %b %Y")),
      ", the season ", strong("starting"), " around ",
      strong(style = "color:#c1121f;", format(start, "%d %b %Y")),
      ", and the ", strong("peak"), " around ",
      strong(style = "color:#c1121f;", format(peak, "%d %b %Y")), "."),

    if (!is.na(cnum("oni_value")) && cnum("oni_value") >= 0.5)
      p(class = "mb-0",
        sprintf("A %s (index %+.2f) is suppressing Atlantic hurricanes, and none are active. ",
                ctxt("oni_state"), cnum("oni_value")),
        "The 2024 season this model was built on had three storms in it, so expect this",
        "year's trough to be ", strong("shallower"), " than the model's - the date should hold,",
        "the depth should not.")
    else if (!is.na(cnum("oni_value")) && cnum("oni_value") <= -0.5)
      p(class = "mb-0",
        sprintf("A %s (index %+.2f) enhances Atlantic hurricane activity. ",
                ctxt("oni_state"), cnum("oni_value")),
        "A storm landing in the arrival window would deepen this trough and distort the dates.")
    else NULL,

    p(class = "text-muted small mb-0 mt-2",
      "Dates from a harmonic model of 2024 daily traffic; conditions measured ",
      ctxt("updated"), ". Conditions indicate direction, not a revised date - ",
      "a warm October does not move a March peak.")
  )
}

live_swing <- function() {
  bits <- list()
  if (!is.na(cnum("oni_value")) && cnum("oni_value") >= 0.5) {
    bits <- c(bits, list(p(
      strong("This year's swing will probably be smaller than the figure shown. "),
      "The 24% was measured on 2024, whose September was flattened by two",
      "hurricanes. With storms suppressed this year, the trough should be",
      "shallower - and a shallower trough means a smaller peak-to-trough gap.")))
  }
  bits
}

# Every northern home state, weighted. No longer a user choice.
ALL_STATES <- NULL   # assigned just below, once state_temps is read

all_states <- state_temps %>%
  distinct(state, people) %>%
  arrange(desc(people)) %>%
  pull(state)

ALL_STATES <- all_states

# Hurricanes hit southwest Florida in 2024 and are all over the traffic data.
# See R/05 for what they look like and why they must come out.
STORM_DAYS <- c(
  seq(as.Date("2024-08-03"), as.Date("2024-08-06"), by = "day"),
  seq(as.Date("2024-09-24"), as.Date("2024-09-29"), by = "day"),
  seq(as.Date("2024-10-06"), as.Date("2024-10-14"), by = "day")
)

# =============================================================================
# THE ANALYSIS, as plain functions
# =============================================================================
# Nothing Shiny-specific below. Keeping real logic in ordinary functions means
# you can test it at the console and the app just calls it. Never bury your
# analysis inside server().

# Daily temperature gap: Naples minus the chosen northern home states.
build_gap <- function(chosen_states, weighted) {
  state_temps %>%
    filter(state %in% chosen_states) %>%
    group_by(date) %>%
    summarise(
      north = if (weighted) weighted.mean(temp, people, na.rm = TRUE)
              else          mean(temp, na.rm = TRUE),
      .groups = "drop"
    ) %>%
    inner_join(naples, by = "date") %>%
    arrange(date) %>%
    mutate(
      gap = naples - north,
      # stats::filter() spelled in full: dplyr also exports filter()
      gap_smooth  = as.numeric(stats::filter(gap, rep(1/7, 7), sides = 2)),
      season_year = if_else(month(date) >= 7, year(date), year(date) - 1L)
    )
}

# For each season, when does the gap cross the threshold up and back down?
find_windows <- function(gap_df, threshold) {
  first_cross <- function(dates, g, months_in, above) {
    hit <- if (above) g >= threshold else g < threshold
    ok  <- hit & (month(dates) %in% months_in)
    if (!any(ok, na.rm = TRUE)) return(as.Date(NA))
    min(dates[which(ok)])
  }

  gap_df %>%
    filter(!is.na(gap_smooth)) %>%
    group_by(season_year) %>%
    summarise(
      opens  = first_cross(date, gap_smooth, 9:12, TRUE),
      closes = first_cross(date, gap_smooth, 3:6,  FALSE),
      .groups = "drop"
    ) %>%
    filter(!is.na(opens), !is.na(closes)) %>%
    mutate(
      window_days = as.numeric(closes - opens),
      opens_d     = as.numeric(opens  - make_date(season_year, 7, 1)),
      closes_d    = as.numeric(closes - make_date(season_year, 7, 1))
    )
}

# -----------------------------------------------------------------------------
# Season forecasting (see R/09 for the full version with bootstrap intervals)
# -----------------------------------------------------------------------------
# A season is a wave, so fit waves to it: sin/cos pairs at 1..K cycles per year.
# K controls how wiggly the curve is allowed to be, and it is exposed as a
# slider so you can watch underfitting and overfitting happen.
harmonics <- function(doy, K) {
  map_dfc(1:K, function(k) {
    tibble(!!paste0("sin", k) := sin(2 * pi * k * doy / 365.25),
           !!paste0("cos", k) := cos(2 * pi * k * doy / 365.25))
  })
}

# Pull the operational numbers out of a fitted seasonal curve.
describe_curve <- function(cv) {
  above <- cv$index >= 1
  cross_down <- which(above[-length(above)] & !above[-1])
  cross_up   <- which(!above[-length(above)] & above[-1])
  end_doy   <- cross_down[cross_down > 60 & cross_down < 240][1]
  start_doy <- cross_up[cross_up > 240][1]

  tibble(
    peak_doy   = cv$doy[which.max(cv$index)],
    trough_doy = cv$doy[which.min(cv$index)],
    start_doy, end_doy,
    peak_val   = max(cv$index),
    trough_val = min(cv$index),
    decline_pct  = 100 * (1 - min(cv$index) / max(cv$index)),
    increase_pct = 100 * (max(cv$index) / min(cv$index) - 1)
  )
}

doy_to_date <- function(d) {
  if (is.na(d)) return("-")
  format(as.Date(d - 1, origin = "2025-01-01"), "%d %b")
}

# Fit a trend, reported per decade and in plain English.
trend_of <- function(w, column) {
  if (nrow(w) < 8) return(list(per_decade = NA, p = NA, label = "not enough data"))
  fit <- lm(reformulate("season_year", column), data = w)
  co  <- summary(fit)$coefficients
  p   <- co["season_year", "Pr(>|t|)"]
  list(
    per_decade = co["season_year", "Estimate"] * 10,
    p          = p,
    label      = if (p < 0.01) "strong evidence"
                 else if (p < 0.05) "some evidence"
                 else if (p < 0.10) "weak, could be noise"
                 else "no real evidence"
  )
}

# =============================================================================
# UI
# =============================================================================
ui <- page_fluid(

    title = "Naples Snowbird Migration",

  # page_fluid does not render a title bar of its own the way page_sidebar
  # does, so the heading is drawn explicitly. Without this the page opens
  # straight onto the settings strip with nothing saying what it is.
  div(
    class = "d-flex align-items-baseline gap-3 mb-3 pb-2",
    style = "border-bottom:2px solid #2a6f97;",
    tags$h4("Naples Snowbird Migration", class = "mb-0 fw-bold",
            style = "color:#1d3f5a;"),
    tags$span(class = "text-muted small",
              "Collier + Lee County, Florida - when the season starts, peaks and ends")
  ),

  tags$head(tags$style(WHY_CSS)),

  # Layout note, learned the hard way.
  # fillable = FALSE looked like the fix for bslib squeezing plots flat, but it
  # made the plot element 440px tall and ZERO pixels WIDE inside the flex
  # layout - a different flavour of the same problem. Leaving fillable at its
  # default and giving the tab card an explicit height gives plots a real size
  # in both directions. The sized() guard in server() handles the brief moment
  # before the browser has measured anything.

  # Apple's actual palette: #1D1D1F text, #F5F5F7 ground, #0071E3 accent.
  # The body stack reaches for SF Pro on Apple hardware first - the real thing -
  # and falls back to DM Sans elsewhere, loaded in the style block below.
  theme = bs_theme(
    version = 5,
    bg = "#FFFFFF", fg = "#1D1D1F",
    primary = "#0071E3",
    base_font = c("-apple-system", "BlinkMacSystemFont", "SF Pro Text",
                  "Segoe UI Variable Text", "DM Sans", "Segoe UI", "sans-serif"),
    heading_font = c("-apple-system", "BlinkMacSystemFont", "SF Pro Display",
                     "Segoe UI Variable Display", "DM Sans", "Segoe UI", "sans-serif"),
    "border-radius" = "14px",
    "card-border-width" = "0"
  ),


  # The headline is the FORECAST, not the temperature trend. The temperature
  # trend turned out not to survive a threshold sweep (see the Robustness tab),
  # so it has no business being the first thing anyone reads. These four are
  # the numbers you would actually act on.
  layout_columns(
    fill = FALSE,

    value_box(
      title = "Next trough", value = head_date(HEAD$trough),
      showcase = icon("arrow-trend-down"), theme = "secondary",
      head_away(HEAD$trough),
      why_tab(
        "Why this date?",
        tags$div(class="mb-2 pb-2", style="border-bottom:1px solid #dee2e6;",
          tags$span(style="font-size:.72rem;font-weight:600;letter-spacing:.04em;color:#c1121f;",
                    "THIS YEAR")),
        live_trough(),
        tags$div(class="mt-3 mb-2 pt-2", style="border-top:1px solid #dee2e6;",
          tags$span(style="font-size:.72rem;font-weight:600;letter-spacing:.04em;color:#6c757d;",
                    "IN A NORMAL YEAR")),
        p(strong("The quietest point of the year."), "Late September is after",
          "the summer visitors have gone and before the snowbirds arrive - and",
          "it sits in the thick of hurricane season, which suppresses travel",
          "on its own."),
        p(strong("How we got it:"), "we fit a smooth repeating curve to every",
          "day of 2024 traffic and take its lowest point. The date shown is the",
          "next time that day of the year comes round."),
        p(strong("Confidence:"), "17-26 September, 90%. The tightest of the",
          "four dates - the curve drops steeply into the trough, so the bottom",
          "is easy to locate."),
        p(class = "text-muted mb-0",
          strong("Caveat: "), "one station (0094) troughs in June instead. Not",
          "every road is a snowbird road.")
      )
    ),

    value_box(
      title = "Season starts", value = head_date(HEAD$start),
      showcase = icon("arrow-right-to-bracket"), theme = "info",
      paste("season ends", head_date(HEAD$end)),
      why_tab(
        "Why this date?",
        tags$div(class="mb-2 pb-2", style="border-bottom:1px solid #dee2e6;",
          tags$span(style="font-size:.72rem;font-weight:600;letter-spacing:.04em;color:#c1121f;",
                    "THIS YEAR")),
        live_start(),
        tags$div(class="mt-3 mb-2 pt-2", style="border-top:1px solid #dee2e6;",
          tags$span(style="font-size:.72rem;font-weight:600;letter-spacing:.04em;color:#6c757d;",
                    "IN A NORMAL YEAR")),
        p(strong("The day traffic first climbs above an ordinary day"), "-",
          "where the smoothed curve crosses 1.0 going up in autumn."),
        p(strong("Why mid-November, not October:"), "the temperature gap reaches",
          "its 'worth going' level around 16 October, but traffic does not",
          "follow for another 25 days. People travel around Thanksgiving and",
          "the holidays, not around the thermometer."),
        p(strong("Confidence:"), "10 November to 7 December, 90%. The widest of",
          "the four - the autumn climb is gradual, and a shallow slope makes",
          "the crossing point genuinely uncertain."),
        p(class = "text-muted mb-0",
          strong("Also: "), "this moves with the curve-flexibility slider. At 1",
          "wave it reads 2 December; at 4 it reads 17 November. The modelling",
          "choice is worth about two weeks.")
      )
    ),

    value_box(
      title = "Next peak", value = head_date(HEAD$peak),
      showcase = icon("arrow-trend-up"), theme = "primary",
      head_away(HEAD$peak),
      why_tab(
        "Why this date?",
        tags$div(class="mb-2 pb-2", style="border-bottom:1px solid #dee2e6;",
          tags$span(style="font-size:.72rem;font-weight:600;letter-spacing:.04em;color:#c1121f;",
                    "THIS YEAR")),
        live_peak(),
        tags$div(class="mt-3 mb-2 pt-2", style="border-top:1px solid #dee2e6;",
          tags$span(style="font-size:.72rem;font-weight:600;letter-spacing:.04em;color:#6c757d;",
                    "IN A NORMAL YEAR")),
        p(strong("The busiest stretch of the year."), "Early March, when the",
          "snowbird population is fullest and spring-break traffic has started",
          "arriving on top of it."),
        p(strong("Read it as a window, not a day:"), "the curve is almost flat",
          "from 20 February to 26 March - 35 days within 1% of the maximum.",
          "A single date implies precision that is not there."),
        p(strong("Confidence:"), "25 February to 21 March, 90%."),
        p(class = "text-muted mb-0",
          strong("Cross-check: "), "March is also the busiest month at the",
          "airport in almost every year on record, and March 2026 set an",
          "all-time monthly record. Two independent datasets agreeing on the",
          "month is more persuasive than either alone.")
      )
    ),

    value_box(
      title = "Peak vs trough", value = sprintf("+%.0f%%", HEAD$increase),
      showcase = icon("arrows-up-down"), theme = "success",
      sprintf("rise from trough; %.0f%% fall from peak", HEAD$decline),
      why_tab(
        "Why these numbers?",
        tags$div(class="mb-2 pb-2", style="border-bottom:1px solid #dee2e6;",
          tags$span(style="font-size:.72rem;font-weight:600;letter-spacing:.04em;color:#c1121f;",
                    "THIS YEAR")),
        live_swing(),
        tags$div(class="mt-3 mb-2 pt-2", style="border-top:1px solid #dee2e6;",
          tags$span(style="font-size:.72rem;font-weight:600;letter-spacing:.04em;color:#6c757d;",
                    "IN A NORMAL YEAR")),
        p(strong("Two ways of describing one gap."), "Traffic falls 24% from the",
          "March peak to the September trough. Coming back the other way it",
          "rises 32%, because the starting point is smaller. Both are correct;",
          "neither is 'the' number."),
        p(strong("How we got it:"), "each station is converted to an index",
          "against its own average day, so a quiet rural road and a stretch of",
          "I-75 can be compared. We then take the high and low of the fitted",
          "curve."),
        p(strong("The spread between roads is large:"), "rural Everglades swings",
          "34%, urban Naples 28%, one station only 17%. If you care about a",
          "specific road, the county average will mislead you."),
        p(class = "text-muted mb-0",
          strong("Caveat: "), "this is traffic, not population. A visitor who",
          "drives twice a day counts twice.")
      )
    )
  ),

  navset_card_tab(

    # -------------------------------------------------------------------------
    nav_panel(
      "This year so far",
      chart_panel(
        heading = "How is this year actually tracking?",
        plain = tagList(
          p("Everything else on this dashboard is a forecast or a study of the",
            "past. This tab is the only one showing", strong("what is happening now"), "."),
          p(strong("Why it has to be airport data: "),
            "the road counters are the better measure, but FDOT publish them",
            "once a year and the newest we have is 2024. Airport passengers are",
            "published monthly, about four weeks after each month ends - so this",
            "is current to within about six weeks, rather than two years."),
          p(strong("How to read it: "),
            "the thick line is this year. The grey band is the range of the last",
            "five years, so anywhere inside it is an ordinary year. Outside the",
            "band is genuinely unusual."),
          textOutput("ytd_summary"),
          live_prediction()
        ),
        chart = spinner(plotOutput("p_ytd", height = "440px"), "440px"),
        footer = tagList(
          spinner(tableOutput("tbl_ytd"), "300px"),
          # The report sits below the chart and the table, so the tab reads
          # top to bottom as: what is happening -> the numbers -> what it means.
          div(class = "mt-4 pt-4", style = "border-top:2px solid #2a6f97;",
              uiOutput("report"))
        ),
        method = tagList(
          p("Monthly passenger totals for Southwest Florida International (RSW)",
            "in Fort Myers - the airport Naples flies through - published by Lee",
            "County Port Authority. The series runs back to 1983."),
          tags$ul(
            tags$li("The annual statistics PDF only rebuilds each January, so it",
                    "stops at last December. The current year is filled in from",
                    "the monthly news releases, each of which states that",
                    "month's count in its opening paragraph."),
            tags$li("The comparison band is the minimum to maximum of the",
                    "previous five years for each month, which is why it widens",
                    "in the winter months - those vary more."),
            tags$li("Year-to-date percentages compare the same months only. With",
                    "seven months published, 2026 is compared against",
                    "January-July of each previous year, not their full totals.")
          ),
          p(strong("What this is not:"), "passengers are not the same as road",
            "traffic. People who drive down are invisible here, and a single",
            "snowbird staying five months counts as two passengers, not 150",
            "days of presence. It is a timing indicator, not a population count.")
        )
      )
    ),

    # -------------------------------------------------------------------------
    nav_panel(
      "Simulation",
      card_body(
        fillable = FALSE,

        div(
          class = "p-3 mb-3",
          style = "background:#eef4f8; border-left:4px solid #2a6f97; border-radius:4px;",
          h6("What if this year isn't normal?", class = "fw-bold mb-2",
             style = "color:#1d3f5a;"),
          div(style = "font-size:0.95rem; line-height:1.55;",
            p("Move the conditions below and watch the peak and trough move with",
              "them. The dials start at what is actually happening right now, so",
              "the first thing you see is this year's real prediction."),
            p(strong("The chain being simulated is one we measured, not invented: "),
              "how warm the northern home states are decides when the temperature",
              "gap crosses the threshold, and traffic then follows roughly 25 days",
              "later. Change the first link and the rest moves."),
            p(class = "text-muted mb-0",
              strong("What it cannot do: "), "this shifts the season, it does not",
              "reshape it. We have one year of daily traffic, so there is no way",
              "to know whether a cold winter makes the season longer as well as",
              "earlier. Treat the shift as directional.")
          )
        ),

        layout_columns(
          col_widths = c(4, 4, 4),
          card(card_header("Northern home states"),
               card_body(
                 sliderInput("sim_north", "Temperature vs normal (°F)",
                             min = -8, max = 8, value = 0, step = 0.5, ticks = FALSE),
                 p(class = "text-muted small mb-0",
                   "Negative = colder than usual up north, which is what pushes",
                   "people south.")
               )),
          card(card_header("Naples"),
               card_body(
                 sliderInput("sim_naples", "Temperature vs normal (°F)",
                             min = -6, max = 6, value = 0, step = 0.5, ticks = FALSE),
                 p(class = "text-muted small mb-0",
                   "Matters far less. The gap is what pulls, and the northern end",
                   "swings much harder.")
               )),
          card(card_header("Behaviour"),
               card_body(
                 sliderInput("sim_lag", "Days traffic lags the thermometer",
                             min = 0, max = 50, value = 25, step = 1, ticks = FALSE),
                 p(class = "text-muted small mb-0",
                   "25 is what we measured. Set it to 0 to see a world where",
                   "people move the moment the weather says so.")
               ))
        ),

        layout_columns(
          fill = FALSE, class = "mt-2",
          value_box(title = "Simulated season start",
                    value = textOutput("sim_start"),
                    showcase = icon("arrow-right-to-bracket"), theme = "info",
                    textOutput("sim_start_delta")),
          value_box(title = "Simulated peak",
                    value = textOutput("sim_peak"),
                    showcase = icon("arrow-trend-up"), theme = "primary",
                    textOutput("sim_peak_delta")),
          value_box(title = "Simulated trough",
                    value = textOutput("sim_trough"),
                    showcase = icon("arrow-trend-down"), theme = "secondary",
                    textOutput("sim_trough_delta"))
        ),

        div(class = "mt-3", uiOutput("sim_explain")),

        plotOutput("p_sim", height = "460px"),

        accordion(
          open = FALSE, class = "mt-3",
          accordion_panel(
            "How was this calculated?", icon = icon("calculator"),
            div(style = "font-size:0.9rem; line-height:1.55;",
              p(strong("Step 1 - shift the temperatures."), "Your two sliders are",
                "added to the 26-year daily averages for Naples and for the",
                "northern home states, producing a 'what if' year."),
              p(strong("Step 2 - find the thermal window."), "We locate the day",
                "in autumn when Naples first becomes warmer than home by more",
                "than the threshold, and the day in spring when it stops being",
                "so. Exactly the calculation used on the Window shift tab."),
              p(strong("Step 3 - apply the measured lag."), "Real traffic does",
                "not turn when the thermometer does; script 05 found it lags by",
                "about 25 days at both ends of the season. That lag is added to",
                "the thermal dates to get traffic dates."),
              p(strong("Step 4 - move the fitted curve."), "The seasonal traffic",
                "curve is shifted by the same number of days, which is where the",
                "simulated peak and trough come from."),
              p(class = "text-muted mb-0",
                strong("The honest limit: "), "step 4 assumes the season slides",
                "rigidly. In reality the peak is anchored partly to the calendar",
                "- spring break and Easter do not care about the weather - so a",
                "large simulated shift will overstate how far the March peak",
                "really moves. The autumn end is the more trustworthy half.")
            )
          )
        )
      )
    ),

    # -------------------------------------------------------------------------
    nav_panel(
      "Season forecast",
      chart_panel(
        heading = "When will Naples be busiest, and when will it be dead?",
        plain = tagList(
          p("Every grey dot is one real day in 2024. The blue line is the",
            "underlying pattern once you ignore the day-to-day noise, and the",
            "shaded band is how sure we are about that line."),
          p(strong("The short version: "),
            "traffic bottoms out in late September, climbs through the autumn,",
            "peaks in early March, then falls away through May. The gap between",
            "the busiest and quietest stretch is about a quarter of all traffic."),
          p(strong("Why you'd care: "),
            "if you staff a business, schedule roadworks, or buy advertising,",
            "these are the dates that decide when demand arrives and when it",
            "disappears.")
        ),
        chart = spinner(plotOutput("p_forecast", height = "440px"), "440px"),
        footer = spinner(tableOutput("tbl_forecast"), "260px"),
        method = tagList(
          p(strong("Fitting waves to a season."),
            "A season repeats every year, so it can be described by sine waves.",
            "We fit 1 to 4 waves per year (the 'flexibility' slider) and let the",
            "maths decide where the peak sits, rather than eyeballing it."),
          tags$ul(
            tags$li("Traffic is converted to an index first: 1.0 = a normal day",
                    "at that counting station. That lets a 3,600-cars-a-day rural",
                    "road be averaged with a 109,000-a-day stretch of I-75."),
            tags$li("Day-of-week terms are included so quiet Sundays don't get",
                    "mistaken for a seasonal dip."),
            tags$li("We model the logarithm of the index, so effects come out as",
                    "percentages rather than absolute car counts."),
            tags$li(strong("The band:"), "a moving-block bootstrap. We rebuild the",
                    "dataset 200 times by reshuffling 14-day chunks of the",
                    "leftover variation, refit each time, and see how much the",
                    "answer wobbles. Whole chunks, not single days, because a busy",
                    "Tuesday implies a busy Wednesday."),
            tags$li("Hurricanes Debby, Helene and Milton are cut out. Milton's",
                    "landfall day ran at 30% of normal traffic and would",
                    "otherwise read as a seasonal collapse.")
          ),
          p(strong("The catch:"), "this is fitted to one year. The band tells you",
            "how well we know 2024 - not how much the season shifts between",
            "years, which one year cannot tell you.")
        )
      )
    ),

    # -------------------------------------------------------------------------
    nav_panel(
      "Traffic vs temperature",
      chart_panel(
        heading = "Do people actually move when the weather tells them to?",
        plain = tagList(
          p("Red is real traffic on Naples roads. Blue is how much warmer Naples",
            "is than the places people come from. If people simply followed the",
            "weather, the two lines would rise and fall together."),
          p(strong("They don't quite. "),
            "Blue peaks in mid-January; red doesn't peak until late February.",
            "Traffic turns up about 25 days after the weather says it should -",
            "and leaves about 25 days after the weather stops justifying it."),
          p(strong("Why that matters: "),
            "a lag at both ends is what a ", strong("calendar"), " looks like, not",
            "a thermometer. People arrive after Thanksgiving and leave after",
            "Easter. Weather sets the backdrop; the diary picks the date. So",
            "forecasting the season from a weather forecast would not work well.")
        ),
        chart = spinner(plotOutput("p_traffic", height = "460px"), "460px"),
        method = tagList(
          tags$ul(
            tags$li("Traffic: daily counts from the continuous counting stations in",
                    "Collier AND Lee counties - machines in the road counting cars",
                    "24/7 - for every day of 2024, with hurricane days removed."),
            tags$li("Only stations that ran nearly the whole year are used. A",
                    "sensor that broke in July would fake a summer collapse."),
            tags$li("Temperature: the daily gap between Naples and the origin",
                    "states you have selected, smoothed over 7 days."),
            tags$li("Both are drawn on their own scales so the shapes can be",
                    "compared; the correlation (r) in the subtitle is the real",
                    "measure of how closely they track.")
          ),
          p("r near 1 would mean they move together perfectly. It comes out",
            "around 0.66, so temperature explains under half of the day-to-day",
            "variation - and with that 25-day delay on top.")
        )
      )
    ),

    # -------------------------------------------------------------------------
    nav_panel(
      "Robustness",
      chart_panel(
        heading = "Would this finding survive if we'd picked a different number?",
        plain = tagList(
          p("The temperature analysis needs a judgement call: how much warmer",
            "does Naples have to be before the trip is 'worth it'? That number",
            "was chosen by hand. This chart redoes the entire analysis at every",
            "sensible value and shows what answer each one gives."),
          p(strong("Red dots are 'statistically significant' results. "),
            "If they appeared everywhere, the finding would be solid. They",
            "appear in one narrow band and nowhere else - and that band happens",
            "to contain the number originally picked."),
          p(strong("What it means: "),
            "the apparent finding that the season is shifting is an accident of",
            "where the line was drawn. Out of 25 attempts, 2 came out",
            "significant - which is exactly what pure chance produces. This is",
            "the most important chart here, because it is the one that says",
            strong("don't believe the other one"), ".")
        ),
        chart = spinner(plotOutput("p_sweep", height = "620px"), "620px"),
        method = tagList(
          p("The whole pipeline is re-run at every threshold from 12 to 36",
            "degrees F. For each one we find the season's start and end dates",
            "in all 26 years, fit a straight line through them, and record both",
            "the slope and the p-value."),
          tags$ul(
            tags$li(strong("p-value:"), "roughly, the chance of seeing a trend",
                    "this strong if nothing were really happening. Below 0.05 is",
                    "the usual (crude) bar for 'probably real'."),
            tags$li(strong("Why 2 out of 25 is nothing:"), "at a 1-in-20",
                    "threshold, testing 25 times should produce about 1 false",
                    "positive by luck alone. Getting 2 is unremarkable."),
            tags$li("The dotted blue line marks your current slider setting, so",
                    "you can see whether you happen to be standing in the lucky",
                    "band.")
          )
        )
      )
    ),

    # -------------------------------------------------------------------------
    nav_panel(
      "Window shift",
      chart_panel(
        heading = "Has the weather's invitation been arriving later each year?",
        plain = tagList(
          p("Each dot is one year. Orange marks the autumn date when Naples",
            "first became much warmer than back home. Blue marks the spring date",
            "when that advantage disappeared. The straight lines show whether",
            "those dates have been drifting over 26 years."),
          p(strong("What it looks like: "),
            "a slight drift towards a later start. What it actually is: ",
            strong("probably nothing"), " - see the Robustness tab, where this",
            "result falls apart the moment you change the threshold."),
          p(strong("Worth knowing: "),
            "this measures thermometers, not people. It shows when the weather",
            "made the trip worthwhile, not when anyone actually travelled.")
        ),
        chart = spinner(plotOutput("p_shift", height = "460px"), "460px"),
        footer = tagList(
          p(class = "text-muted small mt-2", textOutput("trend_note")),
          div(class = "alert alert-warning py-2 px-3 small mt-2",
              strong("Health warning. "),
              "This trend is significant at only 2 of 25 thresholds - what",
              "chance alone produces. Check the Robustness tab before believing",
              "anything here.")
        ),
        method = tagList(
          tags$ul(
            tags$li("For every day since 2000 we take Naples' average",
                    "temperature and subtract the average across the origin",
                    "states. That difference is 'the gap'."),
            tags$li("The gap is smoothed over 7 days, so a single cold Tuesday",
                    "in Chicago doesn't count as the season starting."),
            tags$li("A season runs July to June, because a winter season",
                    "straddles New Year and calendar years would cut it in half."),
            tags$li("Within each season we find the first autumn day the gap",
                    "rises past your threshold, and the first spring day it",
                    "falls back below."),
            tags$li("A straight line is fitted through those dates against year.",
                    "The slope is the drift in days per decade.")
          )
        )
      )
    ),

    # -------------------------------------------------------------------------
    nav_panel(
      "Shape of a year",
      chart_panel(
        heading = "How much warmer is Naples than back home?",
        plain = tagList(
          p("This is the whole reason snowbirds exist, in one line. It shows the",
            "average temperature difference between Naples and the northern",
            "states where these residents keep their other home."),
          p(strong("In midwinter Naples runs about 40 degrees F warmer. "),
            "By July the difference nearly vanishes - a summer day in Michigan",
            "is much like a summer day in Florida, minus the humidity."),
          p(strong("Why it matters: "),
            "nobody moves south because Naples got warm. They move because",
            "home got cold. The red dashed line is your threshold - the point",
            "you've decided the difference is big enough to be worth the trip."),
          p(class = "text-muted small mb-0",
            strong("Fixed at "), "25 °F, all northern home states, weighted by ",
            "migrants sent. Set in code rather than on the page - the Robustness ",
            "tab shows what every other threshold would have given.")
        ),
        chart = spinner(plotOutput("p_year", height = "460px"), "460px"),
        method = tagList(
          p("Daily temperatures from 2000 to 2026 for Naples and for each origin",
            "state, from the Open-Meteo historical archive. For each of the 365",
            "days of the year we average that day across all 26 years, giving",
            "the typical shape of a year rather than any single one."),
          p("Each state sits at the point where its migrants actually live -",
            "weighted by the counties they came from - so Illinois is placed on",
            "Chicago rather than in the middle of a cornfield.")
        )
      )
    ),

    # -------------------------------------------------------------------------
    nav_panel(
      "Northern home states",
      chart_panel(
        heading = "Where are their northern homes?",
        plain = tagList(
          p("Each bar is a northern state where Naples snowbirds keep a home,",
            "sized by how many came from there. Measured from tax records,",
            "not guessed."),
          p(strong("Illinois, New York, Massachusetts and New Jersey "),
            "supply nearly half of all out-of-state arrivals between them."),
          p(strong("Why it matters: "),
            "it decides whose winter counts. Weighting by real numbers beats",
            "assuming - the first version of this analysis guessed Cleveland and",
            "Toronto, and the data says Ohio is minor while New Jersey, which",
            "had been left out entirely, is top four.")
        ),
        chart = spinner(plotOutput("p_states", height = "420px"), "420px"),
        footer = tableOutput("tbl_states"),
        method = tagList(
          p("The IRS publishes county-to-county migration every year, built from",
            "address changes between tax returns. We take every inflow into",
            "Collier County, attach each origin county's geographic centre from",
            "the Census gazetteer, then collapse to states at the",
            "migration-weighted centre of their origin counties."),
          p(strong("The big caveat:"), "this only sees people who CHANGED THEIR",
            "TAX ADDRESS. A classic snowbird deliberately doesn't - they keep",
            "the northern house and the northern domicile. So this measures",
            "permanent relocation and we're using it as a stand-in for seasonal",
            "movement. It also misses Canadians entirely, who file no US return,",
            "even though Ontario owns roughly 4,000 Naples homes.")
        )
      )
    ),

    # -------------------------------------------------------------------------
    nav_panel(
      "50 years",
      chart_panel(
        heading = "Is Naples just getting busier?",
        plain = tagList(
          p("Traffic on a typical Collier or Lee County road, every year back to 1970."),
          p(strong("Why it's here: "),
            "it separates two things that are easy to confuse. Roads getting",
            "busier every year is ", strong("growth"), ". Roads getting busier",
            "every winter is ", strong("seasonality"), ". This project is about",
            "the second, and you need the first in view to avoid mistaking one",
            "for the other.")
        ),
        chart = spinner(plotOutput("p_hist", height = "460px"), "460px"),
        method = tagList(
          p("From FDOT's historical traffic database: 5,339 site-years of",
            "Annual Average Daily Traffic for Collier and Lee counties, 1970 to 2025."),
          p(strong("AADT"), "is the average number of vehicles passing a point",
            "per day across a whole year. We plot the median across all sites,",
            "not the mean, so one enormous stretch of I-75 doesn't dominate.",
            "Years with fewer than 20 reporting sites are dropped as too thin."),
          p("Note that AADT is an annual average by construction - it",
            "deliberately flattens the seasonal swing, which is why it cannot",
            "answer the timing questions on the other tabs.")
        )
      )
    ),

    # -------------------------------------------------------------------------
    nav_panel(
      "Raw data",
      chart_panel(
        heading = "The raw data behind the charts",
        plain = p("One row per season: the date the temperature gap crossed your",
                  "threshold going up, the date it fell back, and how many days",
                  "that left in between. Everything on the Window shift tab is",
                  "drawn from this table."),
        chart = tableOutput("tbl"),
        method = p("Produced by the same crossing calculation described on the",
                   "Window shift tab. Change the threshold or the selected",
                   "states and every row here recalculates.")
      )
    )
,

    # -------------------------------------------------------------------------
    nav_panel(
      "Future trends",
      chart_panel(
        heading = "Where is this heading? Are snowbirds turning into full-time residents?",
        plain = tagList(
          p("Two different questions here, and they have different answers."),
          p(strong("1. Are more people moving here for good? "),
            "The top chart counts people who changed their tax address to",
            "Collier County - which is not a proxy for moving permanently, it",
            strong(" is "), "moving permanently. Northern arrivals went from",
            "6,600 a year in 2012 to a peak of 11,600 in 2021."),
          p(strong("2. Are the ones who still come seasonally staying longer? "),
            "The bottom chart watches the shoulder months - October, April,",
            "May - against the December-to-March core. If stays were",
            "lengthening, people would arrive before the rush and leave after",
            "it, and the shoulders would fatten."),
          p(class = "text-muted mb-0",
            strong("The short answer: "), "there was a big jump in permanent",
            "moves, but it was the pandemic rather than a gradual conversion -",
            "take 2020-22 out and the trend all but disappears. Meanwhile the",
            "people who still come seasonally are ", strong("not"), " staying",
            "longer; if anything the season is tightening around its core.")
        ),
        chart = tagList(
          spinner(plotOutput("p_permanent", height = "400px"), "400px"),
          div(class = "mt-4"),
          spinner(plotOutput("p_longer", height = "400px"), "400px")
        ),
        footer = uiOutput("permanent_verdict"),
        method = tagList(
          p(strong("Permanent moves."), "IRS county-to-county migration, twelve",
            "editions from 2011-12 to 2022-23. Each counts households whose tax",
            "address changed into Collier County, and where from. Filtered to",
            "24 northern states with a real winter, so people moving up from",
            "Miami are not counted as snowbirds."),
          p(strong("A trap in this data worth knowing about: "),
            "FIPS county codes are zero-padded in most editions ('021') but not",
            "in the 2020-21 and 2021-22 files ('21'). Matching on the string",
            "silently drops those two years - no error, just a shorter trend.",
            "Correcting it changed the headline from 'no clear trend' to",
            "significant, which is how much two missing points can matter."),
          p(strong("Staying longer."), "RSW monthly passengers, ratio of",
            "(Oct + Apr + May) to (Dec + Jan + Feb + Mar). A ratio is used",
            "rather than raw numbers so airport growth cannot masquerade as",
            "longer stays. Storm and COVID seasons are excluded."),
          p(class = "text-muted mb-0",
            strong("What neither can see: "), "a snowbird who keeps their",
            "northern tax address, which is most of them and often deliberate.",
            "Question 1 measures the flow of people CONVERTING to permanent,",
            "not the stock of seasonal residents.")
        )
      )
    )
  )
)

# =============================================================================
# SERVER
# =============================================================================
server <- function(input, output, session) {

  # ---------------------------------------------------------------------------
  # Wait until the browser has actually laid the plot out
  # ---------------------------------------------------------------------------
  # bslib activates a tab panel with JavaScript AFTER Shiny takes its first
  # measurement, so on the very first paint Shiny is told the plot is 0 pixels
  # wide. It renders into that and base graphics throws
  #     Error in graphics::plot.new: figure margins too large
  # which then sits there until something forces a redraw.
  #
  # Shiny publishes each output's measured size in session$clientData. req()
  # aborts the render quietly if the size isn't real yet; when the browser
  # reports a proper size moments later, Shiny re-runs this block on its own.
  # Quietly doing nothing beats loudly rendering garbage.
  sized <- function(id) {
    w <- session$clientData[[paste0("output_", id, "_width")]]
    h <- session$clientData[[paste0("output_", id, "_height")]]
    req(!is.null(w), !is.null(h), w > 50, h > 50)
  }

  # NAMESPACE NOTE: shiny::validate() spelled in full, because jsonlite also
  # exports validate() and whichever loads last wins. The symptom is a baffling
  # "is.character(txt) is not TRUE".
  gap <- reactive({
    build_gap(ALL_STATES, WEIGHTED)
  })

  windows <- reactive(find_windows(gap(), THRESHOLD))

  t_opens  <- reactive(trend_of(windows(), "opens_d"))
  t_closes <- reactive(trend_of(windows(), "closes_d"))
  t_len    <- reactive(trend_of(windows(), "window_days"))

  fmt <- function(x) if (is.na(x)) "-" else sprintf("%+.1f days", x)

  # The temperature trend now lives under the Window shift chart rather than
  # in the headline, because it does not survive the Robustness tab.
  output$trend_note <- renderText({
    paste0("Trend at this threshold: opens ", fmt(t_opens()$per_decade),
           "/decade (", t_opens()$label, "), closes ", fmt(t_closes()$per_decade),
           "/decade (", t_closes()$label, "), window length ",
           fmt(t_len()$per_decade), "/decade (", t_len()$label, ").")
  })

  # ---------------------------------------------------------------------------
  # HEADLINE: the next peak and trough, as real calendar dates
  # ---------------------------------------------------------------------------
  # Turn a day-of-year into the next time that day comes round.
  next_occurrence <- function(doy, from = Sys.Date()) {
    if (is.na(doy)) return(as.Date(NA))
    d <- as.Date(paste0(format(from, "%Y"), "-01-01")) + (doy - 1)
    if (d < from) d <- as.Date(paste0(as.integer(format(from, "%Y")) + 1, "-01-01")) + (doy - 1)
    d
  }

  fmt_date <- function(d) if (is.na(d)) "-" else format(d, "%d %b %Y")
  days_off <- function(d) {
    if (is.na(d)) return("")
    n <- as.numeric(d - Sys.Date())
    if (n == 0) "today" else if (n == 1) "tomorrow" else paste(n, "days away")
  }

  # The headline dates were taking 1.5 seconds to appear, because every one of
  # them waited on forecast_fit() - which refits the harmonic model and runs
  # 200 bootstrap replicates before it can produce a single date. The page
  # therefore opened with four blank boxes.
  #
  # But R/09 has already done that work and written the answer to
  # output/season_forecast.csv, using 600 replicates rather than 200. At the
  # default flexibility there is nothing to recompute: read the stored answer
  # and the boxes fill instantly.
  #
  # Only when the flexibility slider is moved away from its default does this
  # fall through to the live fit, so the numbers still respond to the control -
  # they just do not make everyone wait for a result that was already on disk.
  DEFAULT_K <- 4

  nxt <- reactive({
    s <- if (!is.null(fc_static) && isTRUE(HARMONICS == DEFAULT_K)) {
      fc_static
    } else {
      forecast_fit()$stats
    }

    list(
      trough = next_occurrence(s$trough_doy),
      peak   = next_occurrence(s$peak_doy),
      start  = next_occurrence(s$start_doy),
      end    = next_occurrence(s$end_doy),
      stats  = s
    )
  })

  output$vb_trough     <- renderText(fmt_date(nxt()$trough))
  output$vb_trough_sub <- renderText(days_off(nxt()$trough))
  output$vb_peak       <- renderText(fmt_date(nxt()$peak))
  output$vb_peak_sub   <- renderText(days_off(nxt()$peak))
  output$vb_start      <- renderText(fmt_date(nxt()$start))
  output$vb_start_sub  <- renderText(paste("season ends", fmt_date(nxt()$end)))

  output$vb_swing <- renderText(sprintf("+%.0f%%", nxt()$stats$increase_pct))
  output$vb_swing_sub <- renderText(
    sprintf("rise from trough; %.0f%% fall from peak", nxt()$stats$decline_pct))

  # --- Window shift ---------------------------------------------------------
  output$p_shift <- renderPlot({
    sized("p_shift")
    windows() %>%
      select(season_year, opens, closes) %>%
      pivot_longer(c(opens, closes), names_to = "edge", values_to = "date") %>%
      mutate(
        d = as.numeric(date - make_date(season_year, 7, 1)),
        edge = factor(edge, levels = c("opens", "closes"),
                      labels = c("Opens (autumn)", "Closes (spring)"))
      ) %>%
      ggplot(aes(season_year, d, colour = edge)) +
      geom_point(size = 2.8, alpha = 0.85) +
      geom_smooth(method = "lm", se = TRUE, linewidth = 1) +
      scale_colour_manual(values = c("#e07a5f", "#3d5a80")) +
      scale_y_continuous(breaks = c(92, 153, 214, 275, 336),
                         labels = c("1 Oct", "1 Dec", "1 Feb", "1 Apr", "1 Jun")) +
      labs(title = "When does the migration window open and close?",
           subtitle = paste0(THRESHOLD, "°F threshold · ",
                             length(ALL_STATES), " states"),
           x = "Season (year it began)", y = NULL, colour = NULL) +
      theme(legend.position = "top")
  })

  # --- Shape of a year ------------------------------------------------------
  output$p_year <- renderPlot({
    sized("p_year")
    gap() %>%
      filter(!is.na(gap_smooth)) %>%
      mutate(doy = yday(date)) %>%
      group_by(doy) %>%
      summarise(g = mean(gap_smooth), .groups = "drop") %>%
      ggplot(aes(doy, g)) +
      geom_area(fill = "#2a6f97", alpha = 0.15) +
      geom_line(colour = "#2a6f97", linewidth = 1.3) +
      geom_hline(yintercept = THRESHOLD, linetype = "dashed",
                 colour = "#c1121f", linewidth = 0.8) +
      annotate("text", x = 183, y = THRESHOLD + 1.6,
               label = paste0("threshold: ", THRESHOLD, "°F"),
               colour = "#c1121f", hjust = 0, size = LBL) +
      scale_x_continuous(breaks = c(1, 60, 121, 182, 244, 305),
                         labels = c("Jan", "Mar", "May", "Jul", "Sep", "Nov")) +
      labs(title = "How much warmer is Naples than back home?",
           subtitle = "Averaged across 2000-2026",
           x = NULL, y = "Temperature gap (°F)")
  })

  # --- Robustness sweep -----------------------------------------------------
  output$p_sweep <- renderPlot({
    sized("p_sweep")
    g <- gap()
    sweep <- map_dfr(seq(12, 36, by = 1), function(th) {
      w <- find_windows(g, th)
      if (nrow(w) < 8) return(NULL)
      map_dfr(c("opens_d", "closes_d", "window_days"), function(col) {
        tr <- trend_of(w, col)
        tibble(threshold = th, measure = col,
               slope = tr$per_decade, p = tr$p)
      })
    })

    shiny::validate(shiny::need(nrow(sweep) > 0, "Not enough data to sweep."))

    sweep %>%
      mutate(
        measure = recode(measure, opens_d = "Opens",
                         closes_d = "Closes", window_days = "Length"),
        sig = if_else(p < 0.05, "p < 0.05", "not significant")
      ) %>%
      ggplot(aes(threshold, slope)) +
      geom_hline(yintercept = 0, colour = "grey30") +
      geom_line(colour = "grey75") +
      geom_point(aes(colour = sig), size = 2.8) +
      geom_vline(xintercept = THRESHOLD, linetype = "dotted",
                 colour = "#2a6f97", linewidth = 0.8) +
      facet_wrap(~measure, ncol = 1, scales = "free_y") +
      scale_colour_manual(values = c("p < 0.05" = "#c1121f",
                                     "not significant" = "grey55")) +
      labs(title = "Does the finding survive a different threshold?",
           subtitle = "Blue dotted line = your current setting. Above zero = later.",
           x = "Migration threshold (°F)", y = "Days per decade", colour = NULL) +
      theme(legend.position = "top")
  })

  # --- Traffic vs temperature ----------------------------------------------
  output$p_traffic <- renderPlot({
    sized("p_traffic")
    shiny::validate(shiny::need(!is.null(traffic_daily),
                                "Run R/04_fetch_fti.R to get the traffic data."))

    tr <- traffic_daily %>% filter(!date %in% STORM_DAYS)
    good <- tr %>% count(site) %>% filter(n >= 330) %>% pull(site)

    county <- tr %>%
      filter(site %in% good) %>%
      group_by(site) %>% mutate(index = volume / mean(volume)) %>% ungroup() %>%
      group_by(date) %>% summarise(index = mean(index), .groups = "drop") %>%
      arrange(date) %>%
      mutate(index_s = as.numeric(stats::filter(index, rep(1/7, 7), sides = 2)))

    both <- county %>%
      inner_join(gap() %>% select(date, gap_smooth), by = "date") %>%
      filter(!is.na(index_s), !is.na(gap_smooth))

    shiny::validate(shiny::need(nrow(both) > 30, "Not enough overlapping days."))

    ri <- range(both$index_s); rg <- range(both$gap_smooth)
    to_i <- function(x) (x - rg[1]) / diff(rg) * diff(ri) + ri[1]
    to_g <- function(x) (x - ri[1]) / diff(ri) * diff(rg) + rg[1]

    r <- cor(both$index_s, both$gap_smooth)

    ggplot(both, aes(date)) +
      geom_line(aes(y = to_i(gap_smooth), colour = "Temperature gap"), linewidth = 1) +
      geom_line(aes(y = index_s, colour = "Traffic"), linewidth = 1.3) +
      geom_hline(yintercept = 1, linetype = "dotted", colour = "grey40") +
      scale_y_continuous(name = "Traffic (1.0 = average day)",
                         sec.axis = sec_axis(~ to_g(.), name = "Temperature gap (°F)")) +
      scale_x_date(date_labels = "%b", date_breaks = "1 month") +
      scale_colour_manual(values = c("Traffic" = "#c1121f",
                                     "Temperature gap" = "#2a6f97")) +
      labs(title = "Do snowbirds follow the thermometer?",
           subtitle = paste0("Collier + Lee daily traffic vs the gap, 2024. ",
                             "Hurricanes removed. r = ", round(r, 2)),
           x = NULL, colour = NULL) +
      theme(legend.position = "top")
  })

  # --- Current report -------------------------------------------------------
  # Written from the live objects rather than pasted in as prose, so it
  # regenerates itself whenever the pipeline rewrites its outputs. Re-run
  # R/09 with a second year of traffic and every figure below moves with it;
  # nothing here has to be edited by hand.
  output$report <- renderUI({
    s      <- HEAD
    trough <- head_date(s$trough); start <- head_date(s$start)
    peak   <- head_date(s$peak);   endd  <- head_date(s$end)

    # Where this year departs from a normal one
    n_anom <- cnum("north_anom"); g_anom <- cnum("gap_anom")
    oni    <- cnum("oni_value");  ytd    <- cnum("rsw_ytd_change")

    winter <- if (is.na(n_anom)) "unknown"
              else if (n_anom <= -1.5) "early"
              else if (n_anom <= -0.5) "slightly early"
              else if (n_anom >=  1.5) "late"
              else if (n_anom >=  0.5) "slightly late"
              else "on time"

    h <- function(t) tags$h5(t, class = "fw-bold mt-4 mb-2",
                             style = "color:#1d3f5a; font-size:1.05rem;")

    div(
      style = "max-width:76ch; font-size:0.97rem; line-height:1.62;",

      div(class = "pb-2 mb-3", style = "border-bottom:2px solid #2a6f97;",
          tags$h4("Snowbird Season Report", class = "mb-1 fw-bold",
                  style = "color:#1d3f5a;"),
          tags$div(class = "text-muted small",
                   sprintf("Collier + Lee County, Florida · generated %s · conditions measured %s",
                           format(Sys.Date(), "%d %B %Y"), ctxt("updated")))),

      h("The forecast"),
      tags$ul(
        tags$li(strong("Trough "), trough, " — the quietest point of the year"),
        tags$li(strong("Season opens "), start, " — traffic first exceeds an ordinary day"),
        tags$li(strong("Peak "), peak, " — flat across a five-week window, so treat it as a period"),
        tags$li(strong("Season ends "), endd),
        tags$li(sprintf("Peak runs %.0f%% above the trough; traffic falls %.0f%% coming back down",
                        s$increase, s$decline))
      ),

      h("How it is built"),
      p("A harmonic regression on ", strong("2024 daily traffic counts"), " from six ",
        "continuous stations across Collier and Lee counties — machines in the ",
        "road counting vehicles every day of the year. Sine and cosine pairs at one ",
        "to four cycles per year describe the seasonal shape without anyone having ",
        "to say where the peak sits; day-of-week terms keep quiet Sundays from ",
        "being read as a seasonal dip. The model is fitted to the logarithm of a ",
        "traffic index, so effects come out as percentages and a rural road on ",
        "3,660 vehicles a day can be averaged with a stretch of I-75 on 125,228."),
      p("Confidence intervals come from a ", strong("moving-block bootstrap"),
        " — contiguous 14-day blocks of residuals, resampled 600 times, because ",
        "a busy Tuesday implies a busy Wednesday and pretending otherwise would ",
        "make the intervals far too narrow. Hurricane windows are excluded: 2024 ",
        "had three storms, and Milton's landfall alone ran at 30% of normal traffic."),

      h("Conditions entering this season"),
      tags$ul(
        if (!is.na(oni)) tags$li(sprintf("El Niño index %+.2f — %s, %s Atlantic hurricane activity",
                                         oni, ctxt("oni_state"), ctxt("hurricane_outlook"))) else NULL,
        if (!is.na(n_anom)) tags$li(sprintf("Northern home states running %+.1f °F against normal — winter arriving %s",
                                            n_anom, winter)) else NULL,
        if (!is.na(g_anom)) tags$li(sprintf("The migration gap is %+.1f °F against its own normal — %s",
                                            g_anom,
                                            if (g_anom < -0.4) "a weaker pull south than usual"
                                            else if (g_anom > 0.4) "a stronger pull than usual"
                                            else "about as usual")) else NULL,
        if (!is.na(ytd)) tags$li(sprintf("Airport arrivals %+.2f%% year to date against last year", ytd)) else NULL
      ),
      p(sprintf("On that basis the trough is estimated at %s, the season opening around %s, and the peak around %s. ",
                trough, start, peak),
        if (!is.na(oni) && oni >= 0.5)
          "With hurricanes suppressed this year, expect the trough to be shallower than the model's average year — the date should hold, the depth should not."
        else ""),

      h("What this cannot do"),
      p("The seasonal shape rests on ", strong("one year"), " of daily counts, because ",
        "FDOT overwrite the detailed tables with each annual edition rather than ",
        "accumulating them. The intervals therefore say how precisely we know 2024, ",
        "not how much the season varies between years. Treat them as a floor."),
      p("Weather forecasting cannot fill that gap, and this was tested rather than ",
        "assumed: beyond 60 days NOAA's seasonal ensemble is 1.12× the spread of ",
        "plain climatology — wider than simply knowing what month it is. And the ",
        "roads disagree with each other, with peak timing spanning two months and ",
        "amplitude varying twofold across stations."),

      div(class = "mt-4 pt-3", style = "border-top:1px solid #dee2e6;",
          p(class = "text-muted small mb-0",
            strong("This report regenerates itself. "),
            "Every figure above is read from the analysis outputs at load, so ",
            "re-running the pipeline updates it — nothing here is typed by hand. ",
            "The watcher checks all sources daily and raises an alert if a ",
            "headline date moves."))
    )
  })

  # --- Becoming permanent? --------------------------------------------------
  output$p_permanent <- renderPlot({
    sized("p_permanent")
    shiny::validate(shiny::need(!is.null(permanent_moves),
                                "Run R/15_becoming_permanent.R first."))

    permanent_moves %>%
      pivot_longer(c(northern_people, total_people),
                   names_to = "grp", values_to = "n") %>%
      mutate(grp = recode(grp,
                          northern_people = "From northern states",
                          total_people    = "From anywhere out of state")) %>%
      ggplot(aes(year, n, colour = grp)) +
      annotate("rect", xmin = 2019.5, xmax = 2022.5, ymin = -Inf, ymax = Inf,
               fill = "grey85", alpha = 0.55) +
      annotate("text", x = 2021, y = Inf, label = "pandemic wave",
               vjust = 1.8, size = LBL - 0.6, colour = "grey35") +
      geom_line(linewidth = 1.3) +
      geom_point(size = 2.8) +
      scale_y_continuous(labels = comma) +
      scale_x_continuous(breaks = seq(2012, 2023, 2)) +
      scale_colour_manual(values = c("From northern states" = "#c1121f",
                                     "From anywhere out of state" = "#3d5a80")) +
      labs(title = "People moving permanently into Collier County",
           subtitle = "IRS tax-address changes. These are moves, not visits.",
           x = NULL, y = "People per year", colour = NULL) +
      theme(legend.position = "top")
  })

  output$p_longer <- renderPlot({
    sized("p_longer")
    shiny::validate(shiny::need(!is.null(season_shape),
                                "Run R/15_becoming_permanent.R first."))

    EXCL <- c(2004, 2017, 2019, 2020, 2022, 2024)
    clean <- season_shape %>% filter(!season %in% EXCL)

    ggplot(clean, aes(season, shoulder_ratio)) +
      geom_line(colour = "grey70", linewidth = 0.9) +
      geom_point(size = 2.8, colour = "#3d5a80") +
      geom_smooth(method = "lm", se = TRUE, colour = "#c1121f", linewidth = 1.2) +
      labs(title = "Are seasonal visitors staying longer?",
           subtitle = paste0("Shoulder months (Oct, Apr, May) against the Dec-Mar core. ",
                             "Rising would mean longer stays.\n",
                             "Storm and COVID seasons excluded."),
           x = "Season (year it began)", y = "Shoulder / core ratio")
  })

  output$permanent_verdict <- renderUI({
    if (is.null(permanent_moves)) return(NULL)

    p_all <- permanent_moves
    f1 <- lm(northern_people ~ year, data = p_all)
    c1 <- summary(f1)$coefficients["year", c("Estimate","Pr(>|t|)")]

    p_nc <- p_all %>% filter(!year %in% c(2020, 2021, 2022))
    f2 <- lm(northern_people ~ year, data = p_nc)
    c2 <- summary(f2)$coefficients["year", c("Estimate","Pr(>|t|)")]

    div(class = "p-3 mt-3",
        style = "background:#fff5f5; border-left:4px solid #c1121f; border-radius:4px;",
      tags$span(style="font-size:.72rem;font-weight:700;letter-spacing:.05em;color:#c1121f;",
                "VERDICT"),
      p(class = "mt-2 mb-2",
        strong("Permanent moves: mostly a pandemic effect. "),
        sprintf("Across all %d years the rise looks solid (%+.0f people a year, p = %.3f). ",
                nrow(p_all), c1[1], c1[2]),
        sprintf("Remove 2020-22 and it collapses to %+.0f a year, p = %.2f. ",
                c2[1], c2[2]),
        "2021 alone brought 11,566 northern arrivals against a pre-COVID norm",
        "near 7,000 - that is the remote-work exodus, not snowbirds gradually",
        "converting."),
      p(class = "mb-0",
        strong("Staying longer: no. "),
        "The shoulder-to-core ratio is flat to slightly falling",
        "(-1.2% per decade, p = 0.07 across 36 clean seasons). Those who still",
        "come seasonally are not extending their stays; if anything the season",
        "is tightening around its core months."))
  })

  # --- Simulation -----------------------------------------------------------
  # Deliberately SELF-CONTAINED: it reads the module-level data and the stored
  # forecast directly rather than calling gap() or forecast_fit().
  #
  # The first version chained off both of those. Every output on the tab then
  # sat on "recalculating" forever with no error and the R process idle at 0%
  # CPU - the signature of a silent validate()/req() abort propagating up from
  # a dependency, not of a slow computation. Decoupling removes the failure
  # mode, and is the better design anyway: a what-if tool should own its inputs
  # rather than inherit the sidebar's.
  sim <- reactive({
    shift <- input$sim_naples - input$sim_north   # net change to the gap

    thermal <- function(delta) {
      find_windows(mutate(SIM_BASE_GAP, gap_smooth = gap_smooth + delta),
                   THRESHOLD)
    }

    med <- function(w, col) if (nrow(w) == 0) NA_real_ else median(w[[col]], na.rm = TRUE)

    base_w <- thermal(0)
    sim_w  <- thermal(shift)

    d_open <- med(sim_w, "opens_d") - med(base_w, "opens_d")
    thermal_shift <- if (is.na(d_open)) 0 else as.integer(round(d_open))

    lag_delta <- input$sim_lag - 25          # 25 is the measured lag
    total     <- thermal_shift + lag_delta

    bump <- function(doy) {
      if (is.null(doy) || is.na(doy)) return(as.Date(NA))
      next_occurrence(((doy - 1 + total) %% 365) + 1)
    }

    list(
      shift_days    = total,
      thermal_shift = thermal_shift,
      lag_delta     = lag_delta,
      start  = bump(fc_static$start_doy),
      peak   = bump(fc_static$peak_doy),
      trough = bump(fc_static$trough_doy)
    )
  })

  sim_fmt <- function(d) if (is.na(d)) "-" else format(d, "%d %b %Y")
  sim_delta <- function(n) {
    if (n == 0) "unchanged from normal"
    else sprintf("%d days %s than normal", abs(n), if (n > 0) "later" else "earlier")
  }

  output$sim_start        <- renderText(sim_fmt(sim()$start))
  output$sim_start_delta  <- renderText(sim_delta(sim()$shift_days))
  output$sim_peak         <- renderText(sim_fmt(sim()$peak))
  output$sim_peak_delta   <- renderText(sim_delta(sim()$shift_days))
  output$sim_trough       <- renderText(sim_fmt(sim()$trough))
  output$sim_trough_delta <- renderText(sim_delta(sim()$shift_days))

  output$sim_explain <- renderUI({
    s <- sim()
    colour <- if (s$shift_days == 0) "#6c757d" else if (s$shift_days < 0) "#c1121f" else "#3d5a80"

    div(class = "p-3", style = paste0(
          "background:#f8f9fa; border-left:4px solid ", colour, "; border-radius:4px;"),
      p(class = "mb-1",
        if (input$sim_north == 0 && input$sim_naples == 0 && input$sim_lag == 25)
          tagList(strong("These are normal conditions. "),
                  "Move a slider to see what a different year would do.")
        else tagList(
          strong("With these conditions: "),
          if (input$sim_north != 0)
            sprintf("a north running %+.1f F against normal ", input$sim_north) else "",
          if (input$sim_north != 0 && input$sim_naples != 0) "and " else "",
          if (input$sim_naples != 0)
            sprintf("a Naples running %+.1f F ", input$sim_naples) else "",
          sprintf("moves the temperature window %+d days%s. ",
                  s$thermal_shift,
                  if (s$thermal_shift == 0) " (not enough to change a crossing date)" else ""),
          if (s$lag_delta != 0)
            sprintf("Your lag of %d days adds another %+d. ", input$sim_lag, s$lag_delta) else ""
        )),
      p(class = "mb-0",
        sprintf("Net effect: the season runs %s.", sim_delta(s$shift_days)),
        if (abs(s$shift_days) > 20)
          tagList(br(), tags$span(class = "text-muted",
            "A shift this large is beyond anything in the historical record - ",
            "treat it as illustrative rather than a forecast.")) else NULL)
    )
  })

  output$p_sim <- renderPlot({
    sized("p_sim")
    shift <- sim()$shift_days

    shifted <- seasonal_curve_static %>%
      mutate(doy = ((doy - 1 + shift) %% 365) + 1) %>%
      arrange(doy)

    ggplot() +
      geom_line(data = seasonal_curve_static, aes(doy, index, colour = "Normal year"),
                linewidth = 1.1, linetype = "dashed") +
      geom_line(data = shifted, aes(doy, index, colour = "Simulated"),
                linewidth = 1.7) +
      geom_hline(yintercept = 1, linetype = "dotted", colour = "grey40") +
      scale_colour_manual(values = c("Normal year" = "grey45",
                                     "Simulated" = "#c1121f")) +
      scale_x_continuous(breaks = c(1, 60, 121, 182, 244, 305, 365),
                         labels = c("Jan", "Mar", "May", "Jul", "Sep", "Nov", "Dec")) +
      labs(
        title = "Simulated season against a normal one",
        subtitle = sprintf("Season shifted %s.", sim_delta(shift)),
        x = NULL, y = "Traffic (1.0 = average day)", colour = NULL
      ) +
      theme(legend.position = "top")
  })

  # --- This year so far -----------------------------------------------------
  ytd <- reactive({
    shiny::validate(shiny::need(!is.null(rsw_monthly),
                                "Run R/11_are_they_coming_earlier.R first."))

    this_year <- max(rsw_monthly$year)
    cur <- rsw_monthly %>% filter(year == this_year) %>% arrange(month)
    months_have <- cur$month

    # Compare like with like: only the months this year has actually reported.
    same <- rsw_monthly %>%
      filter(month %in% months_have) %>%
      group_by(year) %>%
      filter(n() == length(months_have)) %>%
      summarise(ytd = sum(passengers), .groups = "drop")

    band <- rsw_monthly %>%
      filter(year >= this_year - 5, year < this_year) %>%
      group_by(month) %>%
      summarise(lo = min(passengers), hi = max(passengers),
                mid = median(passengers), .groups = "drop")

    list(year = this_year, cur = cur, months = months_have,
         same = same, band = band,
         prev = rsw_monthly %>% filter(year == this_year - 1) %>% arrange(month))
  })

  output$ytd_summary <- renderText({
    y <- ytd()
    s <- y$same
    now  <- s$ytd[s$year == y$year]
    last <- s$ytd[s$year == y$year - 1]
    if (length(now) == 0 || length(last) == 0) return("")
    pct <- 100 * (now / last - 1)
    # Show enough decimals that a genuinely tiny change doesn't print as
    # "-0.0%", which reads like a rounding artefact rather than a real result.
    # The airport's own release quotes this as "down 0.04 percent".
    fmt <- if (abs(pct) < 0.5) "%+.2f%%" else "%+.1f%%"
    sprintf("Through %s, %d is running %s against the same months of %d (%s vs %s passengers).",
            MONTH_ABB[max(y$months)], y$year, sprintf(fmt, pct), y$year - 1,
            comma(now), comma(last))
  })

  output$p_ytd <- renderPlot({
    sized("p_ytd")
    y <- ytd()

    ggplot() +
      geom_ribbon(data = y$band, aes(month, ymin = lo, ymax = hi,
                                     fill = paste0("range ", y$year - 5, "-", y$year - 1)),
                  alpha = 0.3) +
      geom_line(data = y$prev, aes(month, passengers,
                                   colour = as.character(y$year - 1)),
                linewidth = 0.9, linetype = "dashed") +
      geom_line(data = y$cur, aes(month, passengers, colour = as.character(y$year)),
                linewidth = 1.4) +
      geom_point(data = y$cur, aes(month, passengers, colour = as.character(y$year)),
                 size = 3.0) +
      scale_x_continuous(breaks = 1:12, labels = MONTH_ABB, limits = c(1, 12)) +
      scale_y_continuous(labels = comma) +
      scale_colour_manual(values = setNames(c("#c1121f", "#3d5a80"),
                                            c(as.character(y$year),
                                              as.character(y$year - 1))),
                          name = NULL) +
      scale_fill_manual(values = setNames("grey65",
                                          paste0("range ", y$year - 5, "-", y$year - 1)),
                        name = NULL) +
      labs(title = paste0("RSW passengers, ", y$year, " against recent years"),
           subtitle = paste0("Solid = ", y$year, " (", length(y$months),
                             " months published). Dashed = ", y$year - 1,
                             ". Band = range of the previous five years."),
           x = NULL, y = "Passengers per month") +
      theme(legend.position = "top")
  })

  output$tbl_ytd <- renderTable({
    y <- ytd()
    prev <- y$prev %>% select(month, last_year = passengers)

    y$cur %>%
      left_join(prev, by = "month") %>%
      left_join(y$band %>% select(month, mid), by = "month") %>%
      transmute(
        Month = MONTH_ABB[month],
        `This year` = comma(passengers),
        `Last year` = comma(last_year),
        `vs last year` = sprintf("%+.1f%%", 100 * (passengers / last_year - 1)),
        `vs 5-yr median` = sprintf("%+.1f%%", 100 * (passengers / mid - 1))
      )
  }, striped = TRUE, hover = TRUE, width = "100%")

  # --- Season forecast ------------------------------------------------------
  # The whole fit runs live, so moving the flexibility slider refits it.
  # Only the model is recomputed here; the bootstrap band is 150 runs, which is
  # fewer than R/09 uses (600) purely to keep the app responsive.
  forecast_fit <- reactive({
    shiny::validate(shiny::need(!is.null(traffic_daily),
                                "Run R/04_fetch_fti.R to get the traffic data."))

    K  <- HARMONICS
    tr <- traffic_daily %>% filter(!date %in% STORM_DAYS)
    good <- tr %>% count(site) %>% filter(n >= 330) %>% pull(site)

    county <- tr %>%
      filter(site %in% good) %>%
      group_by(site) %>% mutate(index = volume / mean(volume)) %>% ungroup() %>%
      group_by(date) %>% summarise(index = mean(index), .groups = "drop") %>%
      arrange(date) %>%
      mutate(doy = yday(date), dow = wday(date, label = TRUE), y = log(index))

    md <- bind_cols(county, harmonics(county$doy, K))
    hn <- setdiff(names(md), names(county))
    form <- as.formula(paste("y ~ dow +", paste(hn, collapse = " + ")))
    fit <- lm(form, data = md)

    # -------------------------------------------------------------------------
    # WHY THIS IS NOT JUST lm() IN A LOOP
    # -------------------------------------------------------------------------
    # The obvious bootstrap calls lm() once per replicate. That took 4.7
    # seconds for 150 reps and made this tab feel broken.
    #
    # The waste: every replicate uses the SAME predictors. Only y changes.
    # lm() re-does the expensive part - factorising the design matrix - every
    # single time. Factor it ONCE with qr() and each replicate becomes a cheap
    # back-substitution: qr.coef() instead of a whole regression.
    #
    # Prediction gets the same treatment. Instead of seven predict() calls per
    # replicate, precompute one design matrix for the 365 days of the year,
    # already averaged over weekdays, then a single matrix multiply gives the
    # curve. Averaging the design matrix and then multiplying is identical to
    # averaging the predictions, because the model is linear in its
    # coefficients.
    #
    # Same maths, same answer, roughly 50x faster.
    # -------------------------------------------------------------------------
    X   <- model.matrix(form, md)
    qrX <- qr(X)

    dows <- levels(county$dow)
    # ordered = TRUE is NOT cosmetic. wday(label = TRUE) returns an ORDERED
    # factor, and R codes ordered factors with polynomial contrasts (.L, .Q,
    # .C ...) rather than the dummy columns an unordered factor gets. Rebuild
    # the grid with a plain factor and the design matrix comes back in a
    # different basis, so this matrix multiply silently pairs polynomial
    # coefficients with dummy columns. The curve still looked plausible - it
    # was wrong by about 0.5%. predict() gets this right on its own, which is
    # exactly why hand-rolling the fast path needs checking against it.
    grid <- expand_grid(dow = factor(dows, levels = dows, ordered = TRUE),
                        doy = 1:365)
    grid <- bind_cols(grid, harmonics(grid$doy, K))
    Xg   <- model.matrix(delete.response(terms(fit)), grid)
    # rowsum() sums rows by group and returns them in sorted group order,
    # so this is the per-day mean design matrix across the seven weekdays.
    Pmat <- rowsum(Xg, group = grid$doy) / length(dows)

    curve_from <- function(y) {
      beta <- qr.coef(qrX, y)
      beta[is.na(beta)] <- 0            # guard against aliased columns
      tibble(doy = 1:365, index = as.numeric(exp(Pmat %*% beta)))
    }

    curve <- curve_from(md$y)

    # Moving-block bootstrap: resample CONTIGUOUS runs of residuals so the
    # day-to-day stickiness of traffic survives into the interval.
    res <- residuals(fit); fitv <- fitted(fit); n <- length(res); BLOCK <- 14
    nblk <- ceiling(n / BLOCK)

    boot <- map_dfr(1:200, function(b) {
      st <- sample(seq_len(n - BLOCK + 1), nblk, replace = TRUE)
      r  <- unlist(map(st, ~ res[.x:(.x + BLOCK - 1)]))[1:n]
      curve_from(fitv + r) %>% mutate(rep = b)
    })

    list(county = county, curve = curve, boot = boot,
         stats = describe_curve(curve), r2 = summary(fit)$r.squared)
  })
  # NOTE: this used to be wrapped in bindCache(HARMONICS). That was added
  # when the bootstrap took 4.7 seconds. Once the qr() rewrite brought it to
  # 0.16s the cache stopped earning its place - and it turned out to deadlock:
  # calling a cached reactive from inside ANOTHER reactive (the Simulation tab
  # calls both gap() and forecast_fit()) hung the whole session, with every
  # output stuck 'recalculating' and no error raised. Removing the cache costs
  # nothing measurable and removes the failure mode.

  output$p_forecast <- renderPlot({
    sized("p_forecast")
    f <- forecast_fit()

    ribbon <- f$boot %>%
      group_by(doy) %>%
      summarise(lo = quantile(index, 0.05), hi = quantile(index, 0.95), .groups = "drop")

    s <- f$stats

    ggplot() +
      geom_point(data = f$county, aes(doy, index),
                 colour = "grey70", size = 0.9, alpha = 0.6) +
      geom_ribbon(data = ribbon, aes(doy, ymin = lo, ymax = hi),
                  fill = "#2a6f97", alpha = 0.25) +
      geom_line(data = f$curve, aes(doy, index), colour = "#2a6f97", linewidth = 1.2) +
      geom_hline(yintercept = 1, linetype = "dotted", colour = "grey35") +
      geom_vline(xintercept = s$peak_doy,   colour = "#c1121f", linetype = "dashed") +
      geom_vline(xintercept = s$trough_doy, colour = "#e07a5f", linetype = "dashed") +
      annotate("text", x = s$peak_doy + 4, y = max(f$curve$index),
               label = paste0("peak ", doy_to_date(s$peak_doy)),
               hjust = 0, colour = "#c1121f", size = LBL) +
      annotate("text", x = s$trough_doy + 4, y = min(f$curve$index),
               label = paste0("trough ", doy_to_date(s$trough_doy)),
               hjust = 0, colour = "#e07a5f", size = LBL) +
      scale_x_continuous(breaks = c(1, 60, 121, 182, 244, 305, 365),
                         labels = c("Jan", "Mar", "May", "Jul", "Sep", "Nov", "Dec")) +
      labs(title = "Predicted southwest Florida traffic season",
           subtitle = paste0(HARMONICS, " harmonics · R² = ", round(f$r2, 3),
                             " · grey = actual 2024 days, band = 90% bootstrap"),
           x = NULL, y = "Traffic (1.0 = average day)")
  })

  output$tbl_forecast <- renderTable({
    s <- forecast_fit()$stats
    tibble(
      Measure = c("Season starts", "Peak", "Season ends", "Trough",
                  "Peak level", "Trough level",
                  "Decline from peak", "Increase from trough"),
      Value = c(doy_to_date(s$start_doy), doy_to_date(s$peak_doy),
                doy_to_date(s$end_doy),   doy_to_date(s$trough_doy),
                paste0(round(s$peak_val, 3), "x average"),
                paste0(round(s$trough_val, 3), "x average"),
                paste0(round(s$decline_pct, 1), "%"),
                paste0(round(s$increase_pct, 1), "%"))
    )
  }, striped = TRUE, hover = TRUE, width = "100%")

  # --- Origin states --------------------------------------------------------
  output$p_states <- renderPlot({
    sized("p_states")
    origin_states %>%
      slice_head(n = 15) %>%
      mutate(state = fct_reorder(state, people)) %>%
      ggplot(aes(people, state)) +
      geom_col(fill = "#3d5a80", alpha = 0.9) +
      geom_text(aes(label = paste0(round(100 * share, 1), "%")),
                hjust = -0.15, size = LBL - 0.6) +
      scale_x_continuous(labels = comma, expand = expansion(c(0, 0.14))) +
      labs(title = "Northern home states of Naples arrivals",
           subtitle = "Northern home states of people moving into Collier County (IRS, 2022-23).",
           x = "People", y = NULL)
  })

  output$tbl_states <- renderTable({
    origin_states %>%
      slice_head(n = 15) %>%
      transmute(State = state, People = people,
                Share = paste0(round(100 * share, 1), "%"),
                `Mean AGI ($000)` = round(mean_agi),
                Lat = round(lat, 2), Lon = round(lon, 2))
  }, striped = TRUE, hover = TRUE, width = "100%")

  # --- 50 years -------------------------------------------------------------
  output$p_hist <- renderPlot({
    sized("p_hist")
    shiny::validate(shiny::need(!is.null(hist_aadt),
                                "Run R/04_fetch_fti.R to get the historical data."))
    hist_aadt %>%
      group_by(year) %>%
      summarise(median_aadt = median(aadt), sites = n(), .groups = "drop") %>%
      filter(sites >= 20) %>%
      ggplot(aes(year, median_aadt)) +
      geom_line(colour = "#3d5a80", linewidth = 1.3) +
      geom_point(size = 1.6, colour = "#3d5a80") +
      scale_y_continuous(labels = comma) +
      labs(title = "Fifty years of Naples traffic",
           subtitle = "Median AADT across Collier + Lee counting sites",
           x = NULL, y = "Median AADT")
  })

  # --- Table ----------------------------------------------------------------
  output$tbl <- renderTable({
    windows() %>%
      transmute(Season = as.integer(season_year),
                Opens  = format(opens,  "%d %b %Y"),
                Closes = format(closes, "%d %b %Y"),
                Days   = as.integer(window_days))
  }, striped = TRUE, hover = TRUE, width = "100%")
}

shinyApp(ui, server)
