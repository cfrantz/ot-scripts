#!/usr/bin/env python3
# Build an HTML table that shows cherrypick information.
#
# Typical usage:
# $ check_picks.py <database_filename> -b earlgrey_1.0.0 > output_file.html

import argparse
import re
import json
import logging
import subprocess
import sys
import sqlite3
import html
from pprint import pprint
from copy import copy
from pathlib import Path
from dataclasses import dataclass
import json

COLORS_HTML = {
    "green": "#93c47d",
    "lgreen": "#b6d7a8",
    "n/a": "#c0c4c9",
    "yellow": "#ffff00",
}

COLORS_GSPREAD = {
    "green": {
        "red": 0x93 / 256,
        "green": 0xc4 / 256,
        "blue": 0x7d / 256,
    },
    "n/a": {
        "red": 0xc0 / 256,
        "green": 0xc4 / 256,
        "blue": 0xc9 / 256,
    },
    "yellow": {
        "red": 0xff / 256,
        "green": 0xff / 256,
        "blue": 0,
    }
}

MANUAL = {
    24834: {"pick": 24345, "from": "master"},
    24872: {"to_master": 24838},
    24939: {"to_master": 25888},
    24976: {"to_master": 25991},
    24977: {"to_master": 25997},
    24984: {"from": "master"},
    25018: {"from": "N/A"},
    25020: {"from": "N/A"},
    25036: {"from": "N/A"},
    25126: {"pick": 25119, "from": "master"},
    25195: {"notes": "Investigate"},
    25273: {"pick": 25268, "from": "master"},
    25275: {"from": "N/A"},
}

flags = argparse.ArgumentParser(description="Cherrypick table builder")
flags.add_argument(
    "--logging",
    default="info",
    choices=["debug", "info", "warning", "error", "critical"],
    help="Logging level",
)
flags.add_argument("--gh_bin", default="gh", help="Github CLI binary")
flags.add_argument("-b", "--branch", type=str, help="Branch to check")
flags.add_argument("database", type=str, help="Database file")
flags.add_argument("--html", type=Path, help="Output HTML table to a file")
flags.add_argument("--spreadsheet-url", type=str, help="Update Google spreadsheet at the given URL")
flags.add_argument("--credentials", type=Path, help="""Path to a json file with the google credentials.
Check https://docs.gspread.org/en/latest/oauth2.html for more details.""",)


