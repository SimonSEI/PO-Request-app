# =============================================================================
# JOBBER API HELPERS  (sourced by 16, 17 and the watcher - not run on its own)
# =============================================================================
# Jobber has no plain API key. Access works like "Sign in with Google": an admin
# approves this app once in a browser, Jobber hands back two tokens, and the
# code uses those from then on.
#
#   access token   lets a request through, expires after 60 minutes
#   refresh token  swaps for a new access token without signing in again.
#                  Jobber may ROTATE it (return a new one each time), so it is
#                  saved again after every refresh or it stops working.
#
# WHERE SECRETS LIVE
#   JOBBER_CLIENT_ID / JOBBER_CLIENT_SECRET  ->  .Renviron in the project folder
#   tokens                                    ->  data/jobber/tokens.rds
# Both are in .gitignore. Neither is ever printed. Neither ever reaches GitHub
# or Railway - client data stays on this computer.
# =============================================================================

suppressPackageStartupMessages({
  library(httr)
  library(jsonlite)
})

JOBBER_GQL     <- "https://api.getjobber.com/api/graphql"
JOBBER_TOKEN   <- "https://api.getjobber.com/api/oauth/token"
JOBBER_AUTH    <- "https://api.getjobber.com/api/oauth/authorize"
# On Railway this points at the persistent volume, so tokens survive redeploys.
JOBBER_DIR     <- Sys.getenv("JOBBER_DATA_DIR", "data/jobber")
TOKEN_FILE     <- file.path(JOBBER_DIR, "tokens.rds")

# Jobber dates its API versions and supports each for 12+ months. If this one
# ages out, responses carry a warning naming the replacement - jobber_gql()
# prints it. Override without editing code via JOBBER_API_VERSION in .Renviron.
JOBBER_VERSION <- Sys.getenv("JOBBER_API_VERSION", "2025-04-16")

# The page Jobber sends the browser back to after the admin clicks Allow. It
# must match the "OAuth Callback URL" on the app in Jobber's Developer Center
# character for character. On Railway it is the clients service's own address.
JOBBER_CALLBACK <- Sys.getenv("JOBBER_CALLBACK_URL", "http://localhost:3838/")

dir.create(JOBBER_DIR, showWarnings = FALSE, recursive = TRUE)

jobber_creds <- function() {
  id  <- Sys.getenv("JOBBER_CLIENT_ID")
  sec <- Sys.getenv("JOBBER_CLIENT_SECRET")
  if (!nzchar(id) || !nzchar(sec))
    stop("JOBBER_CLIENT_ID / JOBBER_CLIENT_SECRET are not set. On Railway, add them ",
         "as variables on the clients service.", call. = FALSE)
  list(id = id, secret = sec)
}

save_tokens <- function(tok) {
  tok$obtained_at <- Sys.time()
  saveRDS(tok, TOKEN_FILE)
  invisible(tok)
}

load_tokens <- function() {
  if (!file.exists(TOKEN_FILE))
    stop("Not connected to Jobber yet - run R/16_jobber_connect.R first.", call. = FALSE)
  readRDS(TOKEN_FILE)
}

token_request <- function(body) {
  r <- POST(JOBBER_TOKEN, body = body, encode = "form", timeout(60))
  out <- tryCatch(fromJSON(content(r, "text", encoding = "UTF-8")), error = function(e) list())
  if (status_code(r) >= 400 || is.null(out$access_token))
    stop("Jobber token request failed (HTTP ", status_code(r), "): ",
         out$error_description %||% out$error %||% "no detail", call. = FALSE)
  out
}

jobber_refresh <- function() {
  cr  <- jobber_creds()
  old <- load_tokens()
  new <- token_request(list(client_id = cr$id, client_secret = cr$secret,
                            grant_type = "refresh_token",
                            refresh_token = old$refresh_token))
  # Keep the old refresh token only if Jobber did not issue a replacement.
  if (is.null(new$refresh_token)) new$refresh_token <- old$refresh_token
  save_tokens(new)
}

# One GraphQL call. Refreshes on an expired token, waits out throttling, and
# stops with Jobber's own message on anything else.
jobber_gql <- function(query, variables = NULL, .retry = 3) {
  tok <- load_tokens()
  # Refresh a few minutes early rather than wait to be refused.
  if (difftime(Sys.time(), tok$obtained_at, units = "mins") > 55) tok <- jobber_refresh()

  body <- list(query = query)
  if (!is.null(variables)) body$variables <- variables

  r <- POST(JOBBER_GQL,
            add_headers(Authorization = paste("Bearer", tok$access_token),
                        `X-JOBBER-GRAPHQL-VERSION` = JOBBER_VERSION),
            body = toJSON(body, auto_unbox = TRUE, null = "null"),
            content_type_json(), timeout(120))

  if (status_code(r) == 401 && .retry > 0) {
    jobber_refresh()
    return(jobber_gql(query, variables, .retry - 1))
  }
  if (status_code(r) == 429 && .retry > 0) {
    message("  Jobber rate limit - waiting 60s")
    Sys.sleep(60)
    return(jobber_gql(query, variables, .retry - 1))
  }
  if (status_code(r) >= 400)
    stop("Jobber API HTTP ", status_code(r), call. = FALSE)

  out <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyVector = FALSE)

  warn <- out$extensions$versioning$warning
  if (!is.null(warn)) message("  JOBBER API VERSION WARNING: ", warn)

  if (length(out$errors)) {
    msgs <- vapply(out$errors, function(e) e$message %||% "?", "")
    codes <- vapply(out$errors, function(e) e$extensions$code %||% "", "")
    if (any(codes == "THROTTLED") && .retry > 0) {
      st   <- out$extensions$cost
      need <- (st$requestedQueryCost %||% 1000) - (st$throttleStatus$currentlyAvailable %||% 0)
      wait <- ceiling(max(need, 0) / (st$throttleStatus$restoreRate %||% 500)) + 1
      message("  Jobber throttled - waiting ", wait, "s for query budget")
      Sys.sleep(wait)
      return(jobber_gql(query, variables, .retry - 1))
    }
    err <- simpleError(paste(msgs, collapse = " | "))
    class(err) <- c("jobber_graphql_error", class(err))
    stop(err)
  }
  out$data
}

# -----------------------------------------------------------------------------
# Query building that survives schema differences
# -----------------------------------------------------------------------------
# Jobber's full schema is only visible to signed-in developers, and fields get
# renamed between API versions. So queries are written as nested lists, and if
# Jobber answers "Field 'x' doesn't exist on type 'Y'" that field is dropped
# and the query retried. The fields every step genuinely needs (ids, addresses)
# are marked required and are never dropped - losing one of those is a real
# error and stops the run.
#
# A spec is a list whose unnamed character entries are leaf fields and whose
# named entries are sub-selections, e.g.
#   list("id", "title", client = list("id"))

render_spec <- function(spec) {
  parts <- vapply(seq_along(spec), function(i) {
    nm <- names(spec)[i]
    if (is.null(nm) || !nzchar(nm)) spec[[i]]
    else paste0(nm, " { ", render_spec(spec[[i]]), " }")
  }, "")
  paste(parts, collapse = " ")
}

drop_field <- function(spec, field) {
  keep <- vapply(seq_along(spec), function(i) {
    nm <- names(spec)[i]
    leaf <- is.null(nm) || !nzchar(nm)
    !( (leaf && identical(spec[[i]], field)) || (!leaf && identical(nm, field)) )
  }, TRUE)
  out <- spec[keep]
  for (i in seq_along(out)) {
    nm <- names(out)[i]
    if (!is.null(nm) && nzchar(nm)) out[[i]] <- drop_field(out[[i]], field)
  }
  out
}

# Page through a top-level connection (quotes, clients, jobs). Returns a list
# of nodes, plus the fields that had to be dropped so the caller can say so.
jobber_all <- function(connection, spec, required, page_size = 50, pause = 1) {
  dropped <- character()
  nodes   <- list()
  cursor  <- NULL

  repeat {
    q <- sprintf("query($first: Int!, $after: String) { %s(first: $first, after: $after) { nodes { %s } pageInfo { hasNextPage endCursor } } }",
                 connection, render_spec(spec))
    res <- tryCatch(jobber_gql(q, list(first = page_size, after = cursor)),
                    jobber_graphql_error = function(e) e)

    if (inherits(res, "jobber_graphql_error")) {
      bad <- regmatches(conditionMessage(res),
                        regexec("Field '([A-Za-z0-9_]+)' doesn't exist", conditionMessage(res)))[[1]]
      if (length(bad) == 2 && !(bad[2] %in% required) && !(bad[2] %in% dropped)) {
        message("  ", connection, ": field '", bad[2], "' not in this API version - skipping it")
        dropped <- c(dropped, bad[2])
        spec    <- drop_field(spec, bad[2])
        next
      }
      stop(conditionMessage(res), call. = FALSE)
    }

    page   <- res[[connection]]
    nodes  <- c(nodes, page$nodes)
    message("  ", connection, ": ", length(nodes), " so far")
    if (!isTRUE(page$pageInfo$hasNextPage)) break
    cursor <- page$pageInfo$endCursor
    Sys.sleep(pause)
  }
  list(nodes = nodes, dropped = dropped)
}

# Safe nested getter: g(x, "client", "id") returns NA instead of erroring.
g <- function(x, ...) {
  for (k in c(...)) {
    if (is.null(x) || !is.list(x) || is.null(x[[k]])) return(NA_character_)
    x <- x[[k]]
  }
  if (length(x) == 0) NA_character_ else as.character(x[[1]])
}

address_spec <- list("street1", "street2", "city", "province", "postalCode", "country")

# -----------------------------------------------------------------------------
# What can this API version DO with quotes?
# -----------------------------------------------------------------------------
# Jobber only shows its full schema to signed-in developers, so before building
# anything that changes a quote, ask the API itself. Read-only: this lists
# mutation NAMES and their input fields, never client data. The result goes to
# the service log and data/jobber/schema_probe.json.
jobber_probe_schema <- function() {
  unwrap <- function(t) {
    while (!is.null(t$ofType)) t <- t$ofType
    t$name %||% NA_character_
  }
  q <- "{ __schema { mutationType { fields { name args { name type { name kind ofType { name kind ofType { name kind } } } } } } } }"
  res <- tryCatch(jobber_gql(q), error = function(e) e)
  if (inherits(res, "error")) {
    message("SCHEMA PROBE: introspection unavailable - ", conditionMessage(res))
    return(invisible(NULL))
  }
  muts <- res$`__schema`$mutationType$fields
  keep <- Filter(function(m) grepl("quote|discount|send|message|email|lineitem", m$name, ignore.case = TRUE), muts)

  detail <- lapply(keep, function(m) {
    inputs <- lapply(m$args, function(a) {
      tname <- unwrap(a$type)
      fields <- NULL
      if (!is.na(tname) && grepl("Input|Attributes", tname)) {
        tt <- tryCatch(jobber_gql(sprintf(
          '{ __type(name: "%s") { inputFields { name type { name kind ofType { name kind ofType { name kind } } } } } }', tname)),
          error = function(e) NULL)
        fields <- vapply(tt$`__type`$inputFields %||% list(),
                         function(f) paste0(f$name, ":", unwrap(f$type)), "")
      }
      list(arg = a$name, type = tname, fields = fields)
    })
    list(mutation = m$name, args = inputs)
  })

  message("SCHEMA PROBE: ", length(muts), " mutations in total; quote/send-related:")
  for (d in detail) {
    message("  ", d$mutation)
    for (a in d$args)
      message("    ", a$arg, " (", a$type, ")",
              if (length(a$fields)) paste0(": ", paste(a$fields, collapse = ", ")) else "")
  }

  # Which permissions did the admin grant? The access token is a JWT; its
  # payload is readable. Only the scope list is logged - never the token.
  tok <- load_tokens()
  payload <- tryCatch({
    p <- strsplit(tok$access_token, ".", fixed = TRUE)[[1]][2]
    p <- chartr("-_", "+/", p); p <- paste0(p, strrep("=", (4 - nchar(p) %% 4) %% 4))
    jsonlite::fromJSON(rawToChar(openssl::base64_decode(p)))
  }, error = function(e) list())
  sc <- payload$scope %||% payload$scopes
  message("SCHEMA PROBE: granted scopes: ", if (is.null(sc)) "(not listed in token)" else paste(sc, collapse = " "))

  # Saved together, because the two answers only mean anything side by side: a
  # send mutation this app has no scope for is no more use than no mutation at
  # all. Scopes are permission names, never the token itself.
  jsonlite::write_json(
    list(probed_at      = format(Sys.time(), "%Y-%m-%d %H:%M:%S", tz = "America/New_York"),
         total_mutations = length(muts),
         scopes         = if (is.null(sc)) character() else as.character(sc),
         mutations      = detail),
    file.path(JOBBER_DIR, "schema_probe.json"), auto_unbox = TRUE, pretty = TRUE)

  invisible(detail)
}

