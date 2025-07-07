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

GREEN = "#93c47d"
LGREEN = "#b6d7a8"
NA = "#c0c4c9"
YELLOW = "#ffff00"

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


def render_pr_link(pr):
    if pr:
        return f'<a href="https://github.com/lowRISC/opentitan/pull/{pr}">{pr}</a>'
    else:
        return pr


def render_table(table):
    data = []

    print('<table border="1">')
    print("<tr>")
    print("<th>PR</th>")
    print("<th>To Master</th>")
    print("<th>From</th>")
    print("<th>Title</th>")
    print("<th>Merged</th>")
    print("<th>Author</th>")
    print("</tr>")

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
        notes = ""

        if manual := MANUAL.get(k):
            # Manual overrides for this PR?
            pick = manual.get("pick", pick)
            to_master = manual.get("to_master", to_master)
            source = manual.get("from", source)
            notes = manual.get("notes", "")

        if to_master or source == "master":
            rowstyle = f'bgcolor="{GREEN}"'
            picked += 1
        else:
            rowstyle = ""
            unpicked += 1

        if source == "N/A":
            rowstyle = f'bgcolor="{NA}"'

        if notes:
            rowstyle = f'bgcolor="{YELLOW}"'
            notes = " <b>(NOTE: {})</b>".format(html.escape(notes))

        print(f"<tr {rowstyle}>")
        print("<td>{}</td>".format(render_pr_link(k)))
        if to_master:
            print("<td>{}</td>".format(render_pr_link(to_master)))
        else:
            print("<td></td>")
        if pick:
            print("<td>{} on {}</td>".format(render_pr_link(pick), source))
        else:
            print("<td></td>")
        print(
            "<td>{}{}</td>".format(
                html.escape(v["title"]),
                notes,
            )
        )
        print("<td>{}</td>".format(html.escape(v["mergedAt"])))
        print(
            "<td>{}:{}</td>".format(
                html.escape(v["headRepositoryOwner"]["login"]),
                html.escape(v["headRefName"]),
            )
        )
        print("</tr>")
    print("</table>")
    print(f"<p>{picked} of {total} already exist on master</p>")
    print(f"<p>{unpicked} of {total} need cherry-picks</p>")


def main(args):

    db = CommitDatabase(args.database)
    prs = db.get_prs()
    index_cherrypicks(prs)
    table = tabulate_branch(prs, args.branch)
    render_table(table)
    return 0


if __name__ == "__main__":
    args = flags.parse_args()
    logging.basicConfig(level=args.logging.upper())
    sys.exit(main(args))

# vim: ts=4 sts=4 sw=4 expandtab:
