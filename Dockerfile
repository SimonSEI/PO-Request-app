# =============================================================================
# Container for the Naples Snowbird Shiny app
# =============================================================================
# rocker/shiny-verse already contains R, Shiny and the whole tidyverse,
# pre-compiled. Building tidyverse from source takes 30+ minutes; starting
# from this image takes seconds. Always start from an image that already has
# your heavy dependencies.
# =============================================================================
FROM rocker/shiny-verse:latest

# bslib ships as a Shiny dependency, but pin a current one for the UI widgets.
# install2.r pulls Linux binaries from Posit Package Manager, so this is fast.
RUN install2.r --error --skipinstalled bslib

WORKDIR /app

# Copy the app and only the data it actually needs at runtime.
COPY app.R .
COPY data/weather_daily.csv  data/weather_daily.csv
COPY data/collier_aadt.csv   data/collier_aadt.csv

# Railway injects PORT at runtime and it is NOT always 3838. Reading the env
# var (with a sane fallback for local runs) is what makes this portable.
# Binding to 0.0.0.0 rather than 127.0.0.1 is essential - localhost inside a
# container is unreachable from outside it, which is the single most common
# reason a containerised web app "starts fine" and still returns 502.
ENV PORT=3838
EXPOSE 3838

CMD ["R", "-e", "shiny::runApp('/app', host = '0.0.0.0', port = as.integer(Sys.getenv('PORT', 3838)))"]