class CommitDatabase(object):

    def __init__(self, filename):
        self.db = sqlite3.connect(filename, autocommit=True)

    def create_schema(self):
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS commits (id TEXT, pr INTEGER);
        """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS prs (pr INTEGER PRIMARY KEY, data JSONB);
        """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS branch (
                id TEXT,
                branch TEXT,
                UNIQUE(id, branch)
            );
        """
        )

    def insert_git_commit(self, id, obj):
        logging.info("Commit %s is PR %d", id, obj["number"])
        self.db.execute("INSERT INTO commits VALUES(?, ?)", (id, obj["number"]))
        self.db.execute(
            "INSERT OR IGNORE INTO prs VALUES(?, ?)", (obj["number"], json.dumps(obj))
        )

    def check_git_commit(self, id):
        cur = self.db.execute("SELECT pr FROM commits WHERE id = ?", (id,))
        data = cur.fetchall()
        if len(data):
            return data[0][0]
        else:
            return None

    def get_prs(self):
        """Load the PR database into a dict."""
        prs = {}
        for pr, data in self.db.execute("SELECT pr, data FROM prs;"):
            prs[pr] = json.loads(data)
        return prs


def index_cherrypicks(prs):
    """Determine if a PR is a cherry-pick of another PR."""
    cp = re.compile(r"cherry[ -]?pick", re.I)
    pick = re.compile(r"cherry[ -]?pick (?:of |from )(?:#|https.*pull/)(\d+)", re.I)
    backport = re.compile(r"backport(?: of)? (?:#|https.*pull/)(\d+)", re.I)
    for data in prs.values():
        if m := pick.search(data["body"]):
            data["pick"] = int(m.group(1))
        elif m := pick.search(data["title"]):
            data["pick"] = int(m.group(1))
        elif m := backport.search(data["title"]):
            data["pick"] = int(m.group(1))
        elif m := backport.search(data["body"]):
            data["pick"] = int(m.group(1))
        elif m := cp.search(data["body"]):
            data["pick"] = 0
        else:
            data["pick"] = None


def on_branch(prs, pr, branch):
    """Determine if `pr` was cherry-picked to `branch`."""
    table = {
        k: v for k, v in prs.items() if v["baseRefName"] == branch and v["pick"] == pr
    }
    if len(table) == 1:
        return list(table.values())[0]
    if len(table) > 1:
        logging.error("PR %d has too many picks", pr)
    return None


def tabulate_branch(prs, branch):
    """Tablulate all of the PRs on `branch`."""
    table = {k: v for k, v in prs.items() if v["baseRefName"] == branch}

    for k, v in table.items():
        if v["pick"]:
            # if the item is a cherrypick, figure out where it came from.
            if src := prs.get(v["pick"]):
                v["from"] = src["baseRefName"]
                if v["from"] != "master":
                    # If the item didn't come from master, figure out if it
                    # exists on master.
                    if to_master := on_branch(prs, v["pick"], "master"):
                        # was the cherry-pick picked separately to master.
                        v["to_master"] = to_master["number"]
                    elif to_master := on_branch(prs, k, "master"):
                        # was this item picked to master.
                        v["to_master"] = to_master["number"]
                    else:
                        v["to_master"] = None
            else:
                # Its a cherrypick from an unknown branch.
                v["from"] = "unknown"
                v["to_master"] = None
                if to_master := on_branch(prs, k, "master"):
                    # was this item picked to master.
                    v["to_master"] = to_master["number"]
                else:
                    v["to_master"] = None
        else:
            # Not a cherrypick.
            v["from"] = None
            if to_master := on_branch(prs, k, "master"):
                # was this item picked to master.
                v["to_master"] = to_master["number"]
            else:
                v["to_master"] = None

    return table


class Cell:
    def render_html(self): pass
    def render_gspread(self): pass

@dataclass
class UrlCell(Cell):
    url: str
    label: str

    def render_html(self):
        return '<a href="{}">{}</a>'.format(self.url, self.label)

    def render_gspread(self):
        return '=HYPERLINK("{}", "{}")'.format(self.url, self.label)

def render_pr_link(pr, label = None):
    if label is None:
        label = f"{pr}"
    if pr:
        return UrlCell(url = f'https://github.com/lowRISC/opentitan/pull/{pr}', label = label)
    else:
        return pr


def render_table(table):
    """
    Render the table. The output is a dictionary with the following keys:
    - headers: list of strings
    - rows: list of dictionaries (see below)
    - desc: list of strings (free-style description)

    Each row is described by a dictionary:
    - color: name of the color
    - columns: list of cells (see below)

    Each cell must either be a string, or an object inheriting Cell.
    """
    headers = [
        "PR",
        "To Master",
        "From",
        "Title",
        "Merged",
        "Author",
    ]
    rows = []

    picked = 0
    unpicked = 0
    total = len(table)
    for k in sorted(table.keys()):
        v = table[k]
        if v["pick"] is not None:
            pick = v["pick"]
        else:
            pick = ""
        to_master = v.get("to_master", "")
        source = v["from"]
        notes = v.get("notes", "")

        if manual := MANUAL.get(k):
            # Manual overrides for this PR?
            pick = manual.get("pick", pick)
            to_master = manual.get("to_master", to_master)
            source = manual.get("from", source)
            notes = manual.get("notes", "")

        color = None
        if to_master or source == "master":
            color = "green"
            picked += 1
        else:
            rowstyle = ""
            unpicked += 1

        if source == "N/A":
            color = "n/a"

        if notes:
            color = color or "yellow"
            notes = " <b>(NOTE: {})</b>".format(html.escape(notes))

        columns = [
            render_pr_link(k),
        ]
        if to_master:
            columns.append(render_pr_link(to_master))
        else:
            columns.append("")
        if pick:
            columns.append(render_pr_link(pick, f"{pick} on {source}"))
        else:
            columns.append("")
        columns.append("{}{}".format(
            html.escape(v["title"]),
            notes,
        ))
        columns.append("{}".format(html.escape(v["mergedAt"])))
        columns.append(
            "{}:{}".format(
                html.escape(v["headRepositoryOwner"]["login"]),
                html.escape(v["headRefName"]),
            )
        )
        rows.append({
            "color": color,
            "columns": columns,
        })

    return {
        "headers": headers,
        "rows": rows,
        "desc": [
            f"{picked} of {total} already exist on master",
            f"{unpicked} of {total} need cherry-picks"
        ]
    }


def render_html(html_path, table):
    data = []

    html_out = ""
    def fprint(s):
        nonlocal html_out
        html_out += s

    fprint('<table border="1">')
    fprint("<tr>")
    for hdr in table["headers"]:
        fprint(f"<th>{hdr}</th>")
    fprint("</tr>")

    for row in table["rows"]:
        rowstyle = 'bgcolor="{}"'.format(COLORS_HTML[row["color"]]) if row["color"] else ""

        fprint(f"<tr {rowstyle}>")
        for cell in row["columns"]:
            if isinstance(cell, Cell):
                fprint("<td>{}</td>".format(cell.render_html()))
            else:
                fprint(f"<td>{cell}</td>")
        fprint("</tr>")
    fprint("</table>")
    for desc in table["desc"]:
        fprint(f"<p>{desc}</p>")

    html_path.write_text(html_out)


def open_gspread(args):
    import gspread
    if not args.credentials:
        sys.exit("You need to pass credentials using --credentials")
    gc = gspread.oauth(credentials_filename=args.credentials)
    return gc.open_by_url(args.spreadsheet_url)

def render_gspread(spreadsheet, table):
    sheet = spreadsheet.worksheet("Status")
    print("Rendering to gspread...")

    # The first row is for cookies, the second row for warning text, third row is empty
    first_table_row = 4

    # We store a special value in A1 to detect if the spreadsheet was updated by
    # this script, and in A2 we stored a json table. We always hide the first row
    # to hide this.
    MAGIC_COOKIE = "ot-script cookie"
    if sheet.get("A1") == [[MAGIC_COOKIE]]:
        cookie = json.loads(sheet.get("B1")[0][0])
    else:
        cookie = {
            "first_table_row": first_table_row
        }

    if cookie["first_table_row"] != first_table_row:
        sys.exit("Error: the spreadhseet current uses first_table_row={} but this script wants {}.\n".format(cookie["first_table_row"], first_table_row) +
                 "The script will not update automatically to avoid errors, you must manually update the spreadsheet")

    sheet.update_acell("A1", MAGIC_COOKIE)
    sheet.update_acell("B1", json.dumps(cookie))
    sheet.hide_rows(0, 1)

    sheet.update_acell("A2", "This spreadsheet is automatically generated by the ot-script, you can edit columns starting from {}".format(
                       chr(ord('A')+len(table["headers"]))))
    sheet.format("A2", {'textFormat': {'bold': True}})

    data_range = 'A{}:{}{}'.format(first_table_row, chr(ord('A')+len(table["headers"])-1), first_table_row + len(table["rows"]))

    sheet.batch_clear([data_range])

    sheet.update([table["headers"]] + [
        [
            cell.render_gspread() if isinstance(cell, Cell) else cell
            for cell in row["columns"]
        ]
        for row in table["rows"]
    ], data_range, raw = False)
    # Add colors
    sheet.batch_format([
        {
            "range": '{}'.format(first_table_row + i + 1),
            "format": {
                "backgroundColor": COLORS_GSPREAD[row["color"]] if row["color"] is not None else None
            },
        }
        for (i, row) in enumerate(table["rows"])
    ])
    # Make headers bold and frozen
    sheet.format(str(first_table_row), {'textFormat': {'bold': True}})
    sheet.freeze(first_table_row)
    # Protect autogenerated data: first remove old ranges and then create new ones
    PROTECTED_RANGE_DESC = "Auto-generated content"
    for rng in spreadsheet.list_protected_ranges(sheet.id):
        # Content does not seem to be documented?
        if rng["description"] == PROTECTED_RANGE_DESC:
            sheet.delete_protected_range(rng["protectedRangeId"])

    sheet.add_protected_range(
        data_range,
        description = PROTECTED_RANGE_DESC,
    )


def main(args):

    db = CommitDatabase(args.database)
    prs = db.get_prs()
    index_cherrypicks(prs)
    table = tabulate_branch(prs, args.branch)
    table = render_table(table)
    if args.html:
        render_html(args.html, table)
    if args.spreadsheet_url:
        spreadsheet = open_gspread(args)
        render_gspread(spreadsheet, table)
    return 0


if __name__ == "__main__":
    args = flags.parse_args()
    logging.basicConfig(level=args.logging.upper())
    sys.exit(main(args))

# vim: ts=4 sts=4 sw=4 expandtab:
