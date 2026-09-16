# =============================================================================
# 17 - PULL QUOTES, CLIENTS AND JOB HISTORY FROM JOBBER
# =============================================================================
# Read-only. Writes three files to data/jobber/ (git-ignored):
#
#   quotes.csv   every quote, any status - outstanding ones are what we act on,
#                the rest show when each client has engaged with us before
#   clients.csv  name and billing address - a billing address up north is the
#                first clue to a second home
#   jobs.csv     when work was booked, per client - their personal calendar
#
# Deliberately NOT pulled: emails, phone numbers, notes, line items. None of
# them help decide WHEN to resend, so they stay in Jobber. Take only what the
# question needs.
# =============================================================================

if (file.exists(".Rlib")) .libPaths(c(normalizePath(".Rlib"), .libPaths()))
source("R/jobber_api.R")
suppressPackageStartupMessages(library(tidyverse))

addr_cols <- function(node, prefix, path) {
  a <- node
  for (k in path) a <- if (is.list(a)) a[[k]] else NULL
  tibble(!!paste0(prefix, "street1")  := g(a, "street1"),
         !!paste0(prefix, "street2")  := g(a, "street2"),
         !!paste0(prefix, "city")     := g(a, "city"),
         !!paste0(prefix, "province") := g(a, "province"),
         !!paste0(prefix, "postal")   := g(a, "postalCode"),
         !!paste0(prefix, "country")  := g(a, "country"))
}

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
               "street1", "postalCode"))

quotes <- map_dfr(q$nodes, function(n) bind_cols(
  tibble(quote_id     = g(n, "id"),
         quote_number = g(n, "quoteNumber"),
         status       = tolower(g(n, "quoteStatus")),
         title        = g(n, "title"),
         created_at   = g(n, "createdAt"),
         updated_at   = g(n, "updatedAt"),
         sent_at      = g(n, "sentAt"),
         total        = suppressWarnings(as.numeric(g(n, "amounts", "total"))),
         jobber_link  = g(n, "jobberWebUri"),
         client_id    = g(n, "client", "id"),
         property_id  = g(n, "property", "id")),
  addr_cols(n, "prop_", c("property", "address"))))

# -----------------------------------------------------------------------------
# Clients
# -----------------------------------------------------------------------------
message("Pulling clients...")
cl <- jobber_all("clients",
  spec = list("id", "name", "firstName", "lastName", "companyName", "isCompany",
              "createdAt", "jobberWebUri",
              billingAddress = address_spec),
  required = c("id", "billingAddress", "street1", "province", "country"))

clients <- map_dfr(cl$nodes, function(n) bind_cols(
  tibble(client_id   = g(n, "id"),
         name        = coalesce(g(n, "name"),
                                str_squish(paste(g(n, "firstName"), g(n, "lastName")))),
         first_name  = g(n, "firstName"),
         last_name   = g(n, "lastName"),
         company     = g(n, "companyName"),
         created_at  = g(n, "createdAt"),
         client_link = g(n, "jobberWebUri")),
  addr_cols(n, "bill_", "billingAddress")))

# -----------------------------------------------------------------------------
# Jobs (dates only - when each client books work)
# -----------------------------------------------------------------------------
message("Pulling job history...")
jb <- jobber_all("jobs",
  spec = list("id", "createdAt", "startAt", "completedAt", "jobStatus",
              client = list("id"),
              property = list("id", address = address_spec)),
  required = c("id", "createdAt", "client"))

jobs <- map_dfr(jb$nodes, function(n) bind_cols(
  tibble(job_id       = g(n, "id"),
         created_at   = g(n, "createdAt"),
         start_at     = g(n, "startAt"),
         completed_at = g(n, "completedAt"),
         status       = tolower(g(n, "jobStatus")),
         client_id    = g(n, "client", "id"),
         property_id  = g(n, "property", "id")),
  addr_cols(n, "prop_", c("property", "address"))))

write_csv(quotes,  file.path(JOBBER_DIR, "quotes.csv"))
write_csv(clients, file.path(JOBBER_DIR, "clients.csv"))
write_csv(jobs,    file.path(JOBBER_DIR, "jobs.csv"))
writeLines(format(Sys.time(), "%Y-%m-%d %H:%M"), file.path(JOBBER_DIR, "pulled_at.txt"))

skipped <- unique(c(q$dropped, cl$dropped, jb$dropped))
cat("\nPulled", nrow(quotes), "quotes,", nrow(clients), "clients,", nrow(jobs), "jobs.\n")
cat("Quote statuses:", paste(names(table(quotes$status)), table(quotes$status), sep = " ", collapse = " | "), "\n")
if (length(skipped)) cat("Fields this API version does not offer (skipped):", paste(skipped, collapse = ", "), "\n")
cat("Next: source('R/18_client_second_homes.R')\n")
