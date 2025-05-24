from flask import g
from wyze_sdk import Client


class WyzeClient:
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        app.teardown_appcontext(self.teardown)

    def teardown(self, exception):
        if hasattr(g, 'wyze_client'):
            g.wyze_client = None

    @property
    def client(self):
        if not hasattr(g, 'wyze_client'):
            g.wyze_client = Client(email=self.app.config['WYZE_EMAIL'],
                                   password=self.app.config['WYZE_PASSWORD'],
                                   key_id=self.app.config['WYZE_KEY_ID'],
                                   api_key=self.app.config['WYZE_API_KEY'])
        return g.wyze_client
