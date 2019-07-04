""" Authl: A wrapper library to simplify the implementation of federated identity """

import logging

import requests

from .handlers import Handler
from . import disposition

LOGGER = logging.getLogger(__name__)


class Authl:
    """ Authentication wrapper """

    def __init__(self, handlers=None):
        """ Initialize an Authl library instance.

        handlers -- a collection of handlers for different authentication
            mechanisms

        """
        self._handlers = handlers or []

    def add_handler(self, handler):
        """ Add another handler to the configured handler list. It will be
        given the lowest priority. """
        self._handlers.append(handler)

    def get_handler_for_url(self, url):
        """ Get the appropriate handler for the specified identity URL.
        Returns a tuple of (handler, id). """
        for pos, handler in enumerate(self._handlers):
            if handler.handles_url(url):
                return handler, pos

        request = requests.get(url)
        for pos, handler in enumerate(self._handlers):
            if handler.handles_page(request.headers, request.text):
                return handler, pos

        return None, -1

    def get_handler_by_id(self, handler_id):
        """ Get the handler with the given ID """
        return self._handlers[handler_id]

    @property
    def handlers(self):
        """ get all of the registered handlers, for UX purposes """
        return [*self._handlers]


def from_config(config, secret_key):
    """ Generate an AUthl handler set from provided configuration directives.

    Arguments:

    config -- a configuration dictionary. See the individual handlers'
        from_config functions to see possible configuration values.
    secret_key -- a signing key to use for the handlers which need one

    Handlers will be enabled based on truthy values of the following keys

        TEST_ENABLED -- enable the TestHandler handler
        EMAIL_FROM -- enable the EmailAddress handler
        INDIELOGIN_CLIENT_ID -- enable the IndieLogin handler

    """

    handlers = []
    if config.get('TEST_ENABLED'):
        from .handlers import test_handler
        handlers.append(test_handler.TestHandler())

    if config.get('EMAIL_FROM'):
        from .handlers import email_addr
        handlers.append(email_addr.from_config(config, secret_key))

    if config.get('INDIELOGIN_CLIENT_ID'):
        from .handlers import indielogin
        handlers.append(indielogin.from_config(config))

    return Authl(handlers)


def setup_flask(app, config,
                login_name='login',
                login_path='/_login',
                login_render_func=None,
                notify_render_func=None,
                callback_name='_authl_callback',
                callback_path='/_cb',
                session_auth_name='me'):
    """ Setup Authl to work with a Flask application.

    The Flask application should be configured with a secret_key before this
    function is called.

    Arguments:

    app -- the application to attach to
    config -- Configuration directives for Authl's handlers. See from_config
        for more information.
    login_name -- The endpoint name for the login handler, for flask.url_for()
    login_path -- The mount point of the login route
    login_render_func -- The function to call to render the login page; if not
        specified a default will be provided. It must take an argument named
        'redir' (for the redir parameter to pass along to flask.url_for) and
        should support Flask message flashing.
    callback_name -- The endpoint name for the callback handler, for
        flask.url_for()
    callback_path -- The mount point of the callback handler
    session_auth_name -- The session parameter to use for the authenticated user
    """

    import flask

    auth = from_config(config, app.secret_key)

    def handle_disposition(d, redir):
        from . import disposition

        # A simple redirection
        if isinstance(d, disposition.Redirect):
            return flask.redirect(d.url)

        # The user is verified; log them in
        if isinstance(d, disposition.Verified):

            flask.session[session_auth_name] = d.identity
            return flask.redirect(redir)

        # The user needs to take some additional action
        if isinstance(d, disposition.Notify):
            return render_notify(redir=redir)

        # The user's login failed
        if isinstance(d, disposition.Error):
            flask.flash(d.message)
            return render_login_form(redir=redir)

        # Something weird happened
        return "Unknown disposition", 500

    def render_login_form(**kwargs):
        if login_render_func:
            return login_render_func(**kwargs)

        # TODO replace this with flask.render_template_string with support for
        # message flashing etc.
        return '''
        <html><body><form method="GET" action="{login}">
        <input type="text" name="me" placeholder="you@example.com">
        <input type="submit" value="go!">
        </form>
        </body></html>
        '''.format(login=flask.url_for(login_name, redir=kwargs.get('redir')))

    suffix_list = ['', '/', '/<path:redir>']

    def login(redir=''):
        from flask import request

        if 'me' in request.args:
            me_url = request.args['me']
            handler, hid = auth.get_handler_for_url(me_url)
            if handler:
                cb_url = flask.url_for(callback_name, hid=hid, redir=redir, _external=True)
                return handle_disposition(handler.initiate_auth(me_url, cb_url), redir)

            # No handler found, so flash an error message to login_form
            flask.flash("Unknown authorization method")

        return render_login_form(redir=redir)
    for sfx in suffix_list:
        app.add_url_rule(login_path + sfx, login_name, login)

    def callback(hid, redir=''):
        from flask import request

        handler = auth.get_handler_by_id(hid)
        return handle_disposition(handler.check_callback(request.url,
                                                         request.args,
                                                         request.form),
                                  redir)
    for sfx in suffix_list:
        app.add_url_rule(callback_path + '/<int:hid>' + sfx, callback_name, callback)
