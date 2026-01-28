from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("oss-dashboard")
except PackageNotFoundError:
    # package is not installed
    pass
