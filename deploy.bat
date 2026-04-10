@echo off
echo.
echo ================================
echo   Adynex - Deployment starten
echo ================================
echo.

set /p MSG="Was wurde geaendert? (kurze Beschreibung): "

echo.
echo Dateien werden vorbereitet...
git add .

echo Commit wird erstellt...
git commit -m "%MSG%"

echo Code wird zu GitHub hochgeladen...
git push

echo.
echo ================================
echo   Fertig! Render deployed nun
echo   automatisch die neue Version.
echo.
echo   https://adynex.de
echo ================================
echo.
pause
