"""Command line entry point."""

import argparse

from toolkit import Client

from reporter.formats.table import render_table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("title")
    args = parser.parse_args()
    Client().send(args.title)
    print(render_table([args.title]))
