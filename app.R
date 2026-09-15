# =============================================================================
# THE NAPLES SNOWBIRD DASHBOARD
# =============================================================================
# A Shiny app. Shiny turns an R script into a web page with working controls.
#
# Every Shiny app has exactly three parts:
#   ui     - what it looks like (the controls and where output goes)
#   server - what it does (recalculates when a control moves)
#   shinyApp(ui, server) - glues them together and runs it
#
# The magic word is REACTIVE. You never write "when the slider moves, redraw
# the chart". You write "this chart depends on input$threshold" and Shiny
# works out what to redraw. Everything downstream updates on its own.
#
# The two controls here are deliberate: the threshold and the choice of origin
# cities were the two weakest assumptions in the analysis. Now you can attack
# them directly instead of taking my word for it.
# =============================================================================

library(shiny)
library(bslib)
library(tidyverse)
library(lubridate)

theme_set(theme_minimal(base_size = 13))

# -----------------------------------------------------------------------------
# Load data ONCE, when the app starts - not on every click.
# Code outside server() runs a single time. Code inside runs constantly.
# Getting this wrong is the classic Shiny performance mistake.
# -----------------------------------------------------------------------------
weather <- read_csv("data/weather_daily.csv", show_col_types = FALSE)

north_cities <- weather %>%
  filter(role == "north") %>%
  distinct(city) %>%
  arrange(city) %>%
  pull(city)

aadt <- if (file.exists("data/collier_aadt.csv")) {
  read_csv("data/collier_aadt.csv", show_col_types = FALSE)
} else {
  NULL
}

# -----------------------------------------------------------------------------
# The analysis, as a plain function
# -----------------------------------------------------------------------------
# Note this is ordinary R - nothing Shiny-specific. Keeping your real logic in
# plain functions means you can test it at the console, and the app just calls
# it. Do not bury your analysis inside server().
compute_windows <- function(chosen_cities, threshold) {

  gap <- weather %>%
    filter(role == "south" | city %in% chosen_cities) %>%
    group_by(date, role) %>%
    summarise(temp = mean(temp_mean, na.rm = TRUE), .groups = "drop") %>%
    pivot_wider(names_from = role, values_from = temp) %>%
    arrange(date) %>%
    mutate(
      gap        = south - north,
      gap_smooth = as.numeric(stats::filter(gap, rep(1/7, 7), sides = 2)),
      season_year = if_else(month(date) >= 7, year(date), year(date) - 1L)
    )

  first_crossing <- function(dates, g, months_in, want_above) {
    hit <- if (want_above) g >= threshold else g < threshold
    ok  <- hit & (month(dates) %in% months_in)
    if (!any(ok, na.rm = TRUE)) return(as.Date(NA))
    min(dates[which(ok)])
  }

  windows <- gap %>%
    filter(!is.na(gap_smooth)) %>%
    group_by(season_year) %>%
    summarise(
      opens  = first_crossing(date, gap_smooth, 9:12, TRUE),
      closes = first_crossing(date, gap_smooth, 3:6,  FALSE),
      .groups = "drop"
    ) %>%
    mutate(window_days = as.numeric(closes - opens)) %>%
    filter(!is.na(opens), !is.na(closes))

  list(gap = gap, windows = windows)
}

# Fit a trend and report it in plain English rather than regression jargon.
trend_of <- function(df, column) {
  if (nrow(df) < 5) return(list(per_decade = NA, p = NA, label = "not enough data"))

  df$y <- df[[column]]
  fit  <- lm(y ~ season_year, data = df)
  co   <- summary(fit)$coefficients

  slope <- co["season_year", "Estimate"] * 10   # per decade reads better
  p     <- co["season_year", "Pr(>|t|)"]

  list(
    per_decade = slope,
    p          = p,
    label      = if (is.na(p)) "-"
                 else if (p < 0.01)  "strong evidence"
                 else if (p < 0.05)  "some evidence"
                 else if (p < 0.10)  "weak, could be noise"
                 else                "no real evidence"
  )
}

