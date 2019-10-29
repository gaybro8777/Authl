""" IndieAuth login handler. """

import logging
import urllib.parse

import expiringdict
import requests
from bs4 import BeautifulSoup

from .. import disposition, utils
from . import Handler

LOGGER = logging.getLogger(__name__)


def find_endpoint(id_url=None, links=None, content=None):
    """ Given an identity URL, discover its IndieAuth endpoint

    :param str id_url: an identity URL to check
    :param links: a request.links object from a requests operation
    :param BeautifulSoup content: a BeautifulSoup parse tree of an HTML document
    """
    def _link_endpoint(links):
        if not links:
            return None

        LOGGER.debug("checking indieauth by link header")
        if 'authorization_endpoint' in links:
            return links['authorization_endpoint']['url']
        return None

    def _content_endpoint(content):
        if not content:
            return None

        LOGGER.debug("checking indieauth by link tag")
        link = content.find('link', rel='authorization_endpoint')
        if link:
            return link.get('href')
        return None

    request = utils.request_url(id_url) if id_url and not links or not content else None
    if request:
        links = request.links
        content = BeautifulSoup(request.text, 'html.parser')
    return (_link_endpoint(links) or _content_endpoint(content))


class IndieAuth(Handler):
    """ Directly support login via IndieAuth, without requiring third-party
    IndieLogin brokerage.

    IndieAuth is just barely different enough from baseline OAuth that it's
    easier to just reimplement it directly, rather than trying to use the OAuth
    base class.
    """

    @property
    def service_name(self):
        return 'IndieAuth'

    @property
    def url_schemes(self):
        # pylint:disable=duplicate-code
        return [('%', 'https://website.name')]

    @property
    def description(self):
        return """Supports login via an
        <a href="https://indieweb.org/IndieAuth">IndieAuth</a> provider. """

    @property
    def cb_id(self):
        return 'ia'

    def __init__(self, client_id, token_store, config):
        """ Construct an IndieAuth handler

        :param client_id: The client_id to send to the remote IndieAuth
        provider. Can be a string or a function (e.g. lambda:flask.request.url_root)

        :param max_pending: The maximum number of pending login requests

        :param pending_ttl: How long the user has to complete login, in seconds

        :param token_store: Storage for the tokens
        """

        self._pending = token_store

        self._client_id = client_id

        self._endpoints = expiringdict.ExpiringDict(
            max_len=config.get('INDIEAUTH_MAX_ENDPOINTS', 128),
            max_age_seconds=config.get('INDIEAUTH_ENDPOINT_TTL', 3600))

    def handles_page(self, url, headers, content, links):
        """ If we have the appropriate link rels, register the endpoint now """
        endpoint = find_endpoint(links=links, content=content)

        if endpoint:
            LOGGER.info("%s: has IndieAuth endpoint %s", url, endpoint)
            self._endpoints[url] = endpoint

        return endpoint

    def _get_endpoint(self, id_url):
        if id_url in self._endpoints:
            # We already have it cached, yay
            return self._endpoints[id_url]

        # need to discover it
        endpoint = find_endpoint(id_url)
        if endpoint:
            self._endpoints[id_url] = endpoint
        return endpoint

    def initiate_auth(self, id_url, callback_uri, redir):
        endpoint = self._get_endpoint(id_url)
        if not endpoint:
            return disposition.Error("Failed to get IndieAuth endpoint", redir)

        state = utils.gen_token()
        self._pending[state] = (endpoint, callback_uri, redir)

        client_id = utils.resolve_value(self._client_id)
        LOGGER.debug("Using client_id %s", client_id)

        url = endpoint + '?' + urllib.parse.urlencode({
            'redirect_uri': callback_uri,
            'client_id': client_id,
            'state': state,
            'response_type': 'id',
            'me': id_url})
        return disposition.Redirect(url)

    def check_callback(self, url, get, data):
        # pylint:disable=duplicate-code, too-many-return-statements
        state = get.get('state')
        if not state:
            return disposition.Error("No transaction ID provided", None)
        if state not in self._pending:
            return disposition.Error("Transaction invalid or expired", None)

        endpoint, callback_uri, redir = self._pending[state]

        if 'code' not in get:
            return disposition.Error("Missing auth code", redir)

        # Verify the auth code
        request = requests.post(endpoint, data={
            'code': get['code'],
            'client_id': utils.resolve_value(self._client_id),
            'redirect_uri': callback_uri
        })

        if request.status_code != 200:
            LOGGER.error("Request returned code %d: %s", request.status_code, request.text)
            return disposition.Error("Unable to verify identity", redir)

        try:
            response = request.json()
        except ValueError:
            return disposition.Error("Got invalid response JSON", redir)
        if 'me' not in response:
            return disposition.Error("No identity provided in response", redir)

        return disposition.Verified(response['me'], redir, response)


def from_config(config, token_store):
    """ Generate an IndieAuth handler from the given config dictionary.

    Possible configuration values:

    INDIEAUTH_CLIENT_ID -- the client ID (URL) of your website (required)
    INDIEAUTH_MAX_PENDING -- maximum pending transactions
    INDIEAUTH_PENDING_TTL -- timemout for a pending transction
    INDIEAUTH_MAX_ENDPOINTS -- maximum number of endpoints to cache
    INDIEAUTH_ENDPOINT_TTL -- how long to cache an endpoint for
    """
    return IndieAuth(config['INDIEAUTH_CLIENT_ID'], token_store, config)
