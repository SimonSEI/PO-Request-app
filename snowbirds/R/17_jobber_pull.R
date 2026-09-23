# =============================================================================
# 17 - PULL QUOTES, CLIENTS AND JOB HISTORY FROM JOBBER
# =============================================================================
# Read-only. Writes three files to the Jobber data folder:
#
#   quotes.csv   every quote, any status - outstanding ones are what we act on,
#                the rest show when each client has engaged with us before
#   clients.csv  name, billing address and phone AREA CODES - a billing
#                address or a mobile number from up north are clues to a
#                second home
#   jobs.csv     when work was booked, per client - their personal calendar
#
# PULL_SCOPE (environment variable):
#   "quotes"  quotes only - a couple of minutes. Run every 30 minutes in the
#             day, because quote status is what goes stale. Falls back to a
#             full pull if clients/jobs have never been pulled.
#   "all"     everything - run overnight; clients and job history change slowly
#
# Deliberately NOT pulled: emails, full phone numbers, notes, line items.
# Only the three-digit area code of each phone is kept: most snowbirds keep the
# mobile they had up north, so it helps decide WHO is a snowbird. The rest of
# the number identifies a person and helps nothing here, so it stays in Jobber.
# =============================================================================

if (file.exists(".Rlib")) .libPaths(c(normalizePath(".Rlib"), .libPaths()))
source("R/jobber_api.R")
suppressPackageStartupMessages(library(tidyverse))

scope <- Sys.getenv("PULL_SCOPE", "all")
if (scope == "quotes" &&
    !all(file.exists(file.path(JOBBER_DIR, c("clients.csv", "jobs.csv"))))) {
  message("No client/job history on disk yet - doing a full pull")
  scope <- "all"
}

# Column extraction in one pass per field (about 4 s for 35,000 records).
# Where the old 20-minute refresh actually went: paging 50 records at a time
# with a 1-second pause after every page - roughly 700 pages, 12 minutes of
# which was the pause. Pages are now 100 records with a 0.2 s pause, which
# still sits well inside Jobber's query budget (the client waits and retries
# if it is ever throttled).
col <- function(nodes, ...) {
  path <- c(...)
  vapply(nodes, function(n) {
    for (k in path) { if (!is.list(n) || is.null(n[[k]])) return(NA_character_); n <- n[[k]] }
    if (length(n) == 0) NA_character_ else as.character(n[[1]])
  }, character(1), USE.NAMES = FALSE)
}
addr <- function(nodes, prefix, ...) {
  p <- c(...)
  out <- list(col(nodes, p, "street1"), col(nodes, p, "street2"), col(nodes, p, "city"),
              col(nodes, p, "province"), col(nodes, p, "postalCode"), col(nodes, p, "country"))
  names(out) <- paste0(prefix, c("street1", "street2", "city", "province", "postal", "country"))
  as_tibble(out)
}

started <- Sys.time()

# -----------------------------------------------------------------------------
# Quotes
# -----------------------------------------------------------------------------
message("Pulling quotes...")
q <- jobber_all("quotes",
  spec = list("id", "quoteNumber", "quoteStatus", "title", "createdAt", "updatedAt",
              "sentAt", "jobberWebUri",
              amounts = list("total"),
              client  = list("id"),
              property = list("id", address = address_spec)),
  required = c("id", "quoteStatus", "createdAt", "client", "property", "address",
               "street1", "postalCode"),
  page_size = 100, pause = 0.2)

n <- q$nodes
quotes <- bind_cols(
  tibble(quote_id     = col(n, "id"),
         quote_number = col(n, "quoteNumber"),
         status       = tolower(col(n, "quoteStatus")),
         title        = col(n, "title"),
         created_at   = col(n, "createdAt"),
         updated_at   = col(n, "updatedAt"),
         sent_at      = col(n, "sentAt"),
         total        = suppressWarnings(as.numeric(col(n, "amounts", "total"))),
         jobber_link  = col(n, "jobberWebUri"),
         client_id    = col(n, "client", "id"),
         property_id  = col(n, "property", "id")),
  addr(n, "prop_", "property", "address"))

