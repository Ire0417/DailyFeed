"""Pusher Agent 入口。"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from internal.agent.pusher import PusherAgent


def main():
    agent = PusherAgent()
    agent.start()


if __name__ == "__main__":
    main()
