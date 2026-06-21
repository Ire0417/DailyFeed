"""Summarizer Agent 入口。"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from internal.agent.summarizer import SummarizerAgent


def main():
    agent = SummarizerAgent()
    agent.start()


if __name__ == "__main__":
    main()
