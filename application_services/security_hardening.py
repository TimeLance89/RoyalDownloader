"""Install security guards that require the completed application graph."""

from application_services.runtime import _registered_backend
from security_runtime import install_post_state_security


install_post_state_security(_registered_backend())
