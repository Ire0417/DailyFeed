"""Scheduler Agent 入口。"""
import asyncio
import sys
import os

# Ensure backend/ is on the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from internal.agent.scheduler import SchedulerAgent


def main():
    agent = SchedulerAgent()
    agent.start()


if __name__ == "__main__":
    main()