# =============================================================================
# UI
# =============================================================================
ui <- page_sidebar(

  title = "Naples Snowbird Migration",

  # fillable = FALSE is load-bearing, not cosmetic.
  # By default bslib squeezes everything to fit the window height, which
  # overrode our plotOutput(height = "460px") and left the chart 272px tall.
  # Worse, on first load the height can momentarily be near zero, and Shiny
  # renders the plot BEFORE the layout settles - giving
  #     Error in graphics::plot.new: figure margins too large
  # which then sticks, because nothing re-triggers the render.
  # (Resizing the window "fixed" it, which is what made this confusing.)
  # FALSE means: respect explicit heights and let the page scroll.
  fillable = FALSE,
  # local = FALSE serves the font from Google's CDN rather than downloading it
  # into the container at startup. One less thing to fail in a fresh deploy.
  theme = bs_theme(bootswatch = "flatly",
                   base_font = font_google("Inter", local = FALSE)),

  sidebar = sidebar(
    width = 330,

    h5("Attack the assumptions"),
    p(class = "text-muted small",
      "Both controls below were guesses in the original analysis. If the",
      "finding survives you moving them, it might be real."),

    sliderInput(
      "threshold",
      "Migration threshold (°F warmer than home)",
      min = 10, max = 40, value = 25, step = 1
    ),
    p(class = "text-muted small",
      "How much warmer Naples must be before the trip is 'worth it'."),

    hr(),

    checkboxGroupInput(
      "cities", "Where the snowbirds come from",
      choices  = north_cities,
      selected = north_cities
    ),
    p(class = "text-muted small",
      "Naples skews wealthier and more Midwestern than Florida overall.",
      "Drop the coastal cities and see what changes."),

    hr(),
    p(class = "text-muted small",
      strong("Note: "), "2020-21 is contaminated by COVID. Any trend through",
      "those years is partly measuring a pandemic.")
  ),

  layout_columns(
    fill = FALSE,
    value_box(
      title = "Season opens, per decade",
      value = textOutput("vb_opens"),
      showcase = icon("arrow-right-to-bracket"),
      theme = "primary",
      textOutput("vb_opens_p")
    ),
    value_box(
      title = "Season closes, per decade",
      value = textOutput("vb_closes"),
      showcase = icon("arrow-right-from-bracket"),
      theme = "secondary",
      textOutput("vb_closes_p")
    ),
    value_box(
      title = "Window length, per decade",
      value = textOutput("vb_len"),
      showcase = icon("arrows-left-right"),
      theme = "info",
      textOutput("vb_len_p")
    )
  ),

  navset_card_tab(
    nav_panel("Window shift",   plotOutput("p_shift",  height = "460px")),
    nav_panel("Shape of a year", plotOutput("p_year",   height = "460px")),
    nav_panel("Season length",  plotOutput("p_len",    height = "460px")),
    nav_panel("Traffic",        plotOutput("p_aadt",   height = "460px")),
    nav_panel("The numbers",    tableOutput("tbl"))
  )
)

# =============================================================================
# SERVER
# =============================================================================
server <- function(input, output, session) {

  # reactive() = "recompute this whenever its inputs change, but only once
  # per change, and only if something actually needs the answer."
  # Every output below shares this ONE computation rather than repeating it.
  # NAMESPACE COLLISION, the sequel:
  # jsonlite also exports a validate(), and if it loads after shiny it wins.
  # You then get the baffling error "is.character(txt) is not TRUE", because
  # jsonlite::validate() expects a JSON string, not a Shiny condition.
  # Writing shiny::validate() in full makes the app immune to load order.
  # Same lesson as stats::filter() in script 03: when two packages export the
  # same name, be explicit.
  res <- reactive({
    shiny::validate(shiny::need(length(input$cities) > 0,
                                "Pick at least one northern city."))
    compute_windows(input$cities, input$threshold)
  })

  windows <- reactive(res()$windows)

  # --- The three headline numbers -------------------------------------------
  t_opens  <- reactive({
    w <- windows()
    trend_of(mutate(w, v = as.numeric(opens - make_date(season_year, 7, 1))), "v")
  })
  t_closes <- reactive({
    w <- windows()
    trend_of(mutate(w, v = as.numeric(closes - make_date(season_year, 7, 1))), "v")
  })
  t_len    <- reactive(trend_of(windows(), "window_days"))

  fmt_days <- function(x) {
    if (is.na(x)) return("-")
    sprintf("%+.1f days", x)   # "per decade" lives in the title, so it fits
  }

  output$vb_opens    <- renderText(fmt_days(t_opens()$per_decade))
  output$vb_opens_p  <- renderText(t_opens()$label)
  output$vb_closes   <- renderText(fmt_days(t_closes()$per_decade))
  output$vb_closes_p <- renderText(t_closes()$label)
  output$vb_len      <- renderText(fmt_days(t_len()$per_decade))
  output$vb_len_p    <- renderText(t_len()$label)

  # --- Chart: has the window moved? -----------------------------------------
  output$p_shift <- renderPlot({
    windows() %>%
      select(season_year, opens, closes) %>%
      pivot_longer(c(opens, closes), names_to = "edge", values_to = "date") %>%
      mutate(
        days_from_july = as.numeric(date - make_date(season_year, 7, 1)),
        edge = factor(edge, levels = c("opens", "closes"),
                      labels = c("Opens (autumn)", "Closes (spring)"))
      ) %>%
      ggplot(aes(season_year, days_from_july, colour = edge)) +
      geom_point(size = 2.4, alpha = 0.85) +
      geom_smooth(method = "lm", se = TRUE, linewidth = 1) +
      scale_colour_manual(values = c("#e07a5f", "#3d5a80")) +
      scale_y_continuous(
        breaks = c(92, 153, 214, 275, 336),
        labels = c("1 Oct", "1 Dec", "1 Feb", "1 Apr", "1 Jun")
      ) +
      labs(
        title = "When does the migration window open and close?",
        subtitle = paste0("Threshold ", input$threshold, "°F · ",
                          length(input$cities), " origin cities"),
        x = "Season (year it began)", y = NULL, colour = NULL
      ) +
      theme(legend.position = "top")
  })

  # --- Chart: the average shape of a year -----------------------------------
  output$p_year <- renderPlot({
    res()$gap %>%
      filter(!is.na(gap_smooth)) %>%
      mutate(doy = yday(date)) %>%
      group_by(doy) %>%
      summarise(gap = mean(gap_smooth), .groups = "drop") %>%
      ggplot(aes(doy, gap)) +
      geom_area(fill = "#2a6f97", alpha = 0.15) +
      geom_line(colour = "#2a6f97", linewidth = 1.1) +
      geom_hline(yintercept = input$threshold, linetype = "dashed",
                 colour = "#c1121f", linewidth = 0.8) +
      annotate("text", x = 183, y = input$threshold + 1.8,
               label = paste0("threshold: ", input$threshold, "°F"),
               colour = "#c1121f", hjust = 0, size = 4) +
      scale_x_continuous(breaks = c(1, 60, 121, 182, 244, 305),
                         labels = c("Jan", "Mar", "May", "Jul", "Sep", "Nov")) +
      labs(title = "How much warmer is Naples than back home?",
           subtitle = "Averaged across 2000-2026",
           x = NULL, y = "Temperature gap (°F)")
  })

  # --- Chart: season length --------------------------------------------------
  output$p_len <- renderPlot({
    ggplot(windows(), aes(season_year, window_days)) +
      geom_col(fill = "#3d5a80", alpha = 0.85) +
      geom_smooth(method = "lm", se = FALSE, colour = "#e07a5f", linewidth = 1.1) +
      labs(title = "Length of the thermal snowbird season",
           subtitle = "Days per year Naples is meaningfully warmer than home",
           x = "Season (year it began)", y = "Days")
  })

  # --- Chart: actual traffic -------------------------------------------------
  output$p_aadt <- renderPlot({
    shiny::validate(shiny::need(!is.null(aadt),
                                "Traffic data not found. Run R/02_fetch_traffic.R"))

    aadt %>%
      group_by(year) %>%
      summarise(total = sum(aadt), .groups = "drop") %>%
      ggplot(aes(year, total)) +
      geom_col(fill = "#81b29a", alpha = 0.9) +
      geom_text(aes(label = scales::comma(total)), vjust = -0.5, size = 3.6) +
      scale_y_continuous(labels = scales::comma, expand = expansion(c(0, 0.12))) +
      labs(
        title = "Collier County traffic, all monitored road segments",
        subtitle = paste("Annual average daily traffic, summed across segments.",
                         "\nNote: AADT is an ANNUAL average - it cannot show seasonal timing."),
        x = NULL, y = "Total AADT"
      )
  })

  # --- The underlying table --------------------------------------------------
  output$tbl <- renderTable({
    windows() %>%
      transmute(
        Season = as.integer(season_year),
        Opens  = format(opens,  "%d %b %Y"),
        Closes = format(closes, "%d %b %Y"),
        Days   = as.integer(window_days)
      )
  }, striped = TRUE, hover = TRUE, width = "100%")
}

shinyApp(ui, server)