# Write-then-rename, so the app never reads a half-written file.
save_csv <- function(df, name) {
  tmp <- file.path(JOBBER_DIR, paste0(name, ".partial"))
  write_csv(df, tmp)
  invisible(file.rename(tmp, file.path(JOBBER_DIR, name)))
}
save_csv(quotes, "quotes.csv")
dropped <- q$dropped

if (scope == "all") {
  # ---------------------------------------------------------------------------
  # Clients
  # ---------------------------------------------------------------------------
  message("Pulling clients...")
  cl <- jobber_all("clients",
    spec = list("id", "name", "firstName", "lastName", "companyName", "isCompany",
                "createdAt", "jobberWebUri",
                billingAddress = address_spec,
                # Not required: if this API version has no phones field it is
                # dropped and every client simply has no area code.
                phones = list("number")),
    required = c("id", "billingAddress", "street1", "province", "country"),
    page_size = 100, pause = 0.2)

  n <- cl$nodes

  # Every distinct area code on the client, e.g. "239;312". The number itself
  # is reduced to its first three digits here and never written anywhere.
  area_codes <- function(node) {
    ph <- node$phones
    if (!is.list(ph) || length(ph) == 0) return(NA_character_)
    codes <- vapply(ph, function(p) {
      d <- gsub("[^0-9]", "", as.character(p$number %||% ""))
      if (nchar(d) == 11 && startsWith(d, "1")) d <- substring(d, 2)
      if (nchar(d) == 10) substr(d, 1, 3) else NA_character_
    }, character(1))
    codes <- unique(codes[!is.na(codes)])
    if (length(codes)) paste(codes, collapse = ";") else NA_character_
  }

  clients <- bind_cols(
    tibble(client_id   = col(n, "id"),
           name        = coalesce(col(n, "name"), str_squish(paste(col(n, "firstName"), col(n, "lastName")))),
           first_name  = col(n, "firstName"),
           last_name   = col(n, "lastName"),
           company     = col(n, "companyName"),
           # isCompany was already being requested from the API and then
           # dropped on the floor. It is the only authoritative "this is a
           # business, not a household" signal Jobber gives us.
           is_company  = col(n, "isCompany"),
           created_at  = col(n, "createdAt"),
           client_link = col(n, "jobberWebUri"),
           phone_areas = vapply(n, area_codes, character(1), USE.NAMES = FALSE)),
    addr(n, "bill_", "billingAddress"))

  # ---------------------------------------------------------------------------
  # Jobs (dates only - when each client books work)
  # ---------------------------------------------------------------------------
  message("Pulling job history...")
  jb <- jobber_all("jobs",
    spec = list("id", "createdAt", "startAt", "completedAt", "jobStatus",
                client = list("id"),
                property = list("id", address = address_spec)),
    required = c("id", "createdAt", "client"),
    page_size = 100, pause = 0.2)

  n <- jb$nodes
  jobs <- bind_cols(
    tibble(job_id       = col(n, "id"),
           created_at   = col(n, "createdAt"),
           start_at     = col(n, "startAt"),
           completed_at = col(n, "completedAt"),
           status       = tolower(col(n, "jobStatus")),
           client_id    = col(n, "client", "id"),
           property_id  = col(n, "property", "id")),
    addr(n, "prop_", "property", "address"))

  save_csv(clients, "clients.csv")
  save_csv(jobs, "jobs.csv")
  writeLines(format(Sys.time(), "%Y-%m-%d %H:%M"), file.path(JOBBER_DIR, "pulled_all_at.txt"))
  dropped <- c(dropped, cl$dropped, jb$dropped)
}
writeLines(format(Sys.time(), "%Y-%m-%d %H:%M"), file.path(JOBBER_DIR, "pulled_at.txt"))

cat("\nPulled", nrow(quotes), "quotes",
    if (scope == "all") paste(",", nrow(clients), "clients,", nrow(jobs), "jobs") else "(quotes only)",
    "in", round(as.numeric(difftime(Sys.time(), started, units = "mins")), 1), "min\n")
cat("Quote statuses:", paste(names(table(quotes$status)), table(quotes$status), sep = " ", collapse = " | "), "\n")
if (length(unique(dropped))) cat("Fields this API version does not offer (skipped):", paste(unique(dropped), collapse = ", "), "\n")
