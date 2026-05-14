"""Bulk multi-repo Python doc scan with quality stop-loss (#218).

Funnel pipeline: select -> inventory -> liveness -> investigate -> rank.
All state persisted in unified DB; resumable from any stage on crash.
"""
