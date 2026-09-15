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
COPY data/current_conditions.csv      data/current_conditions.csv
COPY data/permanent_moves.csv         data/permanent_moves.csv
COPY data/season_shape.csv            data/season_shape.csv

# These two live in output/ because the analysis scripts write them there, but
# the RUNNING APP reads them: season_forecast.csv supplies the four headline
# dates (rendered into the initial HTML so they appear instantly), and
# seasonal_curve.csv is the baseline curve the Simulation tab shifts.
#
# Verified by diffing every read_csv() path in app.R against this file. Without
# them the container builds cleanly and then serves a dashboard with no dates
# in the header - which is exactly the kind of failure that only shows up in
# production.
COPY output/season_forecast.csv       output/season_forecast.csv
COPY output/seasonal_curve.csv        output/seasonal_curve.csv

# Railway injects PORT at runtime and it is NOT always 3838. Reading the env
# var (with a sane fallback for local runs) is what makes this portable.
#
# DEPLOYMENT NOTE. The first deploy built cleanly and then returned 502. The
# app was fine - the logs said "Listening on http://0.0.0.0:8080", because
# Railway had injected PORT=8080 and the app correctly honoured it. The fault
# was the DOMAIN, which had been created pointing at 3838. Railway was routing
# to a port nothing was listening on.
#
# Fixed by setting PORT=3838 as a service variable so the app and the domain
# agree. The better habit is to let Railway pick the port and not pass an
# explicit targetPort when generating the domain - then the two cannot drift
# apart. Worth knowing that "build succeeded" and "app reachable" are entirely
# separate claims.
#
# Binding to 0.0.0.0 rather than 127.0.0.1 is essential - localhost inside a
# container is unreachable from outside it, which is the single most common
# reason a containerised web app "starts fine" and still returns 502.
ENV PORT=3838
EXPOSE 3838

CMD ["R", "-e", "shiny::runApp('/app', host = '0.0.0.0', port = as.integer(Sys.getenv('PORT', 3838)))"]
