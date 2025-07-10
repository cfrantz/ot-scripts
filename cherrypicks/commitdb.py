#!/usr/bin/env python3
# Query github to build a database of git commit hashes and github PR numbers.
#
# Typical usage:
# $ cd $OT_REPO
# $ commitdb.py <database_filename>  -b master -b earlgrey_1.0.0 --limit 100

import argparse
import re
import json
import logging
import subprocess
import sys
import sqlite3
from pprint import pprint
from copy import copy

flags = argparse.ArgumentParser(description="Commits database builder")
flags.add_argument(
    "--logging",
    default="info",
    choices=["debug", "info", "warning", "error", "critical"],
    help="Logging level",
)
flags.add_argument("--gh_bin", default="gh", help="Github CLI binary")
flags.add_argument(
    "--dry-run",
    action=argparse.BooleanOptionalAction,
    default=False,
    help="Do not perform any github API actions",
)
flags.add_argument(
    "-b", "--branch", type=str, action="append", help="Branches to parse"
)
flags.add_argument("--stop", type=str, help="Commit to stop at in git log")
flags.add_argument(
    "--limit",
    type=int,
    default=1000000,
    help="Stop after processing this number of commits",
)
flags.add_argument("database", type=str, help="Database file")


class GithubApi(object):

    def __init__(self, gh, dry_run=False):
        self.gh = gh
        self.dry_run = dry_run

    @staticmethod
    def call(args, dry_run=False):
        """Call a subprocess.

        Args:
          args: List[str]; List of arguments.
          dry_run: bool; If true, print the command that would have been called.
        """
        if dry_run:
            print("===== DRY_RUN =====")
            for a in args:
                print(f" '{a}'", end="")
            print()
            return ""
        else:
            return subprocess.check_output(args)

    def get_commit(self, id):
        items = [
            "url",
            "author",
            "assignees",
            "baseRefName",
            "headRefName",
            "headRepositoryOwner",
            "mergedAt",
            "labels",
            "number",
            "title",
            "body",
        ]
        cmd = [
            self.gh,
            "pr",
            "list",
            "-s",
            "merged",
            "--search",
            id,
            "--json",
            ",".join(items),
        ]
        return json.loads(self.call(cmd, self.dry_run))


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
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS commits_desc (id TEXT, desc TEXT, UNIQUE(id, desc));
        """
        )

    def insert_git_commit(self, id, obj):
        logging.info("Commit %s is PR %d", id, obj["number"])
        self.db.execute("INSERT INTO commits VALUES(?, ?)", (id, obj["number"]))
        self.db.execute(
            "INSERT OR IGNORE INTO prs VALUES(?, ?)", (obj["number"], json.dumps(obj))
        )

    def insert_git_commit_desc(self, id, desc):
        self.db.execute("INSERT INTO commits_desc VALUES(?, ?)", (id, desc))

    def check_git_commit(self, id):
        cur = self.db.execute("SELECT pr FROM commits WHERE id = ?", (id,))
        data = cur.fetchall()
        if len(data):
            return data[0][0]
        else:
            return None


def gitlog(branch, stop):
    """Get a list of git commit-ids on the given branch."""
    command = [
        "git",
        "log",
        "--oneline",
        "--no-abbrev-commit",
    ]
    if stop:
        branch = f"{stop}..{branch}"
    command.append(branch)
    data = subprocess.check_output(command)
    commits = []
    for line in data.splitlines():
        line = line.decode("utf-8")
        (commit, desc) = line.split(" ", 1)
        commits.append((commit, desc))
    return commits


def build_db(gh, db, branch, stop, limit):
    """Query the GH API to learn PR information about commits on a branch."""
    commits = gitlog(branch, stop)
    for (c, desc) in commits:
        db.insert_git_commit_desc(c, desc)
        check = db.check_git_commit(c)
        if check is not None:
            logging.info("Commit %s is already known as PR %d", c, check)
            continue
        data = gh.get_commit(c)
        for d in data:
            db.insert_git_commit(c, d)
        limit -= 1
        if limit == 0:
            logging.info("Reached limit; stopping.")
            break


def main(args):

    db = CommitDatabase(args.database)
    db.create_schema()
    gh = GithubApi(args.gh_bin, args.dry_run)

    if not args.branch:
        logging.error("You must supply at least one --branch")
        return 1

    for branch in args.branch:
        logging.info("Processing branch %s...", branch)
        build_db(gh, db, branch, args.stop, args.limit)
    return 0


if __name__ == "__main__":
    args = flags.parse_args()
    logging.basicConfig(level=args.logging.upper())
    sys.exit(main(args))

# vim: ts=4 sts=4 sw=4 expandtab:
