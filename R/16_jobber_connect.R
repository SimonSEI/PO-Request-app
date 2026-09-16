# =============================================================================
# 16 - CONNECT TO JOBBER  (run once; again only if the connection is revoked)
# =============================================================================
# BEFORE RUNNING - one-time setup in Jobber, about ten minutes:
#
#   1. Go to https://developer.getjobber.com and sign up for a developer account
#      (free, separate from your normal Jobber login).
#   2. Manage Apps -> New App. Give it any name, e.g. "Snowbird quote timing".
#   3. OAuth Callback URL:   http://localhost:8765/callback
#   4. Scopes - tick READ access only for:  Clients, Quotes, Jobs
#      (nothing here ever writes to Jobber, so it should never be able to)
#   5. Save. Copy the Client ID and Client Secret.
#   6. In this project folder, copy jobber.Renviron.example to a file named
#      .Renviron, paste the two values in, and RESTART R so it reads them.
#
# THEN RUN THIS SCRIPT. A browser tab opens on Jobber's approval page. A Jobber
# ADMIN signs in there and clicks Allow Access. The tab says "Connected" and
# this script saves the tokens and checks it can see your account.
#
# Nobody types a password into R. The sign-in happens on Jobber's own page.
# =============================================================================

if (file.exists(".Rlib")) .libPaths(c(normalizePath(".Rlib"), .libPaths()))
source("R/jobber_api.R")
suppressPackageStartupMessages({ library(openssl); library(httpuv) })

cr <- jobber_creds()

# -----------------------------------------------------------------------------
# PKCE + state
# -----------------------------------------------------------------------------
# state  - a random value we check comes back unchanged, so a stray or forged
#          redirect cannot slip tokens into this script.
# PKCE   - a random 'verifier' whose hash goes in the link and the original in
#          the token swap, so an intercepted code is useless on its own.
# Jobber recommends both.
b64url   <- function(raw) gsub("=+$", "", chartr("+/", "-_", base64_encode(raw)))
verifier <- b64url(rand_bytes(48))
challenge <- b64url(sha256(charToRaw(verifier)))
state    <- b64url(rand_bytes(24))

auth_url <- paste0(JOBBER_AUTH,
  "?response_type=code",
  "&client_id=",      URLencode(cr$id, reserved = TRUE),
  "&redirect_uri=",   URLencode(JOBBER_CALLBACK, reserved = TRUE),
  "&state=",          state,
  "&code_challenge=", challenge,
  "&code_challenge_method=S256")

# -----------------------------------------------------------------------------
# A tiny local web server to catch the redirect
# -----------------------------------------------------------------------------
got <- new.env()
page <- function(title, msg) paste0(
  "<html><body style='font-family:system-ui;background:#E6E6EB;display:flex;",
  "align-items:center;justify-content:center;height:100vh;margin:0'>",
  "<div style='background:#fff;padding:32px 40px;border-radius:14px;max-width:420px'>",
  "<h2 style='margin:0 0 8px'>", title, "</h2><p style='color:#6E6E73;margin:0'>",
  msg, "</p></div></body></html>")

srv <- startServer("127.0.0.1", JOBBER_PORT, list(call = function(req) {
  if (req$PATH_INFO != "/callback")
    return(list(status = 404L, headers = list(`Content-Type` = "text/plain"), body = "not found"))
  # "?code=...&state=..." -> list(code = , state = )
  kv <- strsplit(strsplit(sub("^\\?", "", req$QUERY_STRING), "&", fixed = TRUE)[[1]], "=", fixed = TRUE)
  qs <- setNames(lapply(kv, function(p) decodeURIComponent(paste(p[-1], collapse = "="))),
                 vapply(kv, `[`, "", 1))
  if (!identical(qs$state, state)) {
    got$error <- "state mismatch - ignoring this redirect"
    return(list(status = 400L, headers = list(`Content-Type` = "text/html"),
                body = page("Something went wrong", "The response did not match this sign-in. Close this tab and run the script again.")))
  }
  got$code <- qs$code
  list(status = 200L, headers = list(`Content-Type` = "text/html"),
       body = page("Connected", "Jobber approved the connection. You can close this tab and go back to R."))
}))

cat("\nOpening Jobber's approval page in your browser.\n",
    "A Jobber ADMIN must sign in and click 'Allow Access'.\n",
    "If no tab opens, paste this link into your browser:\n\n", auth_url, "\n\n", sep = "")
browseURL(auth_url)

# Authorization codes expire after 10 minutes, so there is no point waiting longer.
# (finally, not on.exit: in a source()d script on.exit fires as soon as its own
# line finishes, which would shut the server before Jobber could reach it.)
deadline <- Sys.time() + 600
tryCatch({
  while (is.null(got$code) && is.null(got$error) && Sys.time() < deadline) service(250)
  service(250)   # let the "Connected" page finish sending
}, finally = stopServer(srv))
if (!is.null(got$error)) stop(got$error, call. = FALSE)
if (is.null(got$code))   stop("No approval within 10 minutes - run the script again.", call. = FALSE)

# -----------------------------------------------------------------------------
# Swap the code for tokens and prove they work
# -----------------------------------------------------------------------------
tok <- token_request(list(
  client_id = cr$id, client_secret = cr$secret,
  grant_type = "authorization_code", code = got$code,
  redirect_uri = JOBBER_CALLBACK, code_verifier = verifier))
save_tokens(tok)

acct <- jobber_gql("{ account { id name } }")$account
saveRDS(list(id = acct$id, name = acct$name, connected_at = Sys.time()),
        file.path(JOBBER_DIR, "account.rds"))

cat("\nConnected to Jobber account:", acct$name, "\n")
cat("Tokens saved to", TOKEN_FILE, "(git-ignored). Next: source('R/17_jobber_pull.R')\n")
