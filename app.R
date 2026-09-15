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
library(tidyverse)
library(lubridate)
library(scales)

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

  layout_columns(
    fill = FALSE,
    value_box(title = "Season opens, per decade", value = textOutput("vb_opens"),
              showcase = icon("arrow-right-to-bracket"), theme = "primary",
              textOutput("vb_opens_p")),
    value_box(title = "Season closes, per decade", value = textOutput("vb_closes"),
              showcase = icon("arrow-right-from-bracket"), theme = "secondary",
              textOutput("vb_closes_p")),
    value_box(title = "Window length, per decade", value = textOutput("vb_len"),
              showcase = icon("arrows-left-right"), theme = "info",
              textOutput("vb_len_p"))
  ),

  # card_body(fillable = FALSE) per panel is what finally made the plots the
  # size they are told to be. bslib's default flex layout stretches content to
  # the card and ignores plotOutput(height=), which left a 440px chart drawn
  # into about 90 pixels. Turning fill OFF at the PANEL level (rather than at
  # the page level, which collapsed the width to zero) respects explicit
  # heights and keeps the full width. The panel then scrolls if it needs to.
  navset_card_tab(
    nav_panel("Window shift",
              card_body(fillable = FALSE,
                        plotOutput("p_shift", height = "460px"))),
    nav_panel("Shape of a year",
              card_body(fillable = FALSE,
                        plotOutput("p_year", height = "460px"))),
    nav_panel("Robustness",
              card_body(fillable = FALSE,
                        p(class = "text-muted small",
                          "The single most important chart here. It refits the trend at",
                          "every plausible threshold. If red points appear only in a",
                          "narrow band, the 'finding' is an artefact of where the line",
                          "was drawn."),
                        plotOutput("p_sweep", height = "620px"))),
    nav_panel("Season forecast",
              card_body(fillable = FALSE,
                        p(class = "text-muted small",
                          "Harmonic regression on 2024 daily counts, with a",
                          "moving-block bootstrap for the band. These intervals say",
                          "how precisely we know 2024 - NOT how much the season moves",
                          "between years, which one year of data cannot tell us."),
                        plotOutput("p_forecast", height = "440px"),
                        tableOutput("tbl_forecast"))),
    nav_panel("Traffic vs temperature",
              card_body(fillable = FALSE,
                        plotOutput("p_traffic", height = "460px"))),
    nav_panel("Origin states",
              card_body(fillable = FALSE,
                        plotOutput("p_states", height = "420px"),
                        tableOutput("tbl_states"))),
    nav_panel("50 years",
              card_body(fillable = FALSE,
                        plotOutput("p_hist", height = "460px"))),
    nav_panel("The numbers",
              card_body(fillable = FALSE, tableOutput("tbl")))
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
  })

  windows <- reactive(find_windows(gap(), input$threshold))

  t_opens  <- reactive(trend_of(windows(), "opens_d"))
  t_closes <- reactive(trend_of(windows(), "closes_d"))
  t_len    <- reactive(trend_of(windows(), "window_days"))

  fmt <- function(x) if (is.na(x)) "-" else sprintf("%+.1f days", x)

  output$vb_opens    <- renderText(fmt(t_opens()$per_decade))
  output$vb_opens_p  <- renderText(t_opens()$label)
  output$vb_closes   <- renderText(fmt(t_closes()$per_decade))
  output$vb_closes_p <- renderText(t_closes()$label)
  output$vb_len      <- renderText(fmt(t_len()$per_decade))
  output$vb_len_p    <- renderText(t_len()$label)

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

    dows <- levels(county$dow)
    curve_of <- function(model) {
      grid <- tibble(doy = 1:365) %>% bind_cols(harmonics(1:365, K))
      preds <- map_dfc(dows, function(d) {
        tibble(!!d := predict(model, newdata = mutate(grid, dow = factor(d, levels = dows))))
      })
      tibble(doy = 1:365, index = exp(rowMeans(as.matrix(preds))))
    }

    curve <- curve_of(fit)

    # Moving-block bootstrap: resample CONTIGUOUS runs of residuals so the
    # day-to-day stickiness of traffic survives into the interval.
    res <- residuals(fit); fitv <- fitted(fit); n <- length(res); BLOCK <- 14
    boot <- map_dfr(1:150, function(b) {
      st <- sample(seq_len(n - BLOCK + 1), ceiling(n / BLOCK), replace = TRUE)
      r  <- unlist(map(st, ~ res[.x:(.x + BLOCK - 1)]))[1:n]
      d  <- md; d$y <- fitv + r
      f  <- try(lm(form, data = d), silent = TRUE)
      if (inherits(f, "try-error")) return(NULL)
      curve_of(f) %>% mutate(rep = b)
    })

    list(county = county, curve = curve, boot = boot,
         stats = describe_curve(curve), r2 = summary(fit)$r.squared)
  })

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
