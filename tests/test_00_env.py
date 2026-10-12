"""Imported first by discovery: tests must never reach the network (the live item check in tradestep.fresh is skipped)."""
import os

os.environ["EVE_NO_LIVE"] = "1"
os.environ["EVE_NO_GUARD"] = "1"
