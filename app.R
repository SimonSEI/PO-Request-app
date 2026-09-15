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
# the chart". You write "this chart depends on input$threshold" and Shiny works
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

theme_set(theme_minimal(base_size = 12))

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

all_states <- state_temps %>%
  distinct(state, people) %>%
  arrange(desc(people)) %>%
  pull(state)

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

# Daily temperature gap: Naples minus the chosen origin states.
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
ui <- page_sidebar(

  title = "Naples Snowbird Migration",

  # Layout note, learned the hard way.
  # fillable = FALSE looked like the fix for bslib squeezing plots flat, but it
  # made the plot element 440px tall and ZERO pixels WIDE inside the flex
  # layout - a different flavour of the same problem. Leaving fillable at its
  # default and giving the tab card an explicit height gives plots a real size
  # in both directions. The sized() guard in server() handles the brief moment
  # before the browser has measured anything.

  theme = bs_theme(bootswatch = "flatly",
                   base_font = font_google("Inter", local = FALSE)),

  sidebar = sidebar(
    width = 340,

    h5("Attack the assumptions"),
    p(class = "text-muted small",
      "Every control here was a judgement call in the original analysis.",
      "If a finding survives you moving them, it might be real."),

    sliderInput("threshold", "Migration threshold (°F warmer than home)",
                min = 10, max = 40, value = 25, step = 1),

    radioButtons(
      "weighting", "How to combine origin states",
      choices = c("Weighted by migrants sent" = "weighted",
                  "All states counted equally" = "equal"),
      selected = "weighted"
    ),
    p(class = "text-muted small",
      "Weights come from IRS records of who actually moved to Collier County."),

    hr(),

    sliderInput("harmonics", "Seasonal curve flexibility",
                min = 1, max = 8, value = 4, step = 1),
    p(class = "text-muted small",
      "Used by the Season forecast tab. 1 is a single smooth wave; 8 chases",
      "individual weeks. Watch the fit go from too stiff to overfitted."),

    hr(),

    checkboxGroupInput("states", "Origin states",
                       choices = all_states, selected = all_states),
    actionLink("all_on", "all"), " / ", actionLink("all_off", "none"),

    hr(),
    p(class = "text-muted small",
      strong("Caveats: "),
      "IRS data tracks permanent address changes, not seasonal stays - ",
      "many snowbirds keep their northern domicile. Canadians are missing ",
      "entirely. 2020-21 is distorted by COVID.")
  ),

  # The headline is the FORECAST, not the temperature trend. The temperature
  # trend turned out not to survive a threshold sweep (see the Robustness tab),
  # so it has no business being the first thing anyone reads. These four are
  # the numbers you would actually act on.
  layout_columns(
    fill = FALSE,
    value_box(title = "Next trough",  value = textOutput("vb_trough"),
              showcase = icon("arrow-trend-down"), theme = "secondary",
              textOutput("vb_trough_sub")),
    value_box(title = "Season starts", value = textOutput("vb_start"),
              showcase = icon("arrow-right-to-bracket"), theme = "info",
              textOutput("vb_start_sub")),
    value_box(title = "Next peak",    value = textOutput("vb_peak"),
              showcase = icon("arrow-trend-up"), theme = "primary",
              textOutput("vb_peak_sub")),
    value_box(title = "Peak vs trough", value = textOutput("vb_swing"),
              showcase = icon("arrows-up-down"), theme = "success",
              textOutput("vb_swing_sub"))
  ),

  # card_body(fillable = FALSE) per panel is what finally made the plots the
  # size they are told to be. bslib's default flex layout stretches content to
  # the card and ignores plotOutput(height=), which left a 440px chart drawn
  # into about 90 pixels. Turning fill OFF at the PANEL level (rather than at
  # the page level, which collapsed the width to zero) respects explicit
  # heights and keeps the full width. The panel then scrolls if it needs to.
  navset_card_tab(

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
            tags$li("Traffic: daily counts from Collier County's continuous",
                    "counting stations - machines in the road counting cars",
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
            "states people come from, across the year."),
          p(strong("In midwinter Naples runs about 40 degrees F warmer. "),
            "By July the difference nearly vanishes - a summer day in Michigan",
            "is much like a summer day in Florida, minus the humidity."),
          p(strong("Why it matters: "),
            "nobody moves south because Naples got warm. They move because",
            "home got cold. The red dashed line is your threshold - the point",
            "you've decided the difference is big enough to be worth the trip.")
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
      "Origin states",
      chart_panel(
        heading = "Where do Naples newcomers actually come from?",
        plain = tagList(
          p("Each bar is a US state, sized by how many people moved from there",
            "into Collier County. This is measured from tax records, not",
            "guessed."),
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
          p("Traffic on a typical Collier County road, every year back to 1970."),
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
            "Annual Average Daily Traffic for Collier County, 1970 to 2025."),
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
      "The numbers",
      chart_panel(
        heading = "The raw dates behind the charts",
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
  )
)

# =============================================================================
# SERVER
# =============================================================================
server <- function(input, output, session) {

  observeEvent(input$all_on,
               updateCheckboxGroupInput(session, "states", selected = all_states))
  observeEvent(input$all_off,
               updateCheckboxGroupInput(session, "states", selected = character(0)))

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
    shiny::validate(shiny::need(length(input$states) > 0, "Pick at least one state."))
    build_gap(input$states, input$weighting == "weighted")
  }) %>%
    bindCache(input$states, input$weighting)

  windows <- reactive(find_windows(gap(), input$threshold))

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

  nxt <- reactive({
    s <- forecast_fit()$stats
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
      geom_point(size = 2.3, alpha = 0.85) +
      geom_smooth(method = "lm", se = TRUE, linewidth = 1) +
      scale_colour_manual(values = c("#e07a5f", "#3d5a80")) +
      scale_y_continuous(breaks = c(92, 153, 214, 275, 336),
                         labels = c("1 Oct", "1 Dec", "1 Feb", "1 Apr", "1 Jun")) +
      labs(title = "When does the migration window open and close?",
           subtitle = paste0(input$threshold, "°F threshold · ",
                             length(input$states), " states"),
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
      geom_line(colour = "#2a6f97", linewidth = 1.1) +
      geom_hline(yintercept = input$threshold, linetype = "dashed",
                 colour = "#c1121f", linewidth = 0.8) +
      annotate("text", x = 183, y = input$threshold + 1.6,
               label = paste0("threshold: ", input$threshold, "°F"),
               colour = "#c1121f", hjust = 0, size = 4) +
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
      geom_point(aes(colour = sig), size = 2) +
      geom_vline(xintercept = input$threshold, linetype = "dotted",
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
      geom_line(aes(y = index_s, colour = "Traffic"), linewidth = 1.1) +
      geom_hline(yintercept = 1, linetype = "dotted", colour = "grey40") +
      scale_y_continuous(name = "Traffic (1.0 = average day)",
                         sec.axis = sec_axis(~ to_g(.), name = "Temperature gap (°F)")) +
      scale_x_date(date_labels = "%b", date_breaks = "1 month") +
      scale_colour_manual(values = c("Traffic" = "#c1121f",
                                     "Temperature gap" = "#2a6f97")) +
      labs(title = "Do snowbirds follow the thermometer?",
           subtitle = paste0("Collier County daily traffic vs the gap, 2024. ",
                             "Hurricanes removed. r = ", round(r, 2)),
           x = NULL, colour = NULL) +
      theme(legend.position = "top")
  })

  # --- Season forecast ------------------------------------------------------
  # The whole fit runs live, so moving the flexibility slider refits it.
  # Only the model is recomputed here; the bootstrap band is 150 runs, which is
  # fewer than R/09 uses (600) purely to keep the app responsive.
  forecast_fit <- reactive({
    shiny::validate(shiny::need(!is.null(traffic_daily),
                                "Run R/04_fetch_fti.R to get the traffic data."))

    K  <- input$harmonics
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
  }) %>%
    # bindCache stores the result against the slider value, so the eight
    # possible settings are each computed once per session and are instant
    # on every revisit.
    bindCache(input$harmonics)

  output$p_forecast <- renderPlot({
    sized("p_forecast")
    f <- forecast_fit()

    ribbon <- f$boot %>%
      group_by(doy) %>%
      summarise(lo = quantile(index, 0.05), hi = quantile(index, 0.95), .groups = "drop")

    s <- f$stats

    ggplot() +
      geom_point(data = f$county, aes(doy, index),
                 colour = "grey70", size = 0.7, alpha = 0.6) +
      geom_ribbon(data = ribbon, aes(doy, ymin = lo, ymax = hi),
                  fill = "#2a6f97", alpha = 0.25) +
      geom_line(data = f$curve, aes(doy, index), colour = "#2a6f97", linewidth = 1.2) +
      geom_hline(yintercept = 1, linetype = "dotted", colour = "grey35") +
      geom_vline(xintercept = s$peak_doy,   colour = "#c1121f", linetype = "dashed") +
      geom_vline(xintercept = s$trough_doy, colour = "#e07a5f", linetype = "dashed") +
      annotate("text", x = s$peak_doy + 4, y = max(f$curve$index),
               label = paste0("peak ", doy_to_date(s$peak_doy)),
               hjust = 0, colour = "#c1121f", size = 4) +
      annotate("text", x = s$trough_doy + 4, y = min(f$curve$index),
               label = paste0("trough ", doy_to_date(s$trough_doy)),
               hjust = 0, colour = "#e07a5f", size = 4) +
      scale_x_continuous(breaks = c(1, 60, 121, 182, 244, 305, 365),
                         labels = c("Jan", "Mar", "May", "Jul", "Sep", "Nov", "Dec")) +
      labs(title = "Predicted Naples traffic season",
           subtitle = paste0(input$harmonics, " harmonics · R² = ", round(f$r2, 3),
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
      mutate(state = fct_reorder(state, people),
             picked = state %in% input$states) %>%
      ggplot(aes(people, state, fill = picked)) +
      geom_col(alpha = 0.9) +
      geom_text(aes(label = paste0(round(100 * share, 1), "%")),
                hjust = -0.15, size = 3.4) +
      scale_fill_manual(values = c("TRUE" = "#3d5a80", "FALSE" = "grey80"),
                        guide = "none") +
      scale_x_continuous(labels = comma, expand = expansion(c(0, 0.14))) +
      labs(title = "Where Naples newcomers come from",
           subtitle = "People moving into Collier County from out of state (IRS, 2022-23). Grey = excluded.",
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
      geom_line(colour = "#3d5a80", linewidth = 1.1) +
      geom_point(size = 1.6, colour = "#3d5a80") +
      scale_y_continuous(labels = comma) +
      labs(title = "Fifty years of Naples traffic",
           subtitle = "Median AADT across Collier County counting sites",
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