# -----------------------------------------------------------------------------
# Connecting an account from a web page (the clients app on Railway)
# -----------------------------------------------------------------------------
# state  - a random value that must come back unchanged, so a stray or forged
#          redirect cannot slip tokens in. It is only created after someone has
#          logged in to the clients app, so a matching state proves the flow was
#          started by an authorised user.
# PKCE   - a random 'verifier' whose hash goes in the link and the original in
#          the token swap, so an intercepted code is useless on its own.
# Both are kept on disk between the two page loads; codes expire in 10 minutes.
PENDING_FILE <- file.path(JOBBER_DIR, "pending_auth.rds")

b64url <- function(raw) gsub("=+$", "", chartr("+/", "-_", openssl::base64_encode(raw)))

jobber_auth_start <- function() {
  cr       <- jobber_creds()
  verifier <- b64url(openssl::rand_bytes(48))
  state    <- b64url(openssl::rand_bytes(24))
  saveRDS(list(state = state, verifier = verifier, created = Sys.time()), PENDING_FILE)
  paste0(JOBBER_AUTH,
         "?response_type=code",
         "&client_id=",      URLencode(cr$id, reserved = TRUE),
         "&redirect_uri=",   URLencode(JOBBER_CALLBACK, reserved = TRUE),
         "&state=",          state,
         "&code_challenge=", b64url(openssl::sha256(charToRaw(verifier))),
         "&code_challenge_method=S256")
}

# Returns the connected account's name, or stops with a plain reason.
jobber_auth_finish <- function(code, state) {
  if (!file.exists(PENDING_FILE)) stop("No connection was started from this app.", call. = FALSE)
  pend <- readRDS(PENDING_FILE)
  if (!identical(state, pend$state)) stop("This sign-in does not match the one started here.", call. = FALSE)
  unlink(PENDING_FILE)   # single use, whatever happens next
  if (difftime(Sys.time(), pend$created, units = "mins") > 10)
    stop("The sign-in took longer than 10 minutes. Start it again.", call. = FALSE)

  cr  <- jobber_creds()
  tok <- token_request(list(client_id = cr$id, client_secret = cr$secret,
                            grant_type = "authorization_code", code = code,
                            redirect_uri = JOBBER_CALLBACK, code_verifier = pend$verifier))
  save_tokens(tok)
  acct <- jobber_gql("{ account { id name } }")$account
  saveRDS(list(id = acct$id, name = acct$name, connected_at = Sys.time()),
          file.path(JOBBER_DIR, "account.rds"))
  acct$name
}
