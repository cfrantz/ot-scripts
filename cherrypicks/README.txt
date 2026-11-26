If problem with credentials: go to ~/.config/gspread and remove file

To update DB: from git repo
DB=~/project/ot-scripts/cherrypicks/commit_2026-04-25.db
~/project/ot-scripts/cherrypicks/commitdb.py --stop 3ead1293011152d49ec408e44b579cd87f7d490c -b earlgrey_1.0.0 "$DB"
~/project/ot-scripts/cherrypicks/commitdb.py --stop f27a6894a1cef4badeb3efe5d64ef334883f49c6 -b master "$DB"

To update html/spreadsheet:
./check_picks.py -b earlgrey_1.0.0 --html foo.html "$DB" --spreadsheet-url https://docs.google.com/spreadsheets/d/1oWr823WS9r25rS8hA_mtYItbNgOuKqIx72sAoKSxHCw/edit?usp=sharing --credentials credentials.json
