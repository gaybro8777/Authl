""" Authl: A wrapper library to simplify the implementation of federated identity """

import logging
import typing

import expiringdict
from bs4 import BeautifulSoup

from . import handlers, utils

LOGGER = logging.getLogger(__name__)


class Authl:
    """ Authentication wrapper """

    def __init__(self, cfg_handlers: typing.List[handlers.Handler] = None):
        """ Initialize an Authl library instance.

        :param cfg_handlers: a collection of handlers for different authentication
            mechanisms

        """
        self._handlers = cfg_handlers or []

    def add_handler(self, handler):
        """ Add another handler to the configured handler list. It will be
        given the lowest priority. """
        self._handlers.append(handler)

    def get_handler_for_url(self, url):
        """ Get the appropriate handler for the specified identity URL.
        Returns a tuple of (handler, id, url). """
        for pos, handler in enumerate(self._handlers):
            result = handler.handles_url(url)
            if result:
                LOGGER.debug("%s URL matches %s", url, handler)
                return handler, pos, result

        request = utils.request_url(url)
        if request:
            soup = BeautifulSoup(request.text, 'html.parser')
            for pos, handler in enumerate(self._handlers):
                if handler.handles_page(request.url, request.headers, soup, request.links):
                    LOGGER.debug("%s response matches %s", request.url, handler)
                    return handler, pos, request.url

        LOGGER.debug("No handler found for URL %s", url)
        return None, None, None

    def get_handler_by_id(self, handler_id):
        """ Get the handler with the given ID """
        return self._handlers[handler_id]

    @property
    def handlers(self):
        """ get all of the registered handlers, for UX purposes """
        return [*self._handlers]


def from_config(config: typing.Dict[str, typing.Any], token_store=None) -> Authl:
    """ Generate an AUthl handler set from provided configuration directives.

    Arguments:

    :param dict config: a configuration dictionary. See the individual handlers'
        from_config functions to see possible configuration values.
    :param token_store: A dict-like object which will store login tokens with
        expiration. If None, a default will be used.

    Handlers will be enabled based on truthy values of the following keys

        EMAIL_FROM / EMAIL_SENDMAIL -- enable the EmailAddress handler
        MASTODON_NAME -- enable the Mastodon handler
        INDIEAUTH_CLIENT_ID -- enable the IndieAuth handler
        INDIELOGIN_CLIENT_ID -- enable the IndieLogin handler
        TEST_ENABLED -- enable the test/loopback handler

    If token_store is None, the following additional config parameters will be used:

        MAX_PENDING -- the number of pending logins allowed at any given time
        PENDING_TTL -- how long a login has to complete

    """

    if not token_store:
        token_store = expiringdict.ExpiringDict(
            max_len=config.get('MAX_PENDING', 128),
            max_age_seconds=config.get('PENDING_TTL', 600))

    instance = Authl()

    if config.get('EMAIL_FROM') or config.get('EMAIL_SENDMAIL'):
        from .handlers import email_addr
        instance.add_handler(email_addr.from_config(config, token_store))

    if config.get('MASTODON_NAME'):
        from .handlers import mastodon
        instance.add_handler(mastodon.from_config(config, token_store))

    if config.get('INDIEAUTH_CLIENT_ID'):
        from .handlers import indieauth
        instance.add_handler(indieauth.from_config(config, token_store))

    if config.get('INDIELOGIN_CLIENT_ID'):
        from .handlers import indielogin
        instance.add_handler(indielogin.from_config(config, token_store))

    if config.get('TEST_ENABLED'):
        from .handlers import test_handler
        instance.add_handler(test_handler.TestHandler())

    return instance
