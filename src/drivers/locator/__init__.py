"""
定位器模块

提供多层次定位策略
"""

from .multi_layer_locator import (
    LocatorInfo,
    LocatorResult,
    DOMLocator,
    UIAutomationLocator,
    CoordinateLocator,
    ImageLocator,
    MultiLayerLocator,
)
from .image_matcher import ImageMatcher

__all__ = [
    "LocatorInfo",
    "LocatorResult",
    "DOMLocator",
    "UIAutomationLocator",
    "CoordinateLocator",
    "ImageLocator",
    "MultiLayerLocator",
    "ImageMatcher",
]
