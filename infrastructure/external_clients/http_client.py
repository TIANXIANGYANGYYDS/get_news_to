import requests


class HttpClient:
    def __init__(self):
        self.session = requests.Session()

    def get(self, url: str, **kwargs):
        return self.session.get(url, **kwargs)
