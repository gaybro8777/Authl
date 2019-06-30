""" Authentication response dispositions """


class Disposition:
    """ Base class for all response dispositions """
    pass


class Redirect(Disposition):
    """ A disposition that indicates that the request should redirect to another URL """

    def __init__(self, url):
        self.url = url


class Verified(Disposition):
    """ A disposition that indicates that the user is verified; it is now up to the
    web app to add that authorization to the user session and redirect the client to the actual view

    profile will just be a MultiDict with whatever other junk the provider includes in the profile,
    which is probably useful for some use case
    """

    def __init__(self, identity, profile=None):
        self.identity = identity
        self.profile = profile or {}


class Notify(Disposition):
    """ A disposition that indicates that a notification should be sent to the user (e.g. "check your email").

    For localization/generality purposes this will probably be configured in the handler by the web app,
    e.g.

    Authl.add_handler(authl.EmailHandler(cdata='templates/check_email.html', send_func=blahblahblah)

    In this case send_func would be a function that takes e.g. email_address and auth_url, or something.
    """

    def __init__(self, message, args=None):
        self.message = message
        self.args = args or {}


class Error(Disposition):
    """ A disposition that indicates that authorization failed, hopefully with
    an informative message. """

    def __init__(self, message):
        self.message = message
