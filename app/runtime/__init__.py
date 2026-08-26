"""Shell-free launchers used by the edge-endpoint Helm chart.

These modules replace bash wrappers so the FIPS distroless image (no shell) and
the non-FIPS image can share one chart.
"""
