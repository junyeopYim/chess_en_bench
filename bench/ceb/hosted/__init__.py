"""Hosted official evaluation: submissions, jobs, worker, verified results.

The default backend is SQLite + local filesystem so a toy hosted evaluation
runs anywhere; the same interfaces are the deployment seam for a real
service. Only results produced by the hosted worker are `verified`.
"""
