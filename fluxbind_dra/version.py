__version__ = "0.0.1"
AUTHOR = "Vanessa Sochat"
AUTHOR_EMAIL = "vsoch@users.noreply.github.com"
NAME = "fluxbind-dra"
PACKAGE_URL = "https://github.com/compspec/fluxbind-dra"
KEYWORDS = "cluster, orchestration, mpi, binding, topology"
DESCRIPTION = "Process mapping for Kubernetes pods"
LICENSE = "LICENSE"


################################################################################
# Global requirements

# Note that the spack / environment modules plugins are installed automatically.
# This doesn't need to be the case.
INSTALL_REQUIRES = (
    ("fluxbind", {"min_version": None}),
    ("kubernetes", {"min_version": None}),
    ("PyYAML", {"min_version": None}),
    ("grpcio-tools", {"min_version": None}),
    ("grpcio", {"min_version": None}),
)

TESTS_REQUIRES = ()
INSTALL_REQUIRES_ALL = INSTALL_REQUIRES + TESTS_REQUIRES
