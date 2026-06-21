"""Fetcher Agent 入口。"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from internal.agent.fetcher import FetcherAgent


def main():
    agent = FetcherAgent()
    agent.start()


if __name__ == "__main__":
    main()
