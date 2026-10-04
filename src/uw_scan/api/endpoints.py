"""Compatibility re-export. The UW slug registry lives in
``uw_scan.sources.uw_endpoints`` so ``sources`` does not import ``api`` (I-31)."""

from uw_scan.sources.uw_endpoints import REGISTRY, Endpoint, EndpointSlug, build_path

__all__ = ["REGISTRY", "Endpoint", "EndpointSlug", "build_path"]
