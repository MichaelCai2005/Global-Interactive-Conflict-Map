"""Record live feeds so boards can show them for past days, not only right now.

python -m app.live adsb                 poll military aircraft every 2 minutes
python -m app.live adsb --once          one poll
python -m app.live firms --bbox 22,44,41,53 --start 2026-10-10 --days 10
python -m app.live prune --days 90      delete observations older than 90 days
"""
