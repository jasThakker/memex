"""Command line entry point."""

import argparse

from toolkit import Client

from reporter.formats import table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("title")
    args = parser.parse_args()
    Client().send(args.title)
    print(table.render_table([args.title]))
