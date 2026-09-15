# =============================================================================
# Container for the Naples Snowbird dashboard
# =============================================================================
# rocker/shiny-verse already contains R, Shiny and the whole tidyverse,
# pre-compiled. Building tidyverse from source takes 30+ minutes; starting
# from this image takes seconds. Always start from an image that already has
# your heavy dependencies.
# =============================================================================
FROM rocker/shiny-verse:latest

# bslib ships with Shiny, but pin current versions of the UI packages.
# install2.r pulls Linux binaries from Posit Package Manager, so this is fast.
RUN install2.r --error --skipinstalled bslib shinycssloaders

WORKDIR /app

COPY app.R .

# Only the data the RUNNING APP reads. The analysis scripts and their raw
# downloads (a 1.55GB Access database, 168MB of parcel records) stay out of
# the image - they are inputs to the pipeline, not to the dashboard.
COPY data/weather_daily.csv           data/weather_daily.csv
COPY data/origin_state_temps.csv      data/origin_state_temps.csv
COPY data/origin_states.csv           data/origin_states.csv
COPY data/collier_daily_traffic.csv   data/collier_daily_traffic.csv
COPY data/collier_hist_aadt.csv       data/collier_hist_aadt.csv
COPY data/rsw_monthly_passengers.csv  data/rsw_monthly_passengers.csv

# Railway injects PORT at runtime and it is NOT always 3838. Reading the env
# var (with a sane fallback for local runs) is what makes this portable.
#
# Binding to 0.0.0.0 rather than 127.0.0.1 is essential - localhost inside a
# container is unreachable from outside it, which is the single most common
# reason a containerised web app "starts fine" and still returns 502.
ENV PORT=3838
EXPOSE 3838

CMD ["R", "-e", "shiny::runApp('/app', host = '0.0.0.0', port = as.integer(Sys.getenv('PORT', 3838)))"]
