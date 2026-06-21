"""Aggregator Agent 入口。"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from internal.agent.aggregator import AggregatorAgent


def main():
    agent = AggregatorAgent()
    agent.start()


if __name__ == "__main__":
    main()
