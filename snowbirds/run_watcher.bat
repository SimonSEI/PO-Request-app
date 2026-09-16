@echo off
REM ===========================================================
REM  Naples Snowbird watcher
REM  Checks all data sources, re-runs whatever changed, and
REM  alerts if a headline prediction moves.
REM  Registered as Scheduled Task "NaplesSnowbirdWatcher", 07:00 daily.
REM
REM  cd to the project folder FIRST - that is what lets .Rprofile
REM  put the project's own .Rlib on the library path. Without it,
REM  a Scheduled Task finds no packages at all and dies with
REM      Error in library(tidyverse): there is no package called
REM  even though the same script runs fine from a terminal.
REM
REM  Log: output\watch_log.txt
REM ===========================================================
cd /d "%~dp0"

set "RSCRIPT=C:\Program Files\R\R-4.6.1\bin\Rscript.exe"

if not exist "output" mkdir "output"

echo. >> output\watch_log.txt
echo ===== %DATE% %TIME% ===== >> output\watch_log.txt
"%RSCRIPT%" "R\12_watch.R" >> output\watch_log.txt 2>&1
echo exit code: %ERRORLEVEL% >> output\watch_log.txt
