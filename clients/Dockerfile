# =============================================================================
# Container for the PRIVATE snowbird clients service
# =============================================================================
# Built from the repo root (Railway: Dockerfile path = clients/Dockerfile) so it
# can reuse the Jobber scripts in R/ and the forecast outputs.
#
# No client data is baked in. Tokens, pulled quotes, the property roll and the
# resend plan all live on the Railway volume mounted at /data.
# =============================================================================
FROM rocker/shiny-verse:latest

RUN install2.r --error --skipinstalled bslib DT later openssl httr

WORKDIR /app

COPY R/jobber_api.R                 R/jobber_api.R
COPY R/17_jobber_pull.R             R/17_jobber_pull.R
COPY R/18_client_second_homes.R     R/18_client_second_homes.R
COPY clients/fetch_roll.R           clients/fetch_roll.R
COPY clients/auto_send.R            clients/auto_send.R
COPY clients/app.R                  clients/app.R

# The area forecast R/18 falls back on when a client has no history.
COPY output/season_forecast.csv     output/season_forecast.csv
COPY data/current_conditions.csv    data/current_conditions.csv

# The 7am refresh is 7am Eastern - Naples time, not the server's UTC.
ENV TZ=America/New_York \
    APP_ROOT=/app \
    JOBBER_DATA_DIR=/data/jobber \
    SNOWBIRD_CLIENT_OUT=/data/clients \
    COLLIER_ROLL=/data/rolls/collier_parcels.csv \
    LEE_ROLL=/data/rolls/lee_nal.csv \
    PORT=3838

EXPOSE 3838

CMD ["R", "-e", "shiny::runApp('/app/clients', host = '0.0.0.0', port = as.integer(Sys.getenv('PORT', 3838)))"]
